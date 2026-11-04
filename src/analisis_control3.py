import os
import sys
import glob
import io
import numpy as np
import pandas as pd
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import matplotlib.pyplot as plt

# =============================================================================
# CONFIGURACIÓN GENERAL
# =============================================================================
CFG = {
    "dt": 1.0,                 # Paso del tiempo para remuestreo [s]
    "min_hold_sp": 10.0,       # Tiempo mínimo para validar cambio de SP [s]
    "ventana_suav": 9,         # Tamaño de ventana para media móvil [s]
    "frac_alcanzado": 0.80,    # Fracción alcanzada para iniciar búsqueda de perturbaciones
    "umbral_min": 1.0,         # Caída/Subida mínima de temperatura para declarar perturbación [°C]
    "umbral_rel": 0.10,        # Umbral relativo según magnitud del escalón
    "t_estable": 30.0,         # Tiempo mínimo de estabilidad previa [s]
    "t_pre": 15.0,             # Ventana para promediar valor previo [s]
    "t_ss": 10.0,              # Ventana para promediar valor en régimen estable [s]
    "dpi_grafica": 100,        # Resolución ligera para imagen incrustada en Excel
    "carpeta_datos": "dataControl",
    "carpeta_salida": os.path.join("AnalisisDatos", "Control")
}

_trapz = getattr(np, "trapezoid", None) or np.trapz

# =============================================================================
# PREPROCESAMIENTO Y LIMPIEZA DE DATOS
# =============================================================================
def seleccionar_archivo_datos(carpeta_datos="dataControl"):
    archivos = sorted(glob.glob(os.path.join(carpeta_datos, "*.xlsx")))
    archivos = [a for a in archivos if not os.path.basename(a).startswith("~$")]
    if not archivos:
        print(f"No se encontraron archivos Excel en la carpeta '{carpeta_datos}'.")
        return None
    
    print(f"Archivos disponibles en '{carpeta_datos}':")
    for i, arch in enumerate(archivos):
        print(f"[{i}] {os.path.basename(arch)}")
    
    if len(archivos) == 1:
        print(f"Seleccionando único archivo: {os.path.basename(archivos[0])}")
        return archivos[0]

    while True:
        try:
            sel = int(input(f"Seleccione el número del archivo (0-{len(archivos) - 1}): "))
            if 0 <= sel < len(archivos):
                return archivos[sel]
            print("Selección inválida.")
        except ValueError:
            print("Por favor ingrese un número válido.")

def preparar_datos(df, dt=1.0):
    """Limpia el tiempo (promedia marcas duplicadas) y remuestrea a dt uniforme."""
    d = df.copy()
    d["Tiempo"] = pd.to_numeric(d["Tiempo"], errors="coerce")
    d = d.dropna(subset=["Tiempo"]).sort_values("Tiempo", kind="stable")
    
    cols = [c for c in d.columns if str(c).startswith(("Temperatura", "Corriente", "PWM", "SetPoint"))]
    g = d.groupby("Tiempo")[cols].mean()
    
    malla = np.arange(g.index.min(), g.index.max() + dt / 2, dt)
    out = pd.DataFrame({"Tiempo": malla})
    
    for c in cols:
        s = g[c].dropna()
        if s.empty:
            out[c] = np.nan
        elif str(c).startswith(("PWM", "SetPoint")):
            out[c] = s.reindex(s.index.union(malla)).ffill().reindex(malla).values
        else:
            out[c] = np.interp(malla, s.index.values, s.values)
    return out

def media_movil(x, w):
    w = max(1, int(w))
    if w == 1:
        return x.copy()
    pi = w // 2
    xp = np.pad(x, (pi, w - 1 - pi), mode="edge")
    return np.convolve(xp, np.ones(w) / w, mode="valid")

# =============================================================================
# DETECCIÓN DE EVENTOS Y FASES
# =============================================================================
def detectar_escalon_sp(t, sp, cfg=CFG):
    dt = t[1] - t[0]
    n = len(sp)
    ini = np.r_[0, np.where(np.abs(np.diff(sp)) > 1e-9)[0] + 1]
    fin = np.r_[ini[1:], n]
    
    segs = [dict(i0=int(a), i1=int(b), valor=float(sp[a]),
                 valido=((b - a) * dt >= cfg["min_hold_sp"]) or b == n)
            for a, b in zip(ini, fin)]
    
    if len(segs) == 1:
        return 0, float(sp[0]), n

    idx_step = segs[1]["i0"]
    validos = [s for s in segs[1:] if s["valido"]]
    sp_obj = validos[0]["valor"]
    idx_end = validos[1]["i0"] if len(validos) > 1 else n
    return idx_step, sp_obj, idx_end

def detectar_perturbaciones(t, pv, idx_step, idx_end, y_ini, sp, cfg=CFG):
    dt = t[1] - t[0]
    ys = media_movil(pv, cfg["ventana_suav"] / dt)
    delta = sp - y_ini
    umbral = max(cfg["umbral_min"], cfg["umbral_rel"] * abs(delta))
    if abs(delta) < 1e-9:
        return [], ys

    sgn = 1.0 if delta > 0 else -1.0
    prog = sgn * (ys - y_ini) / abs(delta)
    cand = np.where(prog[idx_step:idx_end] >= cfg["frac_alcanzado"])[0]
    if cand.size == 0:
        return [], ys
    i_a = idx_step + int(cand[0])

    eventos = []
    i = i_a + 1
    n_est = int(cfg["t_estable"] / dt)
    n_pre = max(1, int(cfg["t_pre"] / dt))

    while i < idx_end:
        caida = np.max(ys[max(i_a, i - 120):i + 1]) - ys[i]
        subida = ys[i] - np.min(ys[max(i_a, i - 120):i + 1])

        if caida >= umbral and caida >= subida:
            tipo = "BAJA"
        elif subida >= umbral:
            tipo = "SUBE"
        else:
            i += 1
            continue

        i_on = i
        y_ext, i_ext = ys[i], i
        k = i
        while k < idx_end:
            nuevo = (ys[k] < y_ext - 1e-6) if tipo == "BAJA" else (ys[k] > y_ext + 1e-6)
            if nuevo:
                y_ext, i_ext = ys[k], k
            elif abs(ys[k] - y_ext) >= (0.5 * umbral):
                break
            elif k - i_ext >= n_est:
                break
            k += 1

        y_pre = float(np.mean(pv[max(0, i_on - n_pre):i_on + 1]))
        eventos.append(dict(tipo=tipo, i_ini=int(i_on), i_ext=int(i_ext), y_pre=y_pre, y_ext=float(y_ext)))
        i = int(i_ext) + 1

    return eventos, ys

# =============================================================================
# CÁLCULO DE MÉTRICAS
# =============================================================================
def analizar_planta(t, pv, sp, pwm, corr=None, nombre="Planta", cfg=CFG):
    idx_step, sp_obj, idx_end = detectar_escalon_sp(t, sp, cfg)
    y_ini = float(np.mean(pv[max(0, idx_step - 5):idx_step])) if idx_step > 0 else float(pv[0])
    
    eventos, _ = detectar_perturbaciones(t, pv, idx_step, idx_end, y_ini, sp_obj, cfg)
    i_fin_esc = eventos[0]["i_ini"] if eventos else idx_end

    dt = t[1] - t[0]
    tt = t[idx_step:i_fin_esc] - t[idx_step]
    y = pv[idx_step:i_fin_esc]
    u = pwm[idx_step:i_fin_esc]
    delta_sp = sp_obj - y_ini
    sgn = 1.0 if delta_sp >= 0 else -1.0

    # Temperaturas pico y régimen permanente
    n_ss = max(1, int(cfg["t_ss"] / dt))
    y_max = float(y.max() if sgn > 0 else y.min())
    t_peak = float(tt[np.argmax(y) if sgn > 0 else np.argmin(y)])
    y_ss = float(np.mean(y[-n_ss:]))
    error_ss = float(sp_obj - y_ss)

    # CÁLCULO DE SOBREIMPULSO (2 Métodos)
    sobreimpulso_abs = max(0.0, sgn * (y_max - sp_obj))
    os_pct_delta = (sobreimpulso_abs / abs(delta_sp)) * 100.0 if abs(delta_sp) > 1e-9 else 0.0
    os_pct_sp = (sobreimpulso_abs / abs(sp_obj)) * 100.0 if abs(sp_obj) > 1e-9 else 0.0

    # Tiempos de respuesta
    t_rise = t_s2 = t_s5 = np.nan
    if abs(delta_sp) > 1e-9:
        prog = (y - y_ini) / delta_sp
        i10, i90 = np.where(prog >= 0.10)[0], np.where(prog >= 0.90)[0]
        if i10.size and i90.size:
            t_rise = float(tt[i90[0]] - tt[i10[0]])

        fuera_2 = np.where(np.abs(y - sp_obj) > 0.02 * abs(delta_sp))[0]
        t_s2 = float(tt[fuera_2[-1] + 1]) if fuera_2.size and (fuera_2[-1] + 1) < len(tt) else np.nan

        fuera_5 = np.where(np.abs(y - sp_obj) > 0.05 * abs(delta_sp))[0]
        t_s5 = float(tt[fuera_5[-1] + 1]) if fuera_5.size and (fuera_5[-1] + 1) < len(tt) else np.nan

    # Integrales de error
    e = sp_obj - y
    iae = float(_trapz(np.abs(e), tt))
    ise = float(_trapz(e ** 2, tt))
    itae = float(_trapz(tt * np.abs(e), tt))

    # Esfuerzo de control y corriente
    pwm_max = float(u.max())
    pwm_ss = float(np.mean(u[-n_ss:]))
    tv_u = float(np.sum(np.abs(np.diff(u))))

    i_max = i_ss = np.nan
    if corr is not None and not np.all(np.isnan(corr)):
        c = corr[idx_step:i_fin_esc]
        i_max, i_ss = float(np.nanmax(c)), float(np.nanmean(c[-n_ss:]))

    # Análisis de la primera perturbación si existe
    info_pert = None
    if eventos:
        ev = eventos[0]
        i0, i1 = ev["i_ini"], (eventos[1]["i_ini"] if len(eventos) > 1 else idx_end)
        y_p = pv[i0:i1]
        u_p = pwm[i0:i1]
        t_p = t[i0:i1]
        info_pert = {
            "tipo": ev["tipo"],
            "t_inicio": float(t[i0]),
            "y_pre": float(ev["y_pre"]),
            "y_min": float(np.min(y_p)),
            "caida_temp": float(ev["y_pre"] - np.min(y_p)),
            "pwm_max": float(np.max(u_p)),
            "tiempo_recuperacion": float(t_p[np.where(y_p >= (sp_obj - 0.5))[0][0]] - t_p[0]) if np.any(y_p >= (sp_obj - 0.5)) else np.nan,
            "iae_pert": float(_trapz(np.abs(sp_obj - y_p), t_p - t_p[0]))
        }

    return {
        "planta": nombre,
        "sp_final": sp_obj,
        "y_inicial": y_ini,
        "delta_sp": delta_sp,
        "y_max": y_max,
        "t_peak": t_peak,
        "sobreimpulso_abs": sobreimpulso_abs,
        "os_pct_delta": os_pct_delta,
        "os_pct_sp": os_pct_sp,
        "t_rise": t_rise,
        "t_settling_5": t_s5,
        "t_settling_2": t_s2,
        "y_ss": y_ss,
        "error_ss": error_ss,
        "iae": iae,
        "ise": ise,
        "itae": itae,
        "pwm_max": pwm_max,
        "pwm_ss": pwm_ss,
        "tv_u": tv_u,
        "i_max": i_max,
        "i_ss": i_ss,
        "perturbacion": info_pert
    }

# =============================================================================
# GENERACIÓN DE GRÁFICAS LIGERAS
# =============================================================================
def generar_figura_resumen(t, plantas, m1, m2=None):
    fig, axs = plt.subplots(2, 2, figsize=(11, 7))
    
    # 1. Respuesta Temporal
    axs[0, 0].plot(t, plantas[0]["sp"], "k--", label="SP", alpha=0.7)
    axs[0, 0].plot(t, plantas[0]["pv"], "r-", lw=1.5, label=f'Q1 (OS={m1["os_pct_delta"]:.1f}%)')
    if m2:
        axs[0, 0].plot(t, plantas[1]["pv"], "b-", lw=1.5, label=f'Q2 (OS={m2["os_pct_delta"]:.1f}%)')
    axs[0, 0].set_title("Respuesta Temporal (PV vs SP)", fontsize=10, fontweight="bold")
    axs[0, 0].set_ylabel("Temperatura [°C]")
    axs[0, 0].grid(True, ls=":", alpha=0.5)
    axs[0, 0].legend(fontsize=8)

    # 2. Señal de Error
    err1 = plantas[0]["sp"] - plantas[0]["pv"]
    axs[0, 1].plot(t, err1, "r-", lw=1.2, label=f'Error Q1 (IAE={m1["iae"]:.0f})')
    if m2:
        err2 = plantas[1]["sp"] - plantas[1]["pv"]
        axs[0, 1].plot(t, err2, "b-", lw=1.2, label=f'Error Q2 (IAE={m2["iae"]:.0f})')
    axs[0, 1].axhline(0, color="k", ls="--", lw=0.8)
    axs[0, 1].set_title("Señal de Error e(t)", fontsize=10, fontweight="bold")
    axs[0, 1].set_ylabel("Error [°C]")
    axs[0, 1].grid(True, ls=":", alpha=0.5)
    axs[0, 1].legend(fontsize=8)

    # 3. Esfuerzo de Control (PWM)
    axs[1, 0].plot(t, plantas[0]["pwm"], "r-", lw=1.2, label="PWM Q1")
    if m2:
        axs[1, 0].plot(t, plantas[1]["pwm"], "b-", lw=1.2, label="PWM Q2")
    axs[1, 0].set_title("Esfuerzo de Control (PWM)", fontsize=10, fontweight="bold")
    axs[1, 0].set_ylabel("Ciclo de Trabajo [%]")
    axs[1, 0].set_xlabel("Tiempo [s]")
    axs[1, 0].set_ylim(-5, 105)
    axs[1, 0].grid(True, ls=":", alpha=0.5)
    axs[1, 0].legend(fontsize=8)

    # 4. Consumo de Corriente
    if plantas[0]["corr"] is not None and not np.all(np.isnan(plantas[0]["corr"])):
        axs[1, 1].plot(t, plantas[0]["corr"], "r-", lw=1.2, label="Corriente Q1")
    if m2 and plantas[1]["corr"] is not None and not np.all(np.isnan(plantas[1]["corr"])):
        axs[1, 1].plot(t, plantas[1]["corr"], "b-", lw=1.2, label="Corriente Q2")
    axs[1, 1].set_title("Consumo de Corriente", fontsize=10, fontweight="bold")
    axs[1, 1].set_ylabel("Corriente [mA]")
    axs[1, 1].set_xlabel("Tiempo [s]")
    axs[1, 1].grid(True, ls=":", alpha=0.5)
    if axs[1, 1].has_data():
        axs[1, 1].legend(fontsize=8)

    plt.tight_layout()
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=CFG["dpi_grafica"], bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

# =============================================================================
# EXPORTACIÓN OPTIMIZADA A EXCEL
# =============================================================================
def limpiar_num(x, dec=2):
    if x is None:
        return None
    if isinstance(x, str):
        return x
    try:
        if np.isnan(x):
            return None
    except (TypeError, ValueError):
        pass
    
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        r = round(float(x), dec)
        return int(r) if r.is_integer() else r
    return x

def exportar_excel_resumido(m1, m2=None, df_params=None, img_buf=None, archivo="Control.xlsx"):
    os.makedirs(CFG["carpeta_salida"], exist_ok=True)
    nombre_out = f"AnalisisControl_{os.path.basename(archivo)}"
    ruta_out = os.path.join(CFG["carpeta_salida"], nombre_out)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ResumenControl"
    ws.views.sheetView[0].showGridLines = True

    # Estilos
    fill_hdr = PatternFill("solid", fgColor="1F4E78")
    fill_sec = PatternFill("solid", fgColor="D9E1F2")
    font_hdr = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_sec = Font(name="Arial", size=10, bold=True, color="1F4E78")
    font_cell = Font(name="Arial", size=9)
    borde = Border(bottom=Side(style="thin", color="D9E1F2"))

    # Encabezados de métricas
    ws.cell(row=1, column=1, value="Métrica de Desempeño").font = font_hdr
    ws.cell(row=1, column=1).fill = fill_hdr
    ws.cell(row=1, column=2, value="Q1").font = font_hdr
    ws.cell(row=1, column=2).fill = fill_hdr
    if m2:
        ws.cell(row=1, column=3, value="Q2").font = font_hdr
        ws.cell(row=1, column=3).fill = fill_hdr

    filas_datos = [
        ("SetPoint [°C]", m1["sp_final"], m2["sp_final"] if m2 else None, 2),
        ("Delta SP [°C]", m1["delta_sp"], m2["delta_sp"] if m2 else None, 2),
        ("Temp Máxima [°C]", m1["y_max"], m2["y_max"] if m2 else None, 2),
        ("Tiempo Pico [s]", m1["t_peak"], m2["t_peak"] if m2 else None, 1),
        ("Sobreimpulso Absoluto [°C]", m1["sobreimpulso_abs"], m2["sobreimpulso_abs"] if m2 else None, 2),
        ("Sobreimpulso (% respecto ΔSP)", m1["os_pct_delta"], m2["os_pct_delta"] if m2 else None, 2),
        ("Sobreimpulso (% respecto SP)", m1["os_pct_sp"], m2["os_pct_sp"] if m2 else None, 2),
        ("Tiempo Subida tr (10-90%) [s]", m1["t_rise"], m2["t_rise"] if m2 else None, 1),
        ("Tiempo Establ. 5% [s]", m1["t_settling_5"], m2["t_settling_5"] if m2 else None, 1),
        ("Tiempo Establ. 2% [s]", m1["t_settling_2"], m2["t_settling_2"] if m2 else None, 1),
        ("Temp Final Yss [°C]", m1["y_ss"], m2["y_ss"] if m2 else None, 2),
        ("Error Regimen ess [°C]", m1["error_ss"], m2["error_ss"] if m2 else None, 2),
        ("IAE (Integral Abs. Error)", m1["iae"], m2["iae"] if m2 else None, 1),
        ("ISE (Integral Cuad. Error)", m1["ise"], m2["ise"] if m2 else None, 1),
        ("ITAE (Integral Ponderada)", m1["itae"], m2["itae"] if m2 else None, 1),
        ("PWM Máximo [%]", m1["pwm_max"], m2["pwm_max"] if m2 else None, 1),
        ("PWM Estable [%]", m1["pwm_ss"], m2["pwm_ss"] if m2 else None, 1),
        ("Variación Total TV(u)", m1["tv_u"], m2["tv_u"] if m2 else None, 1),
        ("Corriente Máx [mA]", m1["i_max"], m2["i_max"] if m2 else None, 1),
    ]

    for r_idx, (label, v1, v2, dec) in enumerate(filas_datos, start=2):
        c1 = ws.cell(row=r_idx, column=1, value=label)
        c2 = ws.cell(row=r_idx, column=2, value=limpiar_num(v1, dec))
        c1.font, c2.font = font_cell, font_cell
        c1.border, c2.border = borde, borde
        if m2:
            c3 = ws.cell(row=r_idx, column=3, value=limpiar_num(v2, dec))
            c3.font, c3.border = font_cell, borde

    # Parámetros PID
    col_start = 5
    if df_params is not None and not df_params.empty:
        cols_pid = [c for c in ['Planta', 'Kp', 'Ki', 'Kd', 'Ts', 'Cambio (s)'] if c in df_params.columns]
        for c_idx, h in enumerate(cols_pid, start=col_start):
            cell = ws.cell(row=1, column=c_idx, value=h)
            cell.font, cell.fill = font_hdr, fill_hdr
        
        for f_idx, (_, row) in enumerate(df_params.iterrows(), start=2):
            for c_idx, h in enumerate(cols_pid, start=col_start):
                cell = ws.cell(row=f_idx, column=c_idx, value=limpiar_num(row[h], 4))
                cell.font, cell.border = font_cell, borde

    # Sección de Perturbaciones si existen
    p1, p2 = m1.get("perturbacion"), (m2.get("perturbacion") if m2 else None)
    if p1 or p2:
        r_start = len(filas_datos) + 3
        cell_sec = ws.cell(row=r_start, column=1, value="Rechazo a Perturbaciones")
        cell_sec.font, cell_sec.fill = font_sec, fill_sec
        
        filas_p = [
            ("Caída Temp ΔT [°C]", p1["caida_temp"] if p1 else None, p2["caida_temp"] if p2 else None, 2),
            ("PWM Máx Reacción [%]", p1["pwm_max"] if p1 else None, p2["pwm_max"] if p2 else None, 1),
            ("Tiempo Recuperación [s]", p1["tiempo_recuperacion"] if p1 else None, p2["tiempo_recuperacion"] if p2 else None, 1),
            ("IAE Perturbación", p1["iae_pert"] if p1 else None, p2["iae_pert"] if p2 else None, 1),
        ]
        for offset, (label, vp1, vp2, dec) in enumerate(filas_p, start=1):
            curr_row = r_start + offset
            c1 = ws.cell(row=curr_row, column=1, value=label)
            c2 = ws.cell(row=curr_row, column=2, value=limpiar_num(vp1, dec))
            c1.font, c2.font = font_cell, font_cell
            c1.border, c2.border = borde, borde
            if m2:
                c3 = ws.cell(row=curr_row, column=3, value=limpiar_num(vp2, dec))
                c3.font, c3.border = font_cell, borde

    # Anchos de columna optimizados
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 4
    for col_letter in ["E", "F", "G", "H", "I", "J"]:
        ws.column_dimensions[col_letter].width = 12

    # Imagen del gráfico incrustada de forma eficiente
    if img_buf:
        img_buf.seek(0)
        img = XLImage(img_buf)
        img.width, img.height = 640, 400
        ws.add_image(img, "E6")

    wb.save(ruta_out)
    return ruta_out

# =============================================================================
# PROGRAMA PRINCIPAL
# =============================================================================
def main():
    path_documento = seleccionar_archivo_datos(CFG["carpeta_datos"])
    if not path_documento:
        return
    print(f"\nProcesando: {os.path.basename(path_documento)}")

    df_raw = pd.read_excel(path_documento)
    df = preparar_datos(df_raw, CFG["dt"])
    t = df["Tiempo"].to_numpy(dtype=float)

    def col(nombre):
        return df[nombre].to_numpy(dtype=float) if nombre in df.columns else None

    sp1 = "SetPoint1" if "SetPoint1" in df.columns else "SetPoint"
    plantas = [dict(nombre="Q1", pv=col("Temperatura1"), sp=col(sp1), pwm=col("PWM1"), corr=col("Corriente1"))]
    
    tiene_q2 = all(c in df.columns for c in ("Temperatura2", "PWM2", "SetPoint2"))
    if tiene_q2:
        plantas.append(dict(nombre="Q2", pv=col("Temperatura2"), sp=col("SetPoint2"), pwm=col("PWM2"), corr=col("Corriente2")))

    m1 = analizar_planta(t, plantas[0]["pv"], plantas[0]["sp"], plantas[0]["pwm"], plantas[0]["corr"], "Q1", CFG)
    m2 = analizar_planta(t, plantas[1]["pv"], plantas[1]["sp"], plantas[1]["pwm"], plantas[1]["corr"], "Q2", CFG) if tiene_q2 else None

    cols_pid = [c for c in ["Planta", "Kp", "Ki", "Kd", "Ts", "Cambio (s)"] if c in df_raw.columns]
    df_params = df_raw[cols_pid].dropna(how="all").copy() if cols_pid else None

    print("\nGenerando gráfica y reporte comprimido...")
    img_buf = generar_figura_resumen(t, plantas, m1, m2)
    ruta_excel = exportar_excel_resumido(m1, m2, df_params, img_buf, os.path.basename(path_documento))

    print(f"Reporte Excel generado correctamente en: {ruta_excel}")
    print("Mostrando interfaz gráfica...")
    plt.show()

if __name__ == "__main__":
    main()