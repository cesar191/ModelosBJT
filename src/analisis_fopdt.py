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

def seleccionar_archivo_datos(carpeta_datos="data"):
    os.system('cls' if os.name == 'nt' else 'clear')
    
    archivos = glob.glob(os.path.join(carpeta_datos, "*.xlsx"))
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
    resolucion = 4
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

def exportar_analisis_excel(amplitud_escalon, dyt,dxt,dt, temp_ini, temp_fin,
                            p_fopdt, p_fopdt2, p_termicos,
                            kp_ex, tau_ex, theta_ex,
                            muestreo, ctrl_zn, ctrl_iae, ctrl_emp,
                            img_buf=None,
                            archivo_analizar="Adquirir.xlsx",
                            carpeta_salida=os.path.join("AnalisisDatos", "Fopdt")):
    os.makedirs(carpeta_salida, exist_ok=True)
    nombre_archivo = f"AnalisisFopdt_{archivo_analizar}"
    ruta_archivo = os.path.join(carpeta_salida, nombre_archivo)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AnalisisFOPDT"
    ws1=wb.create_sheet(title="SignalRecort")

    

    tiene_excel = not (np.isnan(kp_ex) or np.isnan(tau_ex) or np.isnan(theta_ex))

    # Filas de datos del ensayo y modelos identificados
    filas_datos = [
        ("planta", "Planta Q1"),
        ("Escalon PWM [%]", amplitud_escalon),
        ("Temp Ambiente [°C]", temp_ini),
        ("Temp Final [°C]", temp_fin),
        ("Delta Temp ΔT [°C]", dyt[-1] - dyt[0]),
        ("Tiempo Muestreo Ts [s]", muestreo),
        ("--- FOPDT Metodo 1 ---", None),
        ("Kp (Ganancia)", p_fopdt[0]),
        ("Tau [s]", p_fopdt[1]),
        ("Theta [s]", p_fopdt[2]),
        ("--- FOPDT Metodo 2 ---", None),
        ("Kp (Ganancia)", p_fopdt2[0]),
        ("Tau [s]", p_fopdt2[1]),
        ("Theta [s]", p_fopdt2[2]),
        ("--- Modelo Termico ---", None),
        ("Kp (Ganancia)", p_termicos[0]),
        ("Tau [s]", p_termicos[1]),
    ]

    if tiene_excel:
        filas_datos.extend([
            ("--- FOPDT Excel ---", None),
            ("Kp (Ganancia)", kp_ex),
            ("Tau [s]", tau_ex),
            ("Theta [s]", theta_ex),
        ])

    filas_datos.extend([
        ("--- Rangos Recomendados Ts ---", None),
        ("Ts segun Tau (FOPDT 1) [s]", f"{p_fopdt[1]*0.05:.2f} a {p_fopdt[1]*0.15:.2f}"),
        ("Ts segun Theta (FOPDT 1) [s]", f"{p_fopdt[2]*0.2:.2f} a {p_fopdt[2]*0.6:.2f}"),
    ])
    if tiene_excel:
        filas_datos.extend([
            ("Ts segun Tau (Excel) [s]", f"{tau_ex*0.05:.2f} a {tau_ex*0.15:.2f}"),
            ("Ts segun Theta (Excel) [s]", f"{theta_ex*0.2:.2f} a {theta_ex*0.6:.2f}"),
        ])

    for r_idx, (label, val) in enumerate(filas_datos, start=1):
        ws.cell(row=r_idx, column=1, value=label)
        v = limpiar_numero(val, dec=4) if isinstance(val, (int, float, np.floating, np.integer)) else val
        if v is not None:
            ws.cell(row=r_idx, column=2, value=v)

    # Tabla de parametros PID en columnas E:I
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
    signal_headers = ["Tiempo", "Temperatura", "PWM"]
    for c_idx in range(0,len(signal_headers)):
        ws1.cell(row=1, column=c_idx+1, value=signal_headers[c_idx])
    for i_row in range(0,len(dyt)):
        ws1.cell(row=i_row+2,column=1,value=dt[i_row])
        ws1.cell(row=i_row+2,column=2,value=dyt[i_row])
        ws1.cell(row=i_row+2,column=3,value=dxt[i_row])
    # Anchos de columna
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 4
    ws.column_dimensions["D"].width = 4
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 10
    ws.column_dimensions["G"].width = 10
    ws.column_dimensions["H"].width = 10
    ws.column_dimensions["I"].width = 10

    # Incrustar imagen de la grafica en E6
    if img_buf is not None:
        img_buf.seek(0)
        img = Image(img_buf)
        img.width = 720
        img.height = 480
        ws.add_image(img, "k1")

    wb.save(ruta_archivo)
    return ruta_archivo

def crear_figura_fopdt(tiempo, temperatura1, pwm, dt, dyt, dxt,
                       t1, y1, t2, y2, t3, y3,
                       tc1, yc1, tc2, yc2, tc3, yc3,
                       amplitud_escalon):
    fig, axs = plt.subplots(2, 2, figsize=(12, 8))

    # [0, 0] Originales
    axs[0, 0].plot(tiempo, temperatura1, label='Temperatura Real', color='red')
    axs[0, 0].plot(tiempo, pwm, label='PWM', color='black')
    axs[0, 0].set_title('Senales Originales')
    axs[0, 0].set_ylabel('Temperatura [°C]')
    axs[0, 0].legend()
    axs[0, 0].grid(True, linestyle=':', alpha=0.6)

    # [1, 0] Recortada
    axs[1, 0].plot(dt, dyt, label='Temp Recortada (ΔT)', color='red')
    axs[1, 0].plot(dt, dxt, label='PWM Recortado', color='black')
    axs[1, 0].set_title('Senal Recortada')
    axs[1, 0].set_ylabel('Temperatura [°C]')
    axs[1, 0].set_xlabel('Tiempo [s]')
    axs[1, 0].legend()
    axs[1, 0].grid(True, linestyle=':', alpha=0.6)

    # [0, 1] Modelos
    axs[0, 1].plot(dt, dxt, label='PWM', color='black', alpha=0.3)
    axs[0, 1].plot(dt, dyt, label='Real (ΔT)', color='red')
    axs[0, 1].plot(t1, y1, label='FOPDT', color='orange')
    axs[0, 1].plot(t2, y2, label='Mod. Termico', color='blue')
    if t3 is not None and y3 is not None:
        axs[0, 1].plot(t3, y3, label='FOPDT Excel', color='darkgreen')
    axs[0, 1].set_title(f'Respuestas a {amplitud_escalon}% PWM')
    axs[0, 1].legend()
    axs[0, 1].grid(True, linestyle=':', alpha=0.6)

    # [1, 1] Control PID
    axs[1, 1].plot(tc1, yc1, label='Ziegler-Nichols', color='orange')
    axs[1, 1].plot(tc2, yc2, label='IAE', color='blue')
    axs[1, 1].plot(tc3, yc3, label='Empirico', color='red')
    axs[1, 1].set_title('Respuesta Control PID (Lazo Cerrado)')
    axs[1, 1].set_xlabel('Tiempo [s]')
    axs[1, 1].legend()
    axs[1, 1].grid(True, linestyle=':', alpha=0.6)

    plt.tight_layout()

    # Guardar imagen en memoria para incrustar en Excel
    img_buf = io.BytesIO()
    fig.savefig(img_buf, format='png', dpi=100, bbox_inches='tight')
    img_buf.seek(0)

    return fig, img_buf

def main():
    # 1. Seleccion de archivo
    path_document = seleccionar_archivo_datos("data")
    if not path_document:
        return
    print(f"\nProcesando archivo: {os.path.basename(path_document)}")
    
    # 2. Lectura de datos
    archivo = pd.read_excel(path_document)
    tiempo = np.double(archivo.iloc[:, 0])
    temperatura1 = np.double(archivo.iloc[:, 1])
    pwm = np.double(archivo.iloc[:, 3])
    pwm_trabajo, _ = Counter(pwm).most_common(1)[0]
    
    # Modelo del Excel
    if archivo.shape[1] > 6 and not pd.isna(archivo.iloc[0, 6]):
        Kp_Excel = float(archivo.iloc[0, 6])
        Tau_Excel = float(archivo.iloc[1, 6])
        Tetha_Excel = float(archivo.iloc[2, 6])
        tiene_excel = not (np.isnan(Kp_Excel) or np.isnan(Tau_Excel) or np.isnan(Tetha_Excel))
    else:
        Kp_Excel, Tau_Excel, Tetha_Excel = np.nan, np.nan, np.nan
        tiene_excel = False

    if tiene_excel:
        Gs_Excel = co.tf([Kp_Excel], [Tau_Excel, 1])
        Gs_timeDeath_Excel = co.tf([-Tetha_Excel/2, 1], [Tetha_Excel/2, 1])
        Gs_Excel_DeathTime = Gs_Excel * Gs_timeDeath_Excel

    # 3. Procesamiento y Recorte
    dyt, dxt, dt, e = recortar_senal(temperatura1, pwm, tiempo, pwm_trabajo)
    amplitud_escalon = e[0][0]
    
    # 4. Parametros Fisicos (Configurables)
    cap_cal = 650 # capacidad calorica [J/°C]    
    alpha = 0.014 # coeficiente de conveccion [W/m²°C]    
    cof_tra_cal = 5  # coeficiente de transferencia de calor [W/m°C] 
    
    # 5. Obtencion de Parametros de Modelos
    p_fopdt = funcion_fopdt_planta(dyt, amplitud_escalon, dt)
    p_fopdt2 = funcion_fopdt2_planta(dyt, amplitud_escalon, dt)
    p_termicos = funcion_modelo_termico(cap_cal, alpha, cof_tra_cal, dyt[-1])

    # 6. Funciones de Transferencia
    Gs_timeDeath = co.tf([-p_fopdt[2]/2, 1], [p_fopdt[2]/2, 1])
    Gs_FOPDT = co.tf([p_fopdt[0]], [p_fopdt[1], 1]) * Gs_timeDeath
    Gs_termico = co.tf([p_termicos[0]], [p_termicos[1], 1]) * Gs_timeDeath
    
    Gs_timeDeath2 = co.tf([-p_fopdt2[2]/2, 1], [p_fopdt2[2]/2, 1])
    Gs_FOPDT2 = co.tf([p_fopdt2[0]], [p_fopdt2[1], 1]) * Gs_timeDeath2

    # Imprimir resultados
    print("\n--- Funciones de transferencia ---")
    print(f"FOPDT metodo 1:       ({p_fopdt[0]:.2f}) / ({p_fopdt[1]:.2f}s+1) * e^(-{p_fopdt[2]:.2f}s)")
    print(f"FOPDT metodo 2:       ({p_fopdt2[0]:.2f}) / ({p_fopdt2[1]:.2f}s+1) * e^(-{p_fopdt2[2]:.2f}s)")
    print(f"Mod. Termico:         ({p_termicos[0]:.2f}) / ({p_termicos[1]:.2f}s+1) * e^(-{p_fopdt[2]:.2f}s)")
    if tiene_excel:
        print(f"FOPDT obtenido Excel: ({Kp_Excel:.2f}) / ({Tau_Excel:.2f}s+1) * e^(-{Tetha_Excel:.2f}s)")

    # 7. Simulacion
    t_sim = np.linspace(dt[0], dt[-1], len(dt))
    t1, y1 = co.forced_response(Gs_FOPDT, t_sim, amplitud_escalon)
    t2, y2 = co.forced_response(Gs_termico, t_sim, amplitud_escalon)
    t3, y3 = co.forced_response(Gs_Excel_DeathTime, t_sim, amplitud_escalon) if tiene_excel else (None, None)
    
    # Analisis del tiempo de muestreo
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

    # 8. Control
    muestreo = int(input("\nIngrese el tiempo de muestreo [s]: "))
    tipoControl = "PID"
    
    ctrl_zn_FOPDT, ctrl_iae_FOPDT = system_control(p_fopdt[0], p_fopdt[1], p_fopdt[2], muestreo, tipoControl)
    ctrl_emp = [3.0, 0.02, 0.3]
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

    # 9. Generacion de graficas y buffer para Excel
    print("\nGenerando graficas...")
    fig, img_buf = crear_figura_fopdt(tiempo, temperatura1, pwm, dt, dyt, dxt,
                                      t1, y1, t2, y2, t3, y3,
                                      tc1, yc1, tc2, yc2, tc3, yc3,
                                      amplitud_escalon)

    # 10. Exportacion a Excel con imagen incrustada
    temp_ini = temperatura1[0]
    temp_fin = temp_ini + dyt[-1]
    ruta_excel = exportar_analisis_excel(
        amplitud_escalon, 
        dyt, dxt,dt,
        temp_ini, temp_fin,
        p_fopdt, p_fopdt2, p_termicos,
        Kp_Excel, Tau_Excel, Tetha_Excel,
        muestreo, ctrl_zn_FOPDT, ctrl_iae_FOPDT, ctrl_emp,
        img_buf=img_buf,archivo_analizar=os.path.basename(path_document)
    )
    print(f"Reporte Excel generado en: {ruta_excel}")

    # 11. Visualizacion interactiva
    print("Mostrando graficas interactivas...")
    plt.show()

if __name__ == "__main__":
    main()
