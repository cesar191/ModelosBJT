import os
import glob
import io
from datetime import datetime
import numpy as np
import pandas as pd
import openpyxl
from openpyxl.drawing.image import Image
import matplotlib.pyplot as plt
import control as co
from collections import Counter
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Configuración general: modificar aquí los valores del experimento.
CONFIG = {
    "carpeta_datos": "dataIdentificacion",
    "carpeta_salida": os.path.join("AnalisisDatos", "Fopdt"),
    "capacidad_calorifica": 650,
    "alpha_termico": 0.014,
    "coeficiente_transferencia": 5,
    "tipo_control": "PID",
    "pid_empirico": [3.0, 0.02, 0.3],
    "dpi_graficas": 180,
    "mostrar_graficas": True,
}

def seleccionar_archivo_datos(carpeta_datos="dataIdentificacion"):
    os.system('cls' if os.name == 'nt' else 'clear')

    archivos = sorted(glob.glob(os.path.join(carpeta_datos, "*.xlsx")))
    archivos = [a for a in archivos if not os.path.basename(a).startswith("~$")]
    if not archivos:
        print(f"No se encontraron archivos Excel en la carpeta '{carpeta_datos}'.")
        return None
    
    print("Archivos disponibles:")
    for i, arch in enumerate(archivos):
        print(f"[{i}] {os.path.basename(arch)}")
    
    while True:
        try:
            seleccion = int(input(f"Seleccione el numero del archivo (0-{len(archivos)-1}): "))
            if 0 <= seleccion < len(archivos):
                return archivos[seleccion]
            print("Seleccion invalida.")
        except ValueError:
            print("Por favor ingrese un numero valido.")

def funcion_fopdt_planta(dyt, pwm_trabajo, dt):
    delta_y = dyt[-1] - dyt[0]
    Kp_gain = delta_y / pwm_trabajo
    
    temp_63 = 0.632 * delta_y
    index_63 = np.argmax(dyt >= temp_63)
    tiempo_63 = dt[index_63] - dt[0]
    
    index_inicio = np.argmax(dyt >= 0.5)
    time_star = dt[index_inicio] - dt[0] 
    
    tau_opt = tiempo_63 - time_star
    theta_opt = time_star

    return [Kp_gain, tau_opt, theta_opt]

def funcion_fopdt2_planta(dyt, pwm_trabajo, dt):
    delta_y = dyt[-1] - dyt[0]
    Kp_gain = delta_y / pwm_trabajo
    
    temp_85 = 0.853 * delta_y
    index_85 = np.argmax(dyt >= temp_85)
    tiempo_85 = dt[index_85] - dt[0]
    
    temp_35 = 0.353 * delta_y
    index_35 = np.argmax(dyt >= temp_35)
    tiempo_35 = dt[index_35] - dt[0]
    
    tau_opt = 0.675 * (tiempo_85 - tiempo_35)
    theta_opt = abs(1.294 * tiempo_35 - 0.294 * tiempo_85)

    return [Kp_gain, tau_opt, theta_opt]

def funcion_modelo_termico(cap_cal, alpha, cof_tra_cal, t_final):
    sigma = 5.67e-8         # Constante de Stefan-Boltzmann (fijo)
    eps = 0.9               # Emisividad del material (fijo)
    area = 1.2e-3           # Area efectiva del disipador [m2] (fijo)
    masa = 0.004            # Masa del componente [kg] (fijo)

    den_comun = cof_tra_cal * area + 4 * eps * sigma * area * (t_final + 273.15)**3
    
    Kp_gain = alpha / den_comun
    tau = (masa * cap_cal) / den_comun
    return [Kp_gain, tau]

def _indice_menor_igual(valores, umbral):
    """Ultimo indice con valor <= umbral, como MATCH aproximado de Excel en un tramo creciente."""
    idx = np.where(np.asarray(valores) <= umbral)[0]
    if len(idx) == 0:
        return 0
    return int(idx[-1])

def leer_fopdt_excel(tiempo, temperatura, pwm, valores_celda=None):
    """Lee Kp, Tau y Theta guardados en el Excel de identificacion."""
    if valores_celda is not None and len(valores_celda) >= 3:
        numeros = []
        for valor in valores_celda[:3]:
            try:
                numeros.append(float(valor))
            except (TypeError, ValueError):
                numeros.append(np.nan)
        if np.all(np.isfinite(numeros)):
            return numeros[0], numeros[1], numeros[2]

    tiempo = np.asarray(tiempo, dtype=float)
    temperatura = np.asarray(temperatura, dtype=float)
    pwm = np.asarray(pwm, dtype=float)
    if len(tiempo) == 0:
        return np.nan, np.nan, np.nan

    pwm_modo = Counter(pwm).most_common(1)[0][0]
    denominador = pwm_modo - np.min(pwm)
    if denominador == 0:
        return np.nan, np.nan, np.nan

    kp = (np.max(temperatura) - np.min(temperatura)) / denominador
    t_modo = tiempo[int(np.where(pwm == pwm_modo)[0][0])]
    idx_max = int(np.argmax(temperatura))
    tramo_t = tiempo[:idx_max + 1]
    tramo_y = temperatura[:idx_max + 1]
    t_63 = tramo_t[_indice_menor_igual(tramo_y, np.max(temperatura) * 0.632)]
    t_td = tramo_t[_indice_menor_igual(tramo_y, np.min(temperatura) * 1.02)]
    return float(kp), float(t_63 - t_modo), float(t_td - t_modo)

def recortar_senal(y, u, t, value_recort):
    dyt, dxt, dt = [], [], []
    escalon = [[], []]  
    
    for i in range(1, len(u)):
        if u[i] - u[i-1] != 0 and u[i] == value_recort:
            escalon[0].append(u[i] - u[i-1])
            escalon[1].append(t[i])          
        
        if u[i] == value_recort:
            dyt.append(y[i] - y[0])
            dxt.append(u[i])
            dt.append(t[i])
            
    dyt = np.array(dyt)
    dxt = np.array(dxt)
    escalon = np.array(escalon)
    dt = np.array(dt) - dt[0]
    
    return dyt, dxt, dt, escalon

def system_control(Kp_Gain, Tau, Tetha, T_muestreo, typePID):
    T_Control = Tetha + (T_muestreo / 2)
    resolucion = 1
    typePID = typePID.upper()
    
    kpzn, kizn, kdzn = 0, 0, 0
    kpiae, kiiae, kdiae = 0, 0, 0

    if typePID == "PID":
        # Ziegler-Nichols
        kpzn = (1.2 * (Tau / (Kp_Gain * T_Control))) / resolucion
        kizn = (kpzn / (2 * T_Control)) / resolucion
        kdzn = (kpzn * (0.5 * T_Control)) / resolucion
        # IAE
        kpiae = (1.086 / Kp_Gain) * ((T_Control / Tau)**(-0.869))
        kiiae = kpiae / (Tau / (0.740 - 0.130 * (T_Control / Tau)))
        kdiae = kpiae * 0.348 * Tau * ((T_Control / Tau)**(0.914))

    elif typePID == "PI":
        # Ziegler-Nichols
        kpzn = (0.45 / Kp_Gain)
        kizn = (kpzn / (T_Control / 0.3))
        # IAE
        kpiae = (0.758 / Kp_Gain) * ((T_Control / Tau)**(-0.861))
        kiiae = (kpiae / (Tau / (1.02 - 0.323 * (T_Control / Tau))))

    elif typePID == "P":
        # Ziegler-Nichols
        kpzn = Tau / (Kp_Gain * T_Control)
        # IAE (aproximacion)
        kpiae = (Kp_Gain / 0.8) 
            
    return [kpzn, kizn, kdzn], [kpiae, kiiae, kdiae]

def calcular_rmse_porcentaje(y_real, y_modelo):
    """RMSE normalizado por el cambio de temperatura, en porcentaje."""
    if y_real is None or y_modelo is None:
        return np.nan
    y_real = np.ravel(np.asarray(y_real, dtype=float))
    y_modelo = np.ravel(np.asarray(y_modelo, dtype=float))
    n = min(len(y_real), len(y_modelo))
    if n == 0:
        return np.nan
    residuo = y_real[:n] - y_modelo[:n]
    if not np.all(np.isfinite(residuo)):
        return np.nan
    rmse = np.sqrt(np.mean(residuo ** 2))
    delta_t = abs(y_real[:n][-1] - y_real[:n][0])
    if delta_t == 0:
        return np.nan
    return 100.0 * rmse / delta_t

def limpiar_numero(x, dec=2):
    if x is None:
        return None
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

def formatear_rmse(valor):
    if valor is None:
        return None
    try:
        if np.isnan(valor):
            return None
    except (TypeError, ValueError):
        return None
    return f"{float(valor):.2f}%"

def similitud_desde_rmse(rmse):
    """Porcentaje de similitud complementario al RMSE normalizado."""
    if rmse is None:
        return np.nan
    try:
        if np.isnan(rmse):
            return np.nan
    except (TypeError, ValueError):
        return np.nan
    return 100.0 - float(rmse)

def etiqueta_con_similitud(nombre, rmse):
    similitud = similitud_desde_rmse(rmse)
    if not np.isfinite(similitud):
        return nombre
    return f"{nombre} (similitud {similitud:.1f}%)"

def exportar_analisis_excel(amplitud_escalon, dyt, dxt, dt, temp_ini, temp_fin,
                            p_fopdt, p_fopdt2, p_termicos,
                            kp_ex, tau_ex, theta_ex,
                            rmse_m1, rmse_m2, rmse_term, rmse_ex,
                            muestreo, ctrl_zn, ctrl_iae, ctrl_emp,
                            img_buf=None,
                            img_plantas=None,
                            archivo_analizar="Adquirir.xlsx",
                            carpeta_salida=CONFIG["carpeta_salida"]):
    # exist_ok=True evita lanzar error si la carpeta ya existe
    os.makedirs(carpeta_salida, exist_ok=True)
    nombre_archivo = f"AnalisisFopdt_{archivo_analizar}"
    ruta_archivo = os.path.join(carpeta_salida, nombre_archivo)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AnalisisFOPDT"
    ws1 = wb.create_sheet(title="SignalReport")

    delta_temp = temp_fin - temp_ini
    filas_datos = [
        ("planta", "Planta Q1"),
        ("Escalon PWM [%]", amplitud_escalon),
        ("Temp Ambiente [°C]", temp_ini),
        ("Temp Final [°C]", temp_fin),
        ("Delta Temp ΔT [°C]", delta_temp),
        ("Tiempo Muestreo Ts [s]", muestreo),
        ("--- Rangos Recomendados Ts ---", None),
        ("Ts segun Tau (FOPDT 1) [s]", f"{p_fopdt[1]*0.05:.2f} a {p_fopdt[1]*0.15:.2f}"),
        ("Ts segun Theta (FOPDT 1) [s]", f"{p_fopdt[2]*0.2:.2f} a {p_fopdt[2]*0.6:.2f}"),
    ]

    for r_idx, (label, val) in enumerate(filas_datos, start=1):
        ws.cell(row=r_idx, column=1, value=label)
        v = limpiar_numero(val, dec=4) if isinstance(val, (int, float, np.floating, np.integer)) else val
        if v is not None:
            ws.cell(row=r_idx, column=2, value=v)

    # Tabla PID en E1:I4
    pid_headers = ["Control", "Kp", "Ki", "Kd", "Ts [s]"]
    for c_idx, h in enumerate(pid_headers, start=5):
        ws.cell(row=1, column=c_idx, value=h)

    pid_filas = [
        ("Ziegler-Nichols", ctrl_zn[0], ctrl_zn[1], ctrl_zn[2], muestreo),
        ("IAE", ctrl_iae[0], ctrl_iae[1], ctrl_iae[2], muestreo),
        ("Empirico", ctrl_emp[0], ctrl_emp[1], ctrl_emp[2], muestreo),
    ]
    for r_offset, fila in enumerate(pid_filas, start=2):
        for c_idx, val in enumerate(fila, start=5):
            v = limpiar_numero(val, dec=4) if isinstance(val, (int, float, np.floating, np.integer)) else val
            ws.cell(row=r_offset, column=c_idx, value=v)

    # Tabla de modelos en E6:I10 (KP, Tau, Theta, RMSE%)
    modelo_headers = ["planta", "KP", "Tau", "Theta", "RMSE"]
    for c_idx, h in enumerate(modelo_headers, start=5):
        ws.cell(row=6, column=c_idx, value=h)

    modelos = [
        ("Metodo 1", p_fopdt[0], p_fopdt[1], p_fopdt[2], rmse_m1),
        ("metodo 2", p_fopdt2[0], p_fopdt2[1], p_fopdt2[2], rmse_m2),
        ("Termico", p_termicos[0], p_termicos[1], None, rmse_term),
        ("excel", kp_ex, tau_ex, theta_ex, rmse_ex),
    ]
    for r_offset, (nombre, kp, tau, theta, rmse) in enumerate(modelos, start=7):
        ws.cell(row=r_offset, column=5, value=nombre)
        for c_idx, val in enumerate((kp, tau, theta), start=6):
            v = limpiar_numero(val, dec=4)
            if v is not None:
                ws.cell(row=r_offset, column=c_idx, value=v)
        rmse_txt = formatear_rmse(rmse)
        if rmse_txt is not None:
            ws.cell(row=r_offset, column=9, value=rmse_txt)

    signal_headers = ["Tiempo", "Temperatura", "PWM"]
    for c_idx, h in enumerate(signal_headers, start=1):
        ws1.cell(row=1, column=c_idx, value=h)
    for i_row in range(len(dyt)):
        ws1.cell(row=i_row + 2, column=1, value=limpiar_numero(dt[i_row], dec=4))
        ws1.cell(row=i_row + 2, column=2, value=limpiar_numero(dyt[i_row], dec=4))
        ws1.cell(row=i_row + 2, column=3, value=limpiar_numero(dxt[i_row], dec=4))

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 4
    ws.column_dimensions["D"].width = 4
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 12
    ws.column_dimensions["I"].width = 12

    if img_plantas is not None:
        img_plantas.seek(0)
        img = Image(img_plantas)
        img.width = 720
        img.height = 420
        ws.add_image(img, "A12")
    if img_buf is not None:
        img_buf.seek(0)
        img = Image(img_buf)
        img.width = 720
        img.height = 480
        ws.add_image(img, "A36")

    color_titulo = "1F4E78"
    color_fila = "EAF2F8"
    borde_fino = Side(style="thin", color="D9E1F2")

    for hoja in wb.worksheets:
        hoja.sheet_view.showGridLines = False
        hoja.freeze_panes = "A2"
        for celda in hoja[1]:
            celda.font = Font(name="Arial", bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor=color_titulo)
            celda.alignment = Alignment(horizontal="center", vertical="center")
        for fila in hoja.iter_rows(min_row=2):
            for celda in fila:
                celda.font = Font(name="Arial", size=10)
                celda.border = Border(bottom=borde_fino)
                if celda.row % 2 == 0:
                    celda.fill = PatternFill("solid", fgColor=color_fila)
        for columna in hoja.columns:
            letra = get_column_letter(columna[0].column)
            ancho = max(
                (len(str(c.value)) for c in columna if c.value is not None),
                default=10
            )
            hoja.column_dimensions[letra].width = min(max(ancho + 2, 12), 38)

    try:
        wb.save(ruta_archivo)
    except PermissionError:
        base, extension = os.path.splitext(nombre_archivo)
        contador = 1
        while True:
            alternativa = os.path.join(
                carpeta_salida, f"{base}_{contador}{extension}"
            )
            if not os.path.exists(alternativa):
                break
            contador += 1
        wb.save(alternativa)
        ruta_archivo = alternativa
        print(f"El archivo original está bloqueado. Se guardó: {ruta_archivo}")

    return ruta_archivo

def crear_figura_comparacion_plantas(dt, dyt, curvas, amplitud_escalon):
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(dt, dyt, label="Respuesta experimental", color="black",
            linewidth=2.6, zorder=5)

    for t_mod, y_mod, nombre, rmse, color in curvas:
        if t_mod is None or y_mod is None:
            continue
        ax.plot(t_mod, np.ravel(y_mod),
                label=etiqueta_con_similitud(nombre, rmse),
                color=color, linewidth=1.8, linestyle="--")

    ax.set_title(
        f"Comparación de modelos frente a la respuesta experimental "
        f"(escalón PWM: {amplitud_escalon:g}%)",
        fontsize=13, fontweight="bold", pad=14
    )
    ax.set_xlabel("Tiempo [s]", fontsize=11)
    ax.set_ylabel("Variación de temperatura ΔT [°C]", fontsize=11)
    ax.minorticks_on()
    ax.grid(True, which="major", linestyle="-", alpha=0.35)
    ax.grid(True, which="minor", linestyle=":", alpha=0.18)
    ax.legend(loc="best", fontsize=9, frameon=True)
    fig.tight_layout()

    img_buf = io.BytesIO()
    fig.savefig(img_buf, format="png", dpi=CONFIG["dpi_graficas"],
                bbox_inches="tight")
    img_buf.seek(0)
    return fig, img_buf

def crear_figura_fopdt(tiempo, temperatura1, pwm, dt, dyt, dxt,
                       tc1, yc1, tc2, yc2, tc3, yc3,
                       amplitud_escalon):
    fig, axs = plt.subplots(
        3, 1, figsize=(12, 11),
        gridspec_kw={"height_ratios": [1, 1, 1.25]}
    )

    # 1. Señales originales
    ax = axs[0]
    ax.plot(tiempo, temperatura1, color="firebrick",
            linewidth=1.8, label="Temperatura")
    ax.set_ylabel("Temperatura [°C]", color="firebrick")
    ax.tick_params(axis="y", labelcolor="firebrick")
    ax.set_title("Señales originales", fontsize=12, fontweight="bold")
    ax_pwm = ax.twinx()
    ax_pwm.step(tiempo, pwm, where="post", color="black",
                linestyle="--", linewidth=1.4, label="PWM")
    ax_pwm.set_ylabel("PWM [%]")
    ax.grid(True, linestyle=":", alpha=0.35)
    l1, n1 = ax.get_legend_handles_labels()
    l2, n2 = ax_pwm.get_legend_handles_labels()
    ax.legend(l1 + l2, n1 + n2, loc="best", fontsize=9)

    # 2. Señal recortada
    ax = axs[1]
    ax.plot(dt, dyt, color="firebrick", linewidth=1.9,
            label="Variación de temperatura")
    ax.set_ylabel("ΔT [°C]", color="firebrick")
    ax.tick_params(axis="y", labelcolor="firebrick")
    ax.set_title(
        f"Respuesta recortada (escalón PWM: {amplitud_escalon:g}%)",
        fontsize=12, fontweight="bold"
    )
    ax_pwm = ax.twinx()
    ax_pwm.step(dt, dxt, where="post", color="black",
                linestyle="--", linewidth=1.4, label="PWM recortado")
    ax_pwm.set_ylabel("PWM [%]")
    ax.grid(True, linestyle=":", alpha=0.35)
    l1, n1 = ax.get_legend_handles_labels()
    l2, n2 = ax_pwm.get_legend_handles_labels()
    ax.legend(l1 + l2, n1 + n2, loc="best", fontsize=9)

    # 3. Respuestas de controladores
    ax = axs[2]
    ax.plot(tc1, yc1, label="Ziegler-Nichols",
            color="darkorange", linewidth=1.8)
    ax.plot(tc2, yc2, label="IAE",
            color="royalblue", linewidth=1.8)
    ax.plot(tc3, yc3, label="Empírico",
            color="seagreen", linewidth=1.8)
    ax.axhline(1.0, color="gray", linestyle=":",
               linewidth=1.3, label="Referencia unitaria")
    ax.set_title(
        "Respuesta de los controladores PID en lazo cerrado",
        fontsize=12, fontweight="bold"
    )
    ax.set_xlabel("Tiempo [s]")
    ax.set_ylabel("Salida normalizada")
    ax.grid(True, linestyle=":", alpha=0.35)
    ax.legend(loc="best", fontsize=9)

    fig.suptitle(
        "ANÁLISIS DE IDENTIFICACIÓN Y CONTROL DE LA PLANTA TÉRMICA",
        fontsize=14, fontweight="bold", y=0.995
    )
    fig.tight_layout(rect=[0, 0, 1, 0.98])

    img_buf = io.BytesIO()
    fig.savefig(img_buf, format="png", dpi=CONFIG["dpi_graficas"],
                bbox_inches="tight")
    img_buf.seek(0)
    return fig, img_buf

def main():
    path_document = seleccionar_archivo_datos(CONFIG["carpeta_datos"])
    if not path_document:
        return
    print(f"\nProcesando archivo: {os.path.basename(path_document)}")
    
    archivo = pd.read_excel(path_document)
    tiempo = np.double(archivo.iloc[:, 0])
    temperatura1 = np.double(archivo.iloc[:, 1])
    pwm = np.double(archivo.iloc[:, 3])
    pwm_trabajo, _ = Counter(pwm).most_common(1)[0]
    
    celdas_fopdt = archivo.iloc[:3, 6].tolist() if archivo.shape[1] > 6 else None
    Kp_Excel, Tau_Excel, Tetha_Excel = leer_fopdt_excel(tiempo, temperatura1, pwm, celdas_fopdt)
    tiene_excel = not (np.isnan(Kp_Excel) or np.isnan(Tau_Excel) or np.isnan(Tetha_Excel))
    if tiene_excel:
        print(f"\nParametros obtenidos de Excel: Kp={Kp_Excel:.4f}, Tau={Tau_Excel:.4f}, Theta={Tetha_Excel:.4f}")

    if tiene_excel:
        Gs_Excel = co.tf([Kp_Excel], [Tau_Excel, 1])
        Gs_timeDeath_Excel = co.tf([-Tetha_Excel/2, 1], [Tetha_Excel/2, 1])
        Gs_Excel_DeathTime = Gs_Excel * Gs_timeDeath_Excel

    dyt, dxt, dt, e = recortar_senal(temperatura1, pwm, tiempo, pwm_trabajo)
    amplitud_escalon = e[0][0]
    
    cap_cal = CONFIG["capacidad_calorifica"]
    alpha = CONFIG["alpha_termico"]
    cof_tra_cal = CONFIG["coeficiente_transferencia"]
    
    p_fopdt = funcion_fopdt_planta(dyt, amplitud_escalon, dt)
    p_fopdt2 = funcion_fopdt2_planta(dyt, amplitud_escalon, dt)
    p_termicos = funcion_modelo_termico(cap_cal, alpha, cof_tra_cal, dyt[-1])

    Gs_timeDeath = co.tf([-p_fopdt[2]/2, 1], [p_fopdt[2]/2, 1])
    Gs_FOPDT = co.tf([p_fopdt[0]], [p_fopdt[1], 1]) * Gs_timeDeath
    Gs_termico = co.tf([p_termicos[0]], [p_termicos[1], 1]) * Gs_timeDeath
    
    Gs_timeDeath2 = co.tf([-p_fopdt2[2]/2, 1], [p_fopdt2[2]/2, 1])
    Gs_FOPDT2 = co.tf([p_fopdt2[0]], [p_fopdt2[1], 1]) * Gs_timeDeath2

    print("\n--- Funciones de transferencia ---")
    print(f"FOPDT metodo 1:       ({p_fopdt[0]:.2f}) / ({p_fopdt[1]:.2f}s+1) * e^(-{p_fopdt[2]:.2f}s)")
    print(f"FOPDT metodo 2:       ({p_fopdt2[0]:.2f}) / ({p_fopdt2[1]:.2f}s+1) * e^(-{p_fopdt2[2]:.2f}s)")
    print(f"Mod. Termico:         ({p_termicos[0]:.2f}) / ({p_termicos[1]:.2f}s+1) * e^(-{p_fopdt[2]:.2f}s)")
    if tiene_excel:
        print(f"FOPDT obtenido Excel: ({Kp_Excel:.2f}) / ({Tau_Excel:.2f}s+1) * e^(-{Tetha_Excel:.2f}s)")

    t_sim = np.linspace(dt[0], dt[-1], len(dt))
    t1, y1 = co.forced_response(Gs_FOPDT, t_sim, amplitud_escalon)
    t2, y2 = co.forced_response(Gs_termico, t_sim, amplitud_escalon)
    _, y_m2 = co.forced_response(Gs_FOPDT2, t_sim, amplitud_escalon)
    t3, y3 = co.forced_response(Gs_Excel_DeathTime, t_sim, amplitud_escalon) if tiene_excel else (None, None)

    rmse_m1 = calcular_rmse_porcentaje(dyt, y1)
    rmse_m2 = calcular_rmse_porcentaje(dyt, y_m2)
    rmse_term = calcular_rmse_porcentaje(dyt, y2)
    rmse_ex = calcular_rmse_porcentaje(dyt, y3) if tiene_excel else np.nan

    print("\n--- RMSE respecto a la senal recortada ---")
    print(f"Metodo 1: {formatear_rmse(rmse_m1)}")
    print(f"metodo 2: {formatear_rmse(rmse_m2)}")
    print(f"Termico:  {formatear_rmse(rmse_term)}")
    if tiene_excel:
        print(f"excel:    {formatear_rmse(rmse_ex)}")
    
    print("\n--- Metodo Tau ---")
    modelos_tau = [("Termico", p_termicos[1]), ("FOPDT", p_fopdt[1]), ("FOPDT2", p_fopdt2[1])]
    if tiene_excel:
        modelos_tau.insert(0, ("Excel", Tau_Excel))
    for nombre, tau in modelos_tau:
        print(f"{nombre}: {tau*0.05:.2f} < T < {tau*0.15:.2f}")

    print("\n--- Metodo Theta ---")
    modelos_theta = [("Termico", p_fopdt[2]), ("FOPDT", p_fopdt[2]), ("FOPDT2", p_fopdt2[2])]
    if tiene_excel:
        modelos_theta.insert(0, ("Excel", Tetha_Excel))
    for nombre, tetha in modelos_theta:
        print(f"{nombre}: {tetha*0.2:.2f} < T < {tetha*0.6:.2f}")

    muestreo = int(input("\nIngrese el tiempo de muestreo [s]: "))
    tipoControl = CONFIG["tipo_control"]
    
    ctrl_zn_FOPDT, ctrl_iae_FOPDT = system_control(p_fopdt[0], p_fopdt[1], p_fopdt[2], muestreo, tipoControl)
    ctrl_emp = CONFIG["pid_empirico"]
    Gs_ctrl_zn = co.tf([ctrl_zn_FOPDT[2], ctrl_zn_FOPDT[0], ctrl_zn_FOPDT[1]], [1, 0])
    Gs_ctrl_iae = co.tf([ctrl_iae_FOPDT[2], ctrl_iae_FOPDT[0], ctrl_iae_FOPDT[1]], [1, 0])
    Gs_ctrl_emp = co.tf([ctrl_emp[2], ctrl_emp[0], ctrl_emp[1]], [1, 0])

    Gs_fb_zn = co.feedback(Gs_FOPDT * Gs_ctrl_zn, 1, sign=-1)
    Gs_fb_iae = co.feedback(Gs_FOPDT * Gs_ctrl_iae, 1, sign=-1)
    Gs_fb_emp = co.feedback(Gs_FOPDT * Gs_ctrl_emp, 1, sign=-1)

    tc1, yc1 = co.step_response(Gs_fb_zn, t_sim)
    tc2, yc2 = co.step_response(Gs_fb_iae, t_sim)
    tc3, yc3 = co.step_response(Gs_fb_emp, t_sim)

    print(f"\n--- Parametros PID (FOPDT) [T={muestreo}s] ---")
    print(f"Empirico: KP= {ctrl_emp[0]:.4f}, KI= {ctrl_emp[1]:.4f}, KD= {ctrl_emp[2]:.4f}")
    print(f"ZN:       KP= {ctrl_zn_FOPDT[0]:.4f}, KI= {ctrl_zn_FOPDT[1]:.4f}, KD= {ctrl_zn_FOPDT[2]:.4f}")
    print(f"IAE:      KP= {ctrl_iae_FOPDT[0]:.4f}, KI= {ctrl_iae_FOPDT[1]:.4f}, KD= {ctrl_iae_FOPDT[2]:.4f}")

    print("\nGenerando graficas...")
    curvas_plantas = [
        (t1, y1, "Metodo 1", rmse_m1, "orange"),
        (t_sim, y_m2, "metodo 2", rmse_m2, "purple"),
        (t2, y2, "Termico", rmse_term, "blue"),
        (t3, y3, "excel", rmse_ex, "darkgreen"),
    ]
    fig_plantas, img_plantas = crear_figura_comparacion_plantas(dt, dyt, curvas_plantas, amplitud_escalon)
    fig, img_buf = crear_figura_fopdt(tiempo, temperatura1, pwm, dt, dyt, dxt,
                                      tc1, yc1, tc2, yc2, tc3, yc3,
                                      amplitud_escalon)

    temp_ini = temperatura1[0]
    temp_fin = temp_ini + dyt[-1]
    
    # Se pasa explícitamente carpeta_salida usando la configuración global
    ruta_excel = exportar_analisis_excel(
        amplitud_escalon,
        dyt, dxt, dt,
        temp_ini, temp_fin,
        p_fopdt, p_fopdt2, p_termicos,
        Kp_Excel, Tau_Excel, Tetha_Excel,
        rmse_m1, rmse_m2, rmse_term, rmse_ex,
        muestreo, ctrl_zn_FOPDT, ctrl_iae_FOPDT, ctrl_emp,
        img_buf=img_buf, img_plantas=img_plantas,
        archivo_analizar=os.path.basename(path_document),
        carpeta_salida=CONFIG["carpeta_salida"]
    )
    print(f"Reporte Excel generado en: {ruta_excel}")

    print("Mostrando graficas interactivas...")
    plt.show()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        print("\n" + "=" * 78)
        print("EL ANÁLISIS SE INTERRUMPIÓ POR UN ERROR".center(78))
        print("=" * 78)
        traceback.print_exc()
    finally:
        input("\nPresione ENTER para cerrar...")