import os
import sys
import glob
import io
import math
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
import pandas as pd
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# Compatibilidad para integración trapezoidal según versión de NumPy
_trapz = getattr(np, "trapezoid", None) or np.trapz

# CONFIGURACIÓN GLOBAL Y PARÁMETROS AJUSTABLES

CFG = {
    # Malla temporal uniforme
    "dt": 1.0,                 # [s] Paso de remuestreo uniforme
    "min_hold_sp": 10.0,       # [s] Duración mínima de SP para descartar glitches
    "ventana_suav": 9,         # [s] Ventana de media móvil para detección de eventos
    
    # Detección y validación de perturbaciones
    "frac_alcanzado": 0.80,    # Fracción del escalón requerida antes de buscar perturbaciones
    "umbral_min": 1.0,         # [°C] Desviación mínima absoluta para declarar perturbación
    "umbral_rel": 0.10,        # [%/100] Fracción de ΔSP para umbral relativo
    "ventana_evento": 120.0,   # [s] Ventana máxima para evaluar la pendiente de la perturbación
    "t_estable": 30.0,         # [s] Duración de meseta exigida para confirmar estabilidad
    "t_plano_inicio": 12.0,    # [s] Detección de inicio plano de perturbación
    "t_asentado": 60.0,        # [s] Ventana para verificar asentamiento del escalón
    "banda_estable": 0.6,      # [°C] Rango (max - min) para considerar una señal como asentada
    "retiro_es_evento": False, # Tratar el retiro de perturbación como evento separado o recuperación
    
    # Ventanas de promedio para estado estacionario
    "t_pre": 15.0,             # [s] Ventana para promediar valor previo al evento
    "t_ss": 10.0,              # [s] Ventana para promediar valor en régimen permanente
    "t_min_dentro": 10.0,      # [s] Tiempo mínimo de permanencia dentro de banda para validar ts
    
    # Rutas por defecto y visualización
    "carpeta_datos": "dataControl",
    "carpeta_salida": os.path.join("AnalisisDatos", "Control"),
    "dpi_grafica": 100,        # Resolución de gráficas para incrustación ligera en Excel
}

# Paleta de colores estándar para fases dinámicas
COLOR_FASE = {
    "ESCALON": "#2ca02c",      # Verde: Respuesta al escalón
    "BAJA": "#1f77b4",         # Azul: Perturbación por enfriamiento forzado
    "SUBE": "#d62728",         # Rojo: Perturbación por calor externo
    "INDEFINIDO": "#7f7f7f"    # Gris: No clasificado
}

TXT_TIPO_PERT = {
    "BAJA": "BAJA (enfriamiento)",
    "SUBE": "SUBE (calentamiento)"
}

# 1. PREPROCESAMIENTO Y LIMPIEZA DE DATOS

def seleccionar_archivo_datos(carpeta_datos: str = "dataControl") -> Optional[str]:
    os.system('cls' if os.name == 'nt' else 'clear')
    if not os.path.isdir(carpeta_datos):
        print(f"Error: La carpeta '{carpeta_datos}' no existe.")
        return None

    archivos = sorted(glob.glob(os.path.join(carpeta_datos, "*.xlsx")))
    archivos = [a for a in archivos if not os.path.basename(a).startswith("~$")]

    if not archivos:
        print(f"No se encontraron archivos Excel válidos en '{carpeta_datos}'.")
        return None

    print(f"\nArchivos disponibles en '{carpeta_datos}':")
    for i, arch in enumerate(archivos):
        print(f"  [{i}] {os.path.basename(arch)}")

    if len(archivos) == 1:
        print(f"\nSeleccionando único archivo disponible: {os.path.basename(archivos[0])}")
        return archivos[0]

    while True:
        try:
            sel = input(f"\nSeleccione el número del archivo (0-{len(archivos) - 1}): ").strip()
            sel_idx = int(sel)
            if 0 <= sel_idx < len(archivos):
                return archivos[sel_idx]
            print(f"Selección fuera de rango. Ingrese un valor entre 0 y {len(archivos) - 1}.")
        except ValueError:
            print("Entrada inválida. Debe ingresar un número entero.")


def preparar_datos(df: pd.DataFrame, dt: float = 1.0) -> pd.DataFrame:
    d = df.copy()
    if "Tiempo" not in d.columns:
        raise ValueError("El archivo Excel no contiene la columna obligatoria 'Tiempo'.")

    d["Tiempo"] = pd.to_numeric(d["Tiempo"], errors="coerce")
    d = d.dropna(subset=["Tiempo"]).sort_values("Tiempo", kind="stable")

    cols_validas = [
        c for c in d.columns 
        if str(c).startswith(("Temperatura", "Corriente", "PWM", "SetPoint"))
    ]

    for c in cols_validas:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    # Promediar marcas de tiempo idénticas si existen
    g = d.groupby("Tiempo")[cols_validas].mean()

    t_min = float(g.index.min())
    t_max = float(g.index.max())
    malla = np.arange(t_min, t_max + dt / 2.0, dt)
    out = pd.DataFrame({"Tiempo": malla})

    for c in cols_validas:
        s = g[c].dropna()
        if s.empty:
            out[c] = np.nan
        elif str(c).startswith(("PWM", "SetPoint")):
            # Retenedor de orden cero para señales discretas/escalonadas
            out[c] = s.reindex(s.index.union(malla)).ffill().bfill().reindex(malla).values
        else:
            # Interpolación lineal para mediciones analógicas continuas
            out[c] = np.interp(malla, s.index.values, s.values)

    return out


def media_movil(x: np.ndarray, w: int) -> np.ndarray:
    w = max(1, int(w))
    if w <= 1 or len(x) < w:
        return x.copy()
    pi = w // 2
    xp = np.pad(x, (pi, w - 1 - pi), mode="edge")
    return np.convolve(xp, np.ones(w) / w, mode="valid")

# 2. DETECCIÓN DEL ESCALÓN DE SETPOINT Y GESTIÓN DE EVENTOS

def detectar_escalon_sp(t: np.ndarray, sp: np.ndarray, cfg: Dict[str, Any] = CFG) -> Tuple[int, float, int, List[str]]:

    dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
    n = len(sp)
    avisos: List[str] = []

    diff_sp = np.abs(np.diff(sp))
    cambios = np.where(diff_sp > 1e-6)[0]

    if len(cambios) == 0:
        avisos.append("El SetPoint se mantiene constante en todo el registro. Se toma t=0 como inicio.")
        return 0, float(sp[0]), n, avisos

    ini = np.r_[0, cambios + 1]
    fin = np.r_[ini[1:], n]

    segs = [
        {
            "i0": int(a),
            "i1": int(b),
            "valor": float(sp[a]),
            "duracion": float((b - a) * dt),
            "valido": float((b - a) * dt) >= cfg["min_hold_sp"] or b == n
        }
        for a, b in zip(ini, fin)
    ]

    # Identificar el primer segmento válido tras un cambio
    validos = [s for s in segs[1:] if s["valido"]]
    if not validos:
        # Si ninguno supera min_hold_sp, se toma el mayor
        validos = sorted(segs[1:], key=lambda s: s["duracion"], reverse=True)

    idx_step = validos[0]["i0"]
    sp_obj = validos[0]["valor"]
    idx_end = validos[1]["i0"] if len(validos) > 1 else n

    if len(validos) > 1:
        avisos.append(
            f"Se detectaron múltiples cambios de SP válidos. Se evalúa el primer escalón "
            f"hasta t = {t[idx_end - 1]:.1f} s."
        )

    for s in segs[1:]:
        if not s["valido"]:
            avisos.append(
                f"Glitche de SP ignorado: valor {s['valor']:.1f} durante {s['duracion']:.1f} s "
                f"en t={t[s['i0']]:.1f} s."
            )

    return idx_step, sp_obj, idx_end, avisos


def _inicio_movimiento(ys: np.ndarray, i: int, tipo: str, limite: int, n_flat: int) -> int:

    sentido = 1.0 if tipo == "SUBE" else -1.0
    j, planos = i, 0
    while j > limite:
        if sentido * (ys[j] - ys[j - 1]) > 1e-6:
            planos = 0
        else:
            planos += 1
            if planos >= n_flat:
                break
        j -= 1
    return min(i, j + planos)


def _plano(w: np.ndarray, banda: float) -> bool:
    if len(w) < 4:
        return False
    h = len(w) // 2
    rango_ok = np.ptp(w) <= banda
    deriva_ok = abs(np.mean(w[h:]) - np.mean(w[:h])) <= 0.5 * banda
    return bool(rango_ok and deriva_ok)


def _asentada(ys: np.ndarray, i: int, n_est: int, banda: float) -> bool:
    if i - n_est < 0:
        return False
    return _plano(ys[i - n_est:i + 1], banda)


def detectar_perturbaciones(
    t: np.ndarray,
    pv: np.ndarray,
    idx_step: int,
    idx_end: int,
    y_ini: float,
    sp: float,
    cfg: Dict[str, Any] = CFG
) -> Tuple[List[Dict[str, Any]], np.ndarray, float]:

    dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
    ys = media_movil(pv, int(cfg["ventana_suav"] / dt))
    delta = sp - y_ini

    umbral = max(float(cfg["umbral_min"]), float(cfg["umbral_rel"]) * abs(delta))
    if abs(delta) < 1e-9:
        return [], ys, umbral

    sgn = 1.0 if delta >= 0 else -1.0
    prog = sgn * (ys - y_ini) / abs(delta)

    # Solo buscar perturbaciones tras haber alcanzado la fracción mínima del escalón
    cand = np.where(prog[idx_step:idx_end] >= cfg["frac_alcanzado"])[0]
    if cand.size == 0:
        return [], ys, umbral

    i_a = idx_step + int(cand[0])
    W = max(5, int(cfg["ventana_evento"] / dt))
    n_est = max(3, int(cfg["t_estable"] / dt))
    n_pre = max(1, int(cfg["t_pre"] / dt))
    tol_os = max(0.5, 0.02 * abs(delta))
    n_flat = max(2, int(cfg["t_plano_inicio"] / dt))

    eventos: List[Dict[str, Any]] = []
    i_busq = i_a
    i = i_a + 1

    while i < idx_end:
        j0 = max(i_busq, i - W)
        v = ys[j0:i + 1]
        caida = np.max(v) - ys[i]
        subida = ys[i] - np.min(v)

        if caida >= umbral and caida >= subida:
            tipo = "BAJA"
        elif subida >= umbral:
            tipo = "SUBE"
        else:
            i += 1
            continue

        i_on = _inicio_movimiento(ys, i, tipo, i_busq, n_flat)

        # Confirmar que la desviación desde el punto de inicio real supere el umbral
        if abs(ys[i] - ys[i_on]) < umbral:
            i += 1
            continue

        # Búsqueda del extremo de la perturbación (nadir para BAJA, cresta para SUBE)
        y_ext, i_ext, k = ys[i], i, i
        rev = 0.5 * umbral
        while k < idx_end:
            nuevo = (ys[k] < y_ext - 1e-6) if tipo == "BAJA" else (ys[k] > y_ext + 1e-6)
            if nuevo:
                y_ext, i_ext = ys[k], k
            elif abs(ys[k] - y_ext) >= rev and ((ys[k] > y_ext) == (tipo == "BAJA")):
                break
            elif (k - i_ext) >= n_est:
                break
            k += 1

        y_pre = float(np.mean(pv[max(0, i_on - n_pre):i_on + 1]))

        # Criterio de validación: eventos en el mismo sentido del escalón o provenientes
        # de un sobreimpulso solo se aceptan si la señal ya estaba previamente asentada
        a_favor = (tipo == "SUBE" and sgn > 0) or (tipo == "BAJA" and sgn < 0)
        lado_sobreimp = (sgn > 0 and y_pre > sp + tol_os) or (sgn < 0 and y_pre < sp - tol_os)

        if a_favor or lado_sobreimp:
            valido = _asentada(ys, i_on, n_est, cfg["banda_estable"])
        else:
            valido = True

        # Evitar registrar el simple retorno al punto de operación como nueva perturbación
        if valido and eventos and not cfg["retiro_es_evento"]:
            prev = eventos[-1]
            tol_rec = max(0.5 * umbral, 0.25 * abs(prev["y_pre"] - prev["y_ext"]))
            if tipo != prev["tipo"] and abs(y_ext - prev["y_pre"]) <= tol_rec:
                valido = False

        if not valido:
            i += 1
            continue

        eventos.append({
            "tipo": tipo,
            "i_ini": int(i_on),
            "i_ext": int(i_ext),
            "y_pre": y_pre,
            "y_ext": float(y_ext)
        })

        i_busq = int(i_ext)
        i = int(i_ext) + 1

    return eventos, ys, umbral

# 3. MÉTODOS DE CÁLCULO DEL SOBREIMPULSO Y CLASIFICACIÓN DINÁMICA

def calcular_sobreimpulso(
    y: np.ndarray,
    sp: float,
    y_ini: float,
    tt: np.ndarray
) -> Dict[str, Any]:

    delta_sp = float(sp - y_ini)
    sgn = 1.0 if delta_sp >= 0 else -1.0

    if sgn > 0:
        idx_pico = int(np.argmax(y))
        y_pico = float(y[idx_pico])
        os_abs = max(0.0, y_pico - sp)
    else:
        idx_pico = int(np.argmin(y))
        y_pico = float(y[idx_pico])
        os_abs = max(0.0, sp - y_pico)

    t_peak = float(tt[idx_pico])

    # Método 1: Normalizado a ΔSP
    if abs(delta_sp) > 1e-9:
        os_pct_delta = (os_abs / abs(delta_sp)) * 100.0
    else:
        os_pct_delta = 0.0

    # Método 2: Referenciado a SP
    if abs(sp) > 1e-9:
        os_pct_sp = (os_abs / abs(sp)) * 100.0
    else:
        os_pct_sp = 0.0

    # Razón de escala entre ambos métodos (SP / ΔSP)
    razon_metodos = (abs(sp) / abs(delta_sp)) if abs(delta_sp) > 1e-9 else np.nan

    return {
        "y_pico": y_pico,
        "t_peak": t_peak,
        "sobreimpulso_abs": os_abs,
        "os_pct_delta": os_pct_delta,
        "os_pct_sp": os_pct_sp,
        "delta_sp": delta_sp,
        "razon_metodos": razon_metodos
    }


def clasificar_comportamiento_sobreimpulso(
    os_pct_delta: float,
    os_abs: float,
    delta_sp: float
) -> Dict[str, Any]:

    # Tolerancia al ruido del sensor de temperatura (±0.1 °C)
    if os_pct_delta <= 0.5 or os_abs < 0.1:
        categoria = "Sobreamortiguado (Sin sobreimpulso)"
        codigo = "OVERDAMPED"
        descripcion = "Respuesta aperiódica suave sin oscilación por encima del SetPoint (ζ ≥ 1.0)."
        zeta_est = 1.0
    elif os_pct_delta <= 5.0:
        categoria = "Subamortiguado Cuasi-crítico / Óptimo"
        codigo = "OPTIMAL_DAMPED"
        descripcion = "Sobreimpulso mínimo contenido dentro de la banda de tolerancia del 5% (ζ ≈ 0.7 - 0.9)."
        zeta_est = float(-np.log(os_pct_delta / 100.0) / np.sqrt(np.pi**2 + np.log(os_pct_delta / 100.0)**2))
    elif os_pct_delta <= 15.0:
        categoria = "Subamortiguado Moderado"
        codigo = "MODERATE_UNDERDAMPED"
        descripcion = "Transitorio rápido con sobreimpulso controlado y decaimiento ágil (ζ ≈ 0.5 - 0.7)."
        zeta_est = float(-np.log(os_pct_delta / 100.0) / np.sqrt(np.pi**2 + np.log(os_pct_delta / 100.0)**2))
    elif os_pct_delta <= 30.0:
        categoria = "Subamortiguado Pronunciado"
        codigo = "PRONOUNCED_UNDERDAMPED"
        descripcion = "Oscilación apreciable similar a sintonización clásica Ziegler-Nichols (ζ ≈ 0.35 - 0.5)."
        zeta_est = float(-np.log(os_pct_delta / 100.0) / np.sqrt(np.pi**2 + np.log(os_pct_delta / 100.0)**2))
    else:
        categoria = "Altamente Oscilatorio / Crítico"
        codigo = "HIGHLY_OSCILLATORY"
        descripcion = "Sobreimpulso severo (>30%). Margen de estabilidad reducido y alto esfuerzo dinámico (ζ < 0.35)."
        zeta_est = float(-np.log(os_pct_delta / 100.0) / np.sqrt(np.pi**2 + np.log(os_pct_delta / 100.0)**2)) if os_pct_delta < 100 else 0.05

    return {
        "categoria": categoria,
        "codigo": codigo,
        "descripcion": descripcion,
        "zeta_estimado": zeta_est
    }


def separar_y_clasificar_senales(resultados_plantas: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grupos: Dict[str, List[Dict[str, Any]]] = {
        "Sobreamortiguado (Sin sobreimpulso)": [],
        "Subamortiguado Cuasi-crítico / Óptimo": [],
        "Subamortiguado Moderado": [],
        "Subamortiguado Pronunciado": [],
        "Altamente Oscilatorio / Crítico": []
    }

    for res in resultados_plantas:
        cat = res["escalon"]["clasificacion"]["categoria"]
        if cat in grupos:
            grupos[cat].append(res)
        else:
            grupos.setdefault(cat, []).append(res)

    return grupos

# 4. CÁLCULO DE MÉTRICAS DETALLADAS (ESCALÓN Y PERTURBACIONES)

def metricas_escalon(
    t: np.ndarray,
    pv: np.ndarray,
    pwm: np.ndarray,
    corr: Optional[np.ndarray],
    sp: float,
    idx_step: int,
    i_fin: int,
    y_ini: float,
    termino_por_pert: bool,
    cfg: Dict[str, Any] = CFG
) -> Dict[str, Any]:

    dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
    tt = t[idx_step:i_fin] - t[idx_step]
    y = pv[idx_step:i_fin]
    u = pwm[idx_step:i_fin]
    delta_sp = float(sp - y_ini)

    n_ss = max(1, int(cfg["t_ss"] / dt))
    n_est = max(1, int(cfg["t_asentado"] / dt))

    # Valor final alcanzado en esta fase
    y_ss = float(np.mean(y[-n_ss:]))
    error_ss = float(sp - y_ss)
    asentado = bool(len(y) >= n_est and _plano(y[-n_est:], cfg["banda_estable"]))

    # Cálculo y comparación de sobreimpulso mediante ambos métodos
    res_os = calcular_sobreimpulso(y, sp, y_ini, tt)
    clasif = clasificar_comportamiento_sobreimpulso(
        res_os["os_pct_delta"], res_os["sobreimpulso_abs"], delta_sp
    )

    # Amplitudes máxima y mínima observadas
    y_max = float(np.max(y))
    y_min = float(np.min(y))

    # Referencia para cálculo de tiempos (SP o valor asentado)
    ref = y_ss if (asentado or termino_por_pert) else sp
    d_ref = ref - y_ini

    # Tiempos de subida (tr: 10% a 90%)
    t_rise = np.nan
    t_s2 = np.nan
    t_s5 = np.nan

    if abs(d_ref) > 1e-9:
        prog = (y - y_ini) / d_ref
        i10 = np.where(prog >= 0.10)[0]
        i90 = np.where(prog >= 0.90)[0]
        if i10.size > 0 and i90.size > 0 and i90[0] >= i10[0]:
            t_rise = float(tt[i90[0]] - tt[i10[0]])

        # Tiempos de establecimiento (ts al 2% y 5%) con requisito de permanencia
        def calc_ts(tolerancia: float) -> float:
            fuera = np.where(np.abs(y - ref) > tolerancia * abs(d_ref))[0]
            if fuera.size == 0:
                return 0.0
            k = fuera[-1] + 1
            if k >= len(tt) or (tt[-1] - tt[k]) < cfg["t_min_dentro"]:
                return np.nan
            return float(tt[k])

        t_s2 = calc_ts(0.02)
        t_s5 = calc_ts(0.05)

    # Índices integrales de error (IAE, ISE, ITAE)
    e = sp - y
    iae = float(_trapz(np.abs(e), tt))
    ise = float(_trapz(e ** 2, tt))
    itae = float(_trapz(tt * np.abs(e), tt))

    # Esfuerzo de control (PWM) y variación total TV(u)
    pwm_max = float(np.max(u))
    pwm_min = float(np.min(u))
    pwm_ss = float(np.mean(u[-n_ss:]))
    tv_u = float(np.sum(np.abs(np.diff(u))))

    # Consumo de corriente eléctrica (mA)
    i_max = np.nan
    i_ss = np.nan
    if corr is not None and not np.all(np.isnan(corr)):
        c = corr[idx_step:i_fin]
        i_max = float(np.nanmax(c))
        i_ss = float(np.nanmean(c[-n_ss:]))

    return {
        "t_step": float(t[idx_step]),
        "t_fin": float(t[i_fin - 1]),
        "duracion": float(tt[-1]),
        "y_inicial": float(y_ini),
        "sp_final": float(sp),
        "delta_sp": delta_sp,
        "y_max": y_max,
        "y_min": y_min,
        "y_pico": res_os["y_pico"],
        "t_peak": res_os["t_peak"],
        "sobreimpulso_abs": res_os["sobreimpulso_abs"],
        "os_pct_delta": res_os["os_pct_delta"],
        "os_pct_sp": res_os["os_pct_sp"],
        "razon_metodos": res_os["razon_metodos"],
        "clasificacion": clasif,
        "t_rise": t_rise,
        "t_settling_2": t_s2,
        "t_settling_5": t_s5,
        "y_ss": y_ss,
        "error_ss": error_ss,
        "asentado": asentado,
        "termino_por": "perturbacion" if termino_por_pert else "fin de registro",
        "iae": iae,
        "ise": ise,
        "itae": itae,
        "pwm_max": pwm_max,
        "pwm_min": pwm_min,
        "pwm_ss": pwm_ss,
        "tv_u": tv_u,
        "i_max": i_max,
        "i_ss": i_ss,
    }


def metricas_perturbacion(
    t: np.ndarray,
    pv: np.ndarray,
    pwm: np.ndarray,
    ev: Dict[str, Any],
    i0: int,
    i1: int,
    sp: float,
    cfg: Dict[str, Any] = CFG
) -> Dict[str, Any]:

    dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
    tt = t[i0:i1]
    y = pv[i0:i1]
    u = pwm[i0:i1]
    n_ss = max(1, int(cfg["t_ss"] / dt))
    n_pre = max(1, int(cfg["t_pre"] / dt))
    tipo = ev["tipo"]

    y_pre = float(ev["y_pre"])
    pwm_pre = float(np.mean(pwm[max(0, i0 - n_pre):i0 + 1]))

    k_ext = int(np.argmin(y) if tipo == "BAJA" else np.argmax(y))
    y_ext = float(y[k_ext])
    t_ext = float(tt[k_ext])
    desviacion = float(y_ext - y_pre)

    # Reacción del controlador en PWM
    k_u = int(np.argmax(u) if tipo == "BAJA" else np.argmin(u))
    pwm_pico = float(u[k_u])
    t_pwm_pico = float(tt[k_u] - tt[0])
    delta_pwm = float(pwm_pico - pwm_pre)

    # Régimen alcanzado al final de la perturbación
    y_fin = float(np.mean(y[-n_ss:]))
    den_rec = float(y_pre - y_ext)
    rec_pct = ((y_fin - y_ext) / den_rec * 100.0) if abs(den_rec) > 1e-6 else np.nan

    # Tiempos de recuperación porcentuales (50% y 90%)
    def t_rec_frac(frac: float) -> float:
        if abs(den_rec) < 1e-6:
            return np.nan
        prog = (y - y_ext) / den_rec
        idx = np.where((np.arange(len(y)) > k_ext) & (prog >= frac))[0]
        return float(tt[idx[0]] - tt[k_ext]) if idx.size > 0 else np.nan

    # Tiempo de recuperación a banda de tolerancia fija (±0.5 °C del SP)
    banda_recov = sp - 0.5 if tipo == "BAJA" else sp + 0.5
    idx_recov_sp = np.where(
        (np.arange(len(y)) > k_ext) & (y >= banda_recov if tipo == "BAJA" else y <= banda_recov)
    )[0]
    t_recup_sp = float(tt[idx_recov_sp[0]] - tt[0]) if idx_recov_sp.size > 0 else np.nan

    d = y - y_pre
    iae_pert = float(_trapz(np.abs(d), tt - tt[0]))
    ise_pert = float(_trapz(d ** 2, tt - tt[0]))

    return {
        "tipo": tipo,
        "t_inicio": float(tt[0]),
        "t_fin": float(tt[-1]),
        "duracion": float(tt[-1] - tt[0]),
        "y_pre": y_pre,
        "y_ext": y_ext,
        "t_ext": t_ext,
        "desviacion": desviacion,
        "t_al_extremo": float(t_ext - tt[0]),
        "pwm_pre": pwm_pre,
        "pwm_pico": pwm_pico,
        "delta_pwm": delta_pwm,
        "t_pwm_pico": t_pwm_pico,
        "y_fin": y_fin,
        "recuperacion_pct": rec_pct,
        "t_rec50": t_rec_frac(0.5),
        "t_rec90": t_rec_frac(0.9),
        "tiempo_recuperacion_sp": t_recup_sp,
        "iae_pert": iae_pert,
        "ise_pert": ise_pert,
    }


def analizar_planta(
    t: np.ndarray,
    pv: np.ndarray,
    sp: np.ndarray,
    pwm: np.ndarray,
    corr: Optional[np.ndarray] = None,
    nombre: str = "Planta",
    cfg: Dict[str, Any] = CFG
) -> Dict[str, Any]:

    idx_step, sp_obj, idx_end, avisos = detectar_escalon_sp(t, sp, cfg)
    y_ini = float(np.mean(pv[max(0, idx_step - 5):idx_step])) if idx_step > 0 else float(pv[0])

    eventos, ys, umbral = detectar_perturbaciones(t, pv, idx_step, idx_end, y_ini, sp_obj, cfg)

    # La fase de escalón termina donde inicia la primera perturbación (o al fin de registro)
    i_fin_esc = eventos[0]["i_ini"] if eventos else idx_end
    esc = metricas_escalon(t, pv, pwm, corr, sp_obj, idx_step, i_fin_esc, y_ini, bool(eventos), cfg)

    perts: List[Dict[str, Any]] = []
    fases = [{"nombre": "Escalón", "tipo": "ESCALON", "i0": idx_step, "i1": i_fin_esc}]

    for k, ev in enumerate(eventos):
        i0 = ev["i_ini"]
        i1 = eventos[k + 1]["i_ini"] if k + 1 < len(eventos) else idx_end
        m_pert = metricas_perturbacion(t, pv, pwm, ev, i0, i1, sp_obj, cfg)
        m_pert["n"] = k + 1
        m_pert["i_ext_abs"] = ev["i_ext"]
        perts.append(m_pert)
        fases.append({
            "nombre": f"Perturbación #{k + 1} ({ev['tipo']})",
            "tipo": ev["tipo"],
            "i0": i0,
            "i1": i1
        })

    # Etiquetado temporal para análisis de series de tiempo
    etiqueta = np.full(len(t), "Pre-escalón", dtype=object)
    for f in fases:
        etiqueta[f["i0"]:f["i1"]] = f["nombre"]
    if idx_end < len(t):
        etiqueta[idx_end:] = "Fuera de análisis"

    if not eventos and not esc["asentado"]:
        avisos.append("No se detectaron perturbaciones y la respuesta aún no se asentó al final del registro.")

    return {
        "planta": nombre,
        "idx_step": idx_step,
        "sp_obj": sp_obj,
        "y_ini": y_ini,
        "umbral_deteccion": umbral,
        "escalon": esc,
        "perturbaciones": perts,
        "fases": fases,
        "etiqueta": etiqueta,
        "avisos": avisos
    }

# 5. SALIDA POR CONSOLA Y REPORTES EN TEXTO

def format_val(val: Any, fmt: str = ".2f", default: str = "-") -> str:

    if val is None:
        return default
    try:
        if isinstance(val, (float, np.floating)):
            if np.isnan(val) or np.isinf(val):
                return default
            return f"{val:{fmt}}"
        if isinstance(val, (int, np.integer)):
            return str(val)
        return str(val)
    except (ValueError, TypeError):
        return str(val)


def imprimir_resumen_control(resultados: List[Dict[str, Any]], df_params: Optional[pd.DataFrame] = None) -> None:

    nombres = [r["planta"] for r in resultados]
    tiene_dos = len(resultados) > 1

    print("\n" + "=" * 78)
    print("           REPORTE INTEGRAL DE ANÁLISIS DE CONTROL EN LAZO CERRADO")
    print("=" * 78)

    if df_params is not None and not df_params.empty:
        print("\n[1] PARÁMETROS PID CONFIGURADOS:")
        print(df_params.to_string(index=False))

    print("\n[2] FASE DE RESPONSIVA AL ESCALÓN (Métricas de Desempeño Transitorio):")
    hdr = f"{'Métrica':<36}" + "".join(f" | {n:<16}" for n in nombres)
    sep = "-" * len(hdr)
    print(hdr)
    print(sep)

    filas_resumen = [
        ("SetPoint Objetivo [°C]", lambda e: format_val(e["sp_final"])),
        ("Temperatura Inicial y0 [°C]", lambda e: format_val(e["y_inicial"])),
        ("Magnitud del Escalón ΔSP [°C]", lambda e: format_val(e["delta_sp"])),
        ("Temp. Máxima Alcanzada [°C]", lambda e: format_val(e["y_max"])),
        ("Temp. Mínima Alcanzada [°C]", lambda e: format_val(e["y_min"])),
        ("Tiempo de Pico tp [s]", lambda e: format_val(e["t_peak"], ".1f")),
        ("Sobreimpulso Absoluto OS [°C]", lambda e: format_val(e["sobreimpulso_abs"])),
        ("  -> MÉTODO 1: OS (% de ΔSP)", lambda e: format_val(e["os_pct_delta"]) + " %"),
        ("  -> MÉTODO 2: OS (% de SP)", lambda e: format_val(e["os_pct_sp"]) + " %"),
        ("Razón Método 1 / Método 2", lambda e: format_val(e["razon_metodos"], ".2f") + "x"),
        ("Comportamiento Transitorio", lambda e: e["clasificacion"]["codigo"]),
        ("Factor Amortiguamiento Est. (ζ)", lambda e: format_val(e["clasificacion"]["zeta_estimado"], ".3f")),
        ("Tiempo de Subida tr (10-90%) [s]", lambda e: format_val(e["t_rise"], ".1f")),
        ("Tiempo de Establ. ts (5%) [s]", lambda e: format_val(e["t_settling_5"], ".1f")),
        ("Tiempo de Establ. ts (2%) [s]", lambda e: format_val(e["t_settling_2"], ".1f")),
        ("Temp. Régimen Estable Yss [°C]", lambda e: format_val(e["y_ss"])),
        ("Error de Régimen ess [°C]", lambda e: format_val(e["error_ss"])),
        ("Respuesta Asentada", lambda e: "Sí" if e["asentado"] else "No"),
        ("Causa de Fin de Fase", lambda e: e["termino_por"]),
        ("Índice IAE", lambda e: format_val(e["iae"], ".1f")),
        ("Índice ISE", lambda e: format_val(e["ise"], ".1f")),
        ("Índice ITAE", lambda e: format_val(e["itae"], ".1f")),
        ("PWM Máximo [%]", lambda e: format_val(e["pwm_max"], ".1f")),
        ("PWM Estable [%]", lambda e: format_val(e["pwm_ss"], ".1f")),
        ("Variación Total TV(u)", lambda e: format_val(e["tv_u"], ".1f")),
        ("Corriente Máx [mA]", lambda e: format_val(e["i_max"], ".1f")),
        ("Corriente Estable [mA]", lambda e: format_val(e["i_ss"], ".1f")),
    ]

    for label, getter in filas_resumen:
        linea = f"{label:<36}" + "".join(f" | {getter(r['escalon']):<16}" for r in resultados)
        print(linea)
    print(sep)

    # Detalle de clasificación
    print("\n[3] EVALUACIÓN Y CLASIFICACIÓN DE AMORTIGUAMIENTO:")
    for r in resultados:
        e = r["escalon"]
        c = e["clasificacion"]
        print(f"  * {r['planta']}: {c['categoria']}")
        print(f"      - {c['descripcion']}")
        print(f"      - Comparación: OS(ΔSP) = {e['os_pct_delta']:.2f}% vs OS(SP) = {e['os_pct_sp']:.2f}%.")

    # Detalle de perturbaciones externas
    print("\n[4] RECHAZO A PERTURBACIONES EXTERNAS:")
    hay_perts = any(len(r["perturbaciones"]) > 0 for r in resultados)
    if not hay_perts:
        print("  No se detectaron perturbaciones térmicas en el registro.")
    else:
        for r in resultados:
            print(f"\n  --- Canal {r['planta']} (Umbral detección = {r['umbral_deteccion']:.2f} °C) ---")
            if not r["perturbaciones"]:
                print("    Sin perturbaciones detectadas.")
            for p in r["perturbaciones"]:
                print(f"    Perturbación #{p['n']}: {TXT_TIPO_PERT.get(p['tipo'], p['tipo'])}")
                print(f"      - Intervalo: t = {p['t_inicio']:.1f} s -> {p['t_fin']:.1f} s (Duración: {p['duracion']:.1f} s)")
                print(f"      - Temperatura previa: {p['y_pre']:.2f} °C | Extremo: {p['y_ext']:.2f} °C (ΔT = {p['desviacion']:+.2f} °C)")
                print(f"      - Reacción PWM: Pico = {p['pwm_pico']:.1f}% (ΔPWM = {p['delta_pwm']:+.1f}%) a los {p['t_pwm_pico']:.1f} s")
                print(f"      - Recuperación al final: {format_val(p['recuperacion_pct'], '.1f')}% | t_rec (al SP): {format_val(p['tiempo_recuperacion_sp'], '.1f')} s")
                print(f"      - Error acumulado: IAE_pert = {p['iae_pert']:.1f}")

    # Avisos del sistema
    todos_avisos = [(r["planta"], a) for r in resultados for a in r["avisos"]]
    if todos_avisos:
        print("\n[5] OBSERVACIONES Y AVISOS TÉCNICOS:")
        for planta, av in todos_avisos:
            print(f"  [!] ({planta}) {av}")

    print("=" * 78 + "\n")

# 6. VISUALIZACIÓN GRÁFICA

def _sombrear_fases(ax: plt.Axes, t: np.ndarray, fases: List[Dict[str, Any]], etiquetar: bool = False) -> None:

    for f in fases:
        col = COLOR_FASE.get(f["tipo"], COLOR_FASE["INDEFINIDO"])
        t0 = t[f["i0"]]
        t1 = t[min(f["i1"] - 1, len(t) - 1)]
        ax.axvspan(t0, t1, color=col, alpha=0.10, lw=0)
        if etiquetar and f["tipo"] != "ESCALON":
            ax.text(
                t0, 1.01, f["nombre"], transform=ax.get_xaxis_transform(),
                fontsize=7.5, color=col, va="bottom", fontweight="bold"
            )


def crear_figura_control(t: np.ndarray, plantas: List[Dict[str, Any]]) -> plt.Figure:

    num_plantas = len(plantas)
    fig, axs = plt.subplots(2, 2, figsize=(12, 8))

    colores_pv = ["#d62728", "#1f77b4"]
    colores_sp = ["#222222", "#444444"]

    # 1. Panel de Temperatura
    ax_temp = axs[0, 0]
    for i, P in enumerate(plantas):
        r = P["res"]
        e = r["escalon"]
        col = colores_pv[i % len(colores_pv)]
        lbl_pv = f"{r['planta']} (OS_Δ={e['os_pct_delta']:.1f}%, OS_sp={e['os_pct_sp']:.1f}%)"
        ax_temp.plot(t, P["pv"], color=col, lw=1.6, label=lbl_pv)
        ax_temp.plot(t, P["sp"], color=colores_sp[i % len(colores_sp)], ls="--", alpha=0.7, lw=1.1, label=f"SP {r['planta']}")

        # Marcar y anotar el pico de sobreimpulso si existe
        if e["sobreimpulso_abs"] > 0.05:
            ax_temp.plot(e["t_step"] + e["t_peak"], e["y_pico"], marker="o", color=col, ms=6)
            ax_temp.annotate(
                f"Pico: {e['y_pico']:.1f}°C\n(+{e['sobreimpulso_abs']:.1f}°C)",
                (e["t_step"] + e["t_peak"], e["y_pico"]),
                textcoords="offset points", xytext=(5, 8),
                fontsize=8, color=col, fontweight="bold"
            )

        # Anotar extremos de perturbaciones
        for p in r["perturbaciones"]:
            mk = "v" if p["tipo"] == "BAJA" else "^"
            ax_temp.plot(p["t_ext"], p["y_ext"], marker=mk, color=COLOR_FASE[p["tipo"]], ms=7)
            ax_temp.annotate(
                f"{p['desviacion']:+.1f}°C",
                (p["t_ext"], p["y_ext"]),
                textcoords="offset points", xytext=(4, -12 if p["tipo"] == "BAJA" else 8),
                fontsize=8, color=COLOR_FASE[p["tipo"]]
            )

        _sombrear_fases(ax_temp, t, r["fases"], etiquetar=(i == 0))

    ax_temp.set_title("Respuesta Temporal del Sistema (Lazo Cerrado)", fontsize=11, fontweight="bold")
    ax_temp.set_ylabel("Temperatura [°C]")
    ax_temp.grid(True, ls=":", alpha=0.6)
    ax_temp.legend(loc="lower right", fontsize=8)

    # 2. Panel de Esfuerzo de Control (PWM)
    ax_pwm = axs[1, 0]
    for i, P in enumerate(plantas):
        col = colores_pv[i % len(colores_pv)]
        ax_pwm.plot(t, P["pwm"], color=col, lw=1.3, label=f"PWM {P['res']['planta']}")
        _sombrear_fases(ax_pwm, t, P["res"]["fases"])
    ax_pwm.axhline(100, color="gray", ls=":", label="Saturación 100%")
    ax_pwm.set_title("Acción de Control / Esfuerzo (PWM)", fontsize=11, fontweight="bold")
    ax_pwm.set_ylabel("Ciclo de Trabajo [%]")
    ax_pwm.set_xlabel("Tiempo [s]")
    ax_pwm.set_ylim(-5, 105)
    ax_pwm.grid(True, ls=":", alpha=0.6)
    ax_pwm.legend(loc="upper right", fontsize=8)

    # 3. Panel de Señal de Error e(t)
    ax_err = axs[0, 1]
    for i, P in enumerate(plantas):
        r = P["res"]
        col = colores_pv[i % len(colores_pv)]
        err = P["sp"] - P["pv"]
        ax_err.plot(t, err, color=col, lw=1.3, label=f"Error {r['planta']} (IAE={r['escalon']['iae']:.0f})")
        _sombrear_fases(ax_err, t, r["fases"])
    ax_err.axhline(0, color="black", ls="--", lw=0.9)
    ax_err.set_title("Señal de Error e(t) = SetPoint - Variable de Proceso", fontsize=11, fontweight="bold")
    ax_err.set_ylabel("Error [°C]")
    ax_err.grid(True, ls=":", alpha=0.6)
    ax_err.legend(loc="upper right", fontsize=8)

    # 4. Panel de Consumo de Corriente Eléctrica
    ax_corr = axs[1, 1]
    tiene_corr = False
    for i, P in enumerate(plantas):
        if P["corr"] is not None and not np.all(np.isnan(P["corr"])):
            tiene_corr = True
            col = colores_pv[i % len(colores_pv)]
            ax_corr.plot(t, P["corr"], color=col, lw=1.3, label=f"Corriente {P['res']['planta']}")
            _sombrear_fases(ax_corr, t, P["res"]["fases"])

    ax_corr.set_title("Consumo de Corriente Eléctrica", fontsize=11, fontweight="bold")
    ax_corr.set_ylabel("Corriente [mA]")
    ax_corr.set_xlabel("Tiempo [s]")
    ax_corr.grid(True, ls=":", alpha=0.6)
    if tiene_corr:
        ax_corr.legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    return fig


def crear_figura_segmentos(t: np.ndarray, plantas: List[Dict[str, Any]]) -> plt.Figure:

    ncol = max(len(P["res"]["fases"]) for P in plantas)
    nrow = len(plantas)
    fig, axs = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 3.8 * nrow), squeeze=False)

    for r_i, P in enumerate(plantas):
        r = P["res"]
        fases = r["fases"]
        for c_i in range(ncol):
            ax = axs[r_i, c_i]
            if c_i >= len(fases):
                ax.axis("off")
                continue
            f = fases[c_i]
            sl = slice(f["i0"], f["i1"])
            col = COLOR_FASE.get(f["tipo"], "#333333")

            ax.plot(t[sl], P["pv"][sl], color=col, lw=1.8, label="Temp [°C]")
            ax.plot(t[sl], P["sp"][sl], "k--", lw=0.9, alpha=0.7, label="SP")
            ax.set_ylabel("Temp [°C]", color=col)
            ax.grid(True, ls=":", alpha=0.5)

            ax_pwm = ax.twinx()
            ax_pwm.plot(t[sl], P["pwm"][sl], color="#7f7f7f", lw=1.1, ls="-.")
            ax_pwm.set_ylabel("PWM [%]", color="#7f7f7f")
            ax_pwm.set_ylim(-5, 105)

            if f["tipo"] == "ESCALON":
                e = r["escalon"]
                sub = f"OS(Δ)={e['os_pct_delta']:.1f}% | OS(sp)={e['os_pct_sp']:.1f}% | tr={format_val(e['t_rise'], '.0f')}s"
            else:
                p = r["perturbaciones"][c_i - 1]
                sub = f"ΔT={p['desviacion']:+.1f}°C | ΔPWM={p['delta_pwm']:+.1f}%"

            ax.set_title(f"{r['planta']} - {f['nombre']}\n{sub}", fontsize=9, fontweight="bold")
            ax.set_xlabel("Tiempo [s]")

    plt.tight_layout()
    return fig


def fig_a_buffer(fig: plt.Figure, ancho_px: int = 800, dpi: int = 100) -> Tuple[io.BytesIO, int, int]:

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    buf.seek(0)
    alto_px = int(ancho_px * fig.get_figheight() / fig.get_figwidth())
    return buf, ancho_px, alto_px

# 7. EXPORTACIÓN PROFESIONAL A EXCEL (MULTIHASH CON FORMATO TÉCNICO)

def limpiar_numero(x: Any, dec: int = 2) -> Any:

    if x is None:
        return None
    if isinstance(x, (bool, np.bool_)):
        return "Sí" if x else "No"
    if isinstance(x, str):
        return x
    try:
        if np.isnan(x) or np.isinf(x):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        r = round(float(x), dec)
        return int(r) if r.is_integer() else r
    return x


def exportar_analisis_excel(
    resultados: List[Dict[str, Any]],
    plantas: List[Dict[str, Any]],
    t: np.ndarray,
    df_params: Optional[pd.DataFrame] = None,
    buffers: Optional[List[Tuple[io.BytesIO, int, int]]] = None,
    archivo_origen: str = "Control.xlsx",
    carpeta_salida: str = CFG["carpeta_salida"]
) -> str:

    os.makedirs(carpeta_salida, exist_ok=True)
    base_nombre = os.path.splitext(os.path.basename(archivo_origen))[0]
    ruta_archivo = os.path.join(carpeta_salida, f"AnalisisControl_{base_nombre}.xlsx")

    wb = openpyxl.Workbook()

    # Estilos estándar para todo el libro
    font_titulo = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_sec = Font(name="Calibri", size=10, bold=True, color="1F4E78")
    font_bold = Font(name="Calibri", size=9, bold=True)
    font_cell = Font(name="Calibri", size=9)
    fill_hdr = PatternFill("solid", fgColor="1F4E78")
    fill_sec = PatternFill("solid", fgColor="D9E1F2")
    fill_highlight = PatternFill("solid", fgColor="FFF2CC")
    border_thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    def formatear_cabecera(ws: Any, row: int, col0: int, textos: List[str]) -> None:
        for idx, txt in enumerate(textos):
            c = ws.cell(row=row, column=col0 + idx, value=txt)
            c.font = font_titulo
            c.fill = fill_hdr
            c.alignment = align_center

    # HOJA 1: RESUMEN EJECUTIVO (ResumenControl)

    ws1 = wb.active
    ws1.title = "ResumenControl"
    ws1.views.sheetView[0].showGridLines = True

    nombres = [r["planta"] for r in resultados]
    cols_hdr = ["Métrica de Desempeño"] + nombres
    formatear_cabecera(ws1, 1, 1, cols_hdr)

    filas_resumen_excel = [
        ("SetPoint Objetivo [°C]", "sp_final", 2),
        ("Temperatura Inicial y0 [°C]", "y_inicial", 2),
        ("Magnitud del Escalón ΔSP [°C]", "delta_sp", 2),
        ("Temp. Máxima Alcanzada [°C]", "y_max", 2),
        ("Temp. Mínima Alcanzada [°C]", "y_min", 2),
        ("Tiempo de Pico tp [s]", "t_peak", 1),
        ("Sobreimpulso Absoluto [°C]", "sobreimpulso_abs", 2),
        ("Sobreimpulso MÉTODO 1 (% de ΔSP)", "os_pct_delta", 2),
        ("Sobreimpulso MÉTODO 2 (% de SP)", "os_pct_sp", 2),
        ("Razón Método 1 / Método 2", "razon_metodos", 2),
        ("Clasificación de Comportamiento", lambda e: e["clasificacion"]["categoria"], 0),
        ("Factor de Amortiguamiento Est. (ζ)", lambda e: e["clasificacion"]["zeta_estimado"], 3),
        ("Tiempo de Subida tr (10-90%) [s]", "t_rise", 1),
        ("Tiempo de Establ. ts (5%) [s]", "t_settling_5", 1),
        ("Tiempo de Establ. ts (2%) [s]", "t_settling_2", 1),
        ("Temp. Régimen Permanente Yss [°C]", "y_ss", 2),
        ("Error de Régimen ess [°C]", "error_ss", 2),
        ("Respuesta Asentada", "asentado", 0),
        ("Índice IAE", "iae", 1),
        ("Índice ISE", "ise", 1),
        ("Índice ITAE", "itae", 1),
        ("PWM Máximo [%]", "pwm_max", 1),
        ("PWM Régimen Estable [%]", "pwm_ss", 1),
        ("Variación Total TV(u)", "tv_u", 1),
        ("Corriente Máx [mA]", "i_max", 1),
        ("Corriente Régimen Estable [mA]", "i_ss", 1),
    ]

    for r_idx, (label, key_or_fn, dec) in enumerate(filas_resumen_excel, start=2):
        c1 = ws1.cell(row=r_idx, column=1, value=label)
        c1.font = font_cell
        c1.border = border_thin
        c1.alignment = align_left

        # Resaltar filas clave de sobreimpulso
        if "Sobreimpulso MÉTODO" in label:
            c1.fill = fill_highlight
            c1.font = font_bold

        for col_idx, r in enumerate(resultados, start=2):
            e = r["escalon"]
            val_raw = key_or_fn(e) if callable(key_or_fn) else e[key_or_fn]
            val = limpiar_numero(val_raw, dec)
            cell = ws1.cell(row=r_idx, column=col_idx, value=val)
            cell.font = font_cell
            cell.border = border_thin
            cell.alignment = align_center
            if "Sobreimpulso MÉTODO" in label:
                cell.fill = fill_highlight
                cell.font = font_bold

    # Sección de Perturbaciones resumidas debajo de la tabla principal
    row_pert_start = len(filas_resumen_excel) + 3
    ws1.cell(row=row_pert_start, column=1, value="Rechazo a Perturbaciones Térmicas").font = font_sec
    ws1.cell(row=row_pert_start, column=1).fill = fill_sec

    filas_p_resumen = [
        ("Perturbaciones Detectadas", lambda r: len(r["perturbaciones"]), 0),
        ("Caída de Temp. Máxima ΔT [°C]", lambda r: (r["perturbaciones"][0]["desviacion"] if r["perturbaciones"] else None), 2),
        ("PWM Máx de Reacción [%]", lambda r: (r["perturbaciones"][0]["pwm_pico"] if r["perturbaciones"] else None), 1),
        ("Tiempo Recuperación al SP [s]", lambda r: (r["perturbaciones"][0]["tiempo_recuperacion_sp"] if r["perturbaciones"] else None), 1),
        ("IAE de Perturbación", lambda r: (r["perturbaciones"][0]["iae_pert"] if r["perturbaciones"] else None), 1),
    ]

    for off, (label, fn, dec) in enumerate(filas_p_resumen, start=1):
        curr_r = row_pert_start + off
        c1 = ws1.cell(row=curr_r, column=1, value=label)
        c1.font = font_cell
        c1.border = border_thin
        for col_idx, r in enumerate(resultados, start=2):
            val = limpiar_numero(fn(r), dec)
            c = ws1.cell(row=curr_r, column=col_idx, value=val)
            c.font = font_cell
            c.border = border_thin
            c.alignment = align_center

    # Parámetros PID en columnas E:J
    col_pid_start = len(nombres) + 3
    if df_params is not None and not df_params.empty:
        cols_pid = [c for c in ['Planta', 'Kp', 'Ki', 'Kd', 'Ts', 'Cambio (s)'] if c in df_params.columns]
        formatear_cabecera(ws1, 1, col_pid_start, cols_pid)
        for f_idx, (_, row_p) in enumerate(df_params.iterrows(), start=2):
            for c_off, h in enumerate(cols_pid):
                val = limpiar_numero(row_p[h], 4)
                c = ws1.cell(row=f_idx, column=col_pid_start + c_off, value=val)
                c.font = font_cell
                c.border = border_thin
                c.alignment = align_center

    # Ajuste de anchos de columna en Hoja 1
    ws1.column_dimensions["A"].width = 36
    ws1.column_dimensions["B"].width = 16
    ws1.column_dimensions["C"].width = 16
    ws1.column_dimensions["D"].width = 4
    for col_char in ["E", "F", "G", "H", "I", "J"]:
        ws1.column_dimensions[col_char].width = 13

    # Incrustar gráfico principal al lado de los datos
    if buffers and len(buffers) > 0:
        buf_img, w_px, h_px = buffers[0]
        buf_img.seek(0)
        img1 = XLImage(io.BytesIO(buf_img.getvalue()))
        img1.width, img1.height = int(w_px * 0.8), int(h_px * 0.8)
        letra_col_img = get_column_letter(col_pid_start)
        ws1.add_image(img1, f"{letra_col_img}6")

    # HOJA 2: PERTURBACIONES DETALLADAS (Perturbaciones)

    ws_p = wb.create_sheet("Perturbaciones")
    ws_p.views.sheetView[0].showGridLines = True
    cols_pert_hdr = [
        "Planta", "N°", "Tipo", "Inicio [s]", "Fin [s]", "Duración [s]",
        "Temp Previa [°C]", "Temp Extremo [°C]", "Desviación ΔT [°C]", "t al Extremo [s]",
        "PWM Previo [%]", "PWM Pico [%]", "ΔPWM [%]", "t al PWM Pico [s]",
        "Recuperación [%]", "t Recup 50% [s]", "t Recup 90% [s]", "t Recup SP [s]",
        "IAE Perturbación", "ISE Perturbación"
    ]
    formatear_cabecera(ws_p, 1, 1, cols_pert_hdr)

    row_p_idx = 2
    for r in resultados:
        for p in r["perturbaciones"]:
            vals_p = [
                r["planta"], p["n"], TXT_TIPO_PERT.get(p["tipo"], p["tipo"]),
                limpiar_numero(p["t_inicio"], 1), limpiar_numero(p["t_fin"], 1), limpiar_numero(p["duracion"], 1),
                limpiar_numero(p["y_pre"], 2), limpiar_numero(p["y_ext"], 2), limpiar_numero(p["desviacion"], 2),
                limpiar_numero(p["t_al_extremo"], 1), limpiar_numero(p["pwm_pre"], 1), limpiar_numero(p["pwm_pico"], 1),
                limpiar_numero(p["delta_pwm"], 1), limpiar_numero(p["t_pwm_pico"], 1), limpiar_numero(p["recuperacion_pct"], 1),
                limpiar_numero(p["t_rec50"], 1), limpiar_numero(p["t_rec90"], 1), limpiar_numero(p["tiempo_recuperacion_sp"], 1),
                limpiar_numero(p["iae_pert"], 1), limpiar_numero(p["ise_pert"], 1)
            ]
            for col_i, v in enumerate(vals_p, start=1):
                c = ws_p.cell(row=row_p_idx, column=col_i, value=v)
                c.font = font_cell
                c.border = border_thin
                c.alignment = align_center
            row_p_idx += 1

    if row_p_idx == 2:
        ws_p.cell(row=2, column=1, value="No se registraron perturbaciones externas.").font = font_cell

    for ci in range(1, len(cols_pert_hdr) + 1):
        ws_p.column_dimensions[get_column_letter(ci)].width = 16

    # HOJA 3: PARÁMETROS PID (ParametrosPID)

    if df_params is not None and not df_params.empty:
        ws_pid = wb.create_sheet("ParametrosPID")
        ws_pid.views.sheetView[0].showGridLines = True
        cols_pid = list(df_params.columns)
        formatear_cabecera(ws_pid, 1, 1, cols_pid)
        for i, (_, row_data) in enumerate(df_params.iterrows(), start=2):
            for j, col_name in enumerate(cols_pid, start=1):
                val = limpiar_numero(row_data[col_name], 4)
                c = ws_pid.cell(row=i, column=j, value=val)
                c.font = font_cell
                c.border = border_thin
                c.alignment = align_center
        for j in range(1, len(cols_pid) + 1):
            ws_pid.column_dimensions[get_column_letter(j)].width = 15

    # HOJA 4: DATOS REMUESTREADOS Y SEGMENTOS (DatosSegmentados)

    ws_seg = wb.create_sheet("DatosSegmentados")
    cab_seg = ["Tiempo [s]"]
    for P in plantas:
        n = P["res"]["planta"]
        cab_seg += [f"{n} Temp [°C]", f"{n} SP [°C]", f"{n} PWM [%]", f"{n} Corriente [mA]", f"{n} Fase"]
    formatear_cabecera(ws_seg, 1, 1, cab_seg)

    # Insertar filas de datos remuestreados
    for i in range(len(t)):
        fila_data: List[Any] = [limpiar_numero(t[i], 1)]
        for P in plantas:
            corr_val = None if (P["corr"] is None or np.isnan(P["corr"][i])) else limpiar_numero(P["corr"][i], 1)
            fila_data += [
                limpiar_numero(P["pv"][i], 2),
                limpiar_numero(P["sp"][i], 2),
                limpiar_numero(P["pwm"][i], 1),
                corr_val,
                str(P["res"]["etiqueta"][i])
            ]
        ws_seg.append(fila_data)

    for j in range(1, len(cab_seg) + 1):
        ws_seg.column_dimensions[get_column_letter(j)].width = 16

    # HOJA 5: GRÁFICAS ADICIONALES (Graficas)

    if buffers and len(buffers) > 1:
        ws_g = wb.create_sheet("Graficas")
        fila_g = 1
        for b_img, w_px, h_px in buffers:
            b_img.seek(0)
            img = XLImage(io.BytesIO(b_img.getvalue()))
            img.width, img.height = int(w_px * 0.9), int(h_px * 0.9)
            ws_g.add_image(img, f"A{fila_g}")
            fila_g += int(h_px / 18) + 3

    wb.save(ruta_archivo)
    return ruta_archivo

# 8. PROGRAMA PRINCIPAL Y FLUJO DE EJECUCIÓN

def ejecutar_analisis_completo(path_documento: str, interactivo: bool = True) -> Dict[str, Any]:

    if not os.path.exists(path_documento):
        raise FileNotFoundError(f"No existe el archivo especificado: {path_documento}")

    print(f"\nProcesando archivo: {os.path.basename(path_documento)}")
    df_raw = pd.read_excel(path_documento)
    df = preparar_datos(df_raw, CFG["dt"])
    t = df["Tiempo"].to_numpy(dtype=float)

    print(f"Registro: {len(df_raw)} muestras originales -> {len(df)} puntos uniformes "
          f"(dt={CFG['dt']:.1f} s, duración total: {t[-1] - t[0]:.0f} s)")

    def get_col(col_name: str) -> Optional[np.ndarray]:
        return df[col_name].to_numpy(dtype=float) if col_name in df.columns else None

    # Configuración de plantas
    sp1_col = "SetPoint1" if "SetPoint1" in df.columns else "SetPoint"
    plantas: List[Dict[str, Any]] = [
        {
            "nombre": "Q1",
            "pv": get_col("Temperatura1"),
            "sp": get_col(sp1_col),
            "pwm": get_col("PWM1"),
            "corr": get_col("Corriente1")
        }
    ]

    tiene_q2 = all(c in df.columns for c in ("Temperatura2", "PWM2")) and (
        "SetPoint2" in df.columns or "SetPoint" in df.columns
    )
    if tiene_q2:
        sp2_col = "SetPoint2" if "SetPoint2" in df.columns else "SetPoint"
        plantas.append({
            "nombre": "Q2",
            "pv": get_col("Temperatura2"),
            "sp": get_col(sp2_col),
            "pwm": get_col("PWM2"),
            "corr": get_col("Corriente2")
        })

    # Análisis individual de cada planta
    for P in plantas:
        P["res"] = analizar_planta(
            t, P["pv"], P["sp"], P["pwm"], P["corr"], P["nombre"], CFG
        )

    resultados = [P["res"] for P in plantas]

    # Separación y clasificación de señales según sobreimpulso
    grupos_clasif = separar_y_clasificar_senales(resultados)

    # Parámetros PID del archivo original
    cols_pid = [c for c in ["Planta", "Kp", "Ki", "Kd", "Ts", "Cambio (s)"] if c in df_raw.columns]
    df_params = df_raw[cols_pid].dropna(how="all").copy() if cols_pid else None
    if df_params is not None and not df_params.empty and "Planta" not in df_params.columns:
        df_params.insert(0, "Planta", ["Q1"] * len(df_params))

    # Impresión estructurada en consola
    imprimir_resumen_control(resultados, df_params)

    # Generación de gráficas
    print("Generando figuras técnicas...")
    fig1 = crear_figura_control(t, plantas)
    fig2 = crear_figura_segmentos(t, plantas)
    buffers = [fig_a_buffer(fig1, ancho_px=850), fig_a_buffer(fig2, ancho_px=850)]

    # Exportación a Excel
    ruta_excel = exportar_analisis_excel(
        resultados, plantas, t, df_params, buffers,
        archivo_origen=os.path.basename(path_documento)
    )
    print(f"Reporte técnico exportado exitosamente a:\n  -> {ruta_excel}")

    if interactivo:
        print("\nMostrando figuras interactivas (cierre las ventanas para finalizar)...")
        plt.show()
    else:
        plt.close(fig1)
        plt.close(fig2)

    return {
        "resultados": resultados,
        "grupos_clasificacion": grupos_clasif,
        "ruta_excel": ruta_excel,
        "df_params": df_params
    }


def main() -> None:

    path_documento: Optional[str] = None
    if len(sys.argv) > 1:
        path_documento = sys.argv[1]
    else:
        path_documento = seleccionar_archivo_datos(CFG["carpeta_datos"])

    if not path_documento:
        print("No se seleccionó ningún archivo de datos. Finalizando ejecución.")
        return

    try:
        ejecutar_analisis_completo(path_documento, interactivo=True)
    except Exception as e:
        print(f"\n[ERROR] Ocurrió una excepción durante el procesamiento:\n{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
