import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import control as co
from collections import Counter

def seleccionar_archivo_datos(carpeta_datos="data"):

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

def main():
    # 1. Seleccion de archivo
    path_document = seleccionar_archivo_datos()
    if not path_document:
        return
    print(f"\nProcesando archivo: {path_document}")
    
    # 2. Lectura de datos
    archivo = pd.read_excel(path_document)
    tiempo = np.double(archivo.iloc[:, 0])
    temperatura1 = np.double(archivo.iloc[:, 1])
    pwm = np.double(archivo.iloc[:, 3])
    pwm_trabajo, _ = Counter(pwm).most_common(1)[0]
    
    # Modelo del Excel
    Kp_Excel, Tau_Excel, Tetha_Excel = archivo.iloc[0, 6], archivo.iloc[1, 6], archivo.iloc[2, 6]
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
    print(f"FOPDT obtenido Excel: ({Kp_Excel:.2f}) / ({Tau_Excel:.2f}s+1) * e^(-{Tetha_Excel:.2f}s)")

    # 7. Simulacion
    t_sim = np.linspace(dt[0], dt[-1], len(dt))
    t1, y1 = co.forced_response(Gs_FOPDT, t_sim, amplitud_escalon)
    t2, y2 = co.forced_response(Gs_termico, t_sim, amplitud_escalon)
    t3, y3 = co.forced_response(Gs_Excel_DeathTime, t_sim, amplitud_escalon)
    
    # Analisis del tiempo de muestreo
    print("\n--- Metodo Tau ---")
    for nombre, tau in [("Excel", Tau_Excel), ("Termico", p_termicos[1]), ("FOPDT", p_fopdt[1]), ("FOPDT2", p_fopdt2[1])]:
        print(f"{nombre}: {tau*0.05:.2f} < T < {tau*0.15:.2f}")

    print("\n--- Metodo Theta ---")
    for nombre, tetha in [("Excel", Tetha_Excel), ("Termico", p_fopdt[2]), ("FOPDT", p_fopdt[2]), ("FOPDT2", p_fopdt2[2])]:
        print(f"{nombre}: {tetha*0.2:.2f} < T < {tetha*0.6:.2f}")

    # 8. Control
    muestreo = 5
    tipoControl = "PID"
    
    ctrl_zn_FOPDT, ctrl_iae_FOPDT = system_control(p_fopdt[0], p_fopdt[1], p_fopdt[2], muestreo, tipoControl)
    Gs_ctrl_zn = co.tf([ctrl_zn_FOPDT[2], ctrl_zn_FOPDT[0], ctrl_zn_FOPDT[1]], [1, 0])
    Gs_ctrl_iae = co.tf([ctrl_iae_FOPDT[2], ctrl_iae_FOPDT[0], ctrl_iae_FOPDT[1]], [1, 0])
    Gs_ctrl_emp = co.tf([0.3, 3, 0.02], [1, 0])

    Gs_fb_zn = co.feedback(Gs_FOPDT * Gs_ctrl_zn, 1, sign=-1)
    Gs_fb_iae = co.feedback(Gs_FOPDT * Gs_ctrl_iae, 1, sign=-1)
    Gs_fb_emp = co.feedback(Gs_FOPDT * Gs_ctrl_emp, 1, sign=-1)

    tc1, yc1 = co.step_response(Gs_fb_zn, t_sim)
    tc2, yc2 = co.step_response(Gs_fb_iae, t_sim)
    tc3, yc3 = co.step_response(Gs_fb_emp, t_sim)

    print(f"\n--- Parametros PID (FOPDT) [T={muestreo}s] ---")
    print(f"Empirico: KP=3.0000, KI=0.0200, KD=0.3000")
    print(f"ZN:       KP={ctrl_zn_FOPDT[0]:.4f}, KI={ctrl_zn_FOPDT[1]:.4f}, KD={ctrl_zn_FOPDT[2]:.4f}")
    print(f"IAE:      KP={ctrl_iae_FOPDT[0]:.4f}, KI={ctrl_iae_FOPDT[1]:.4f}, KD={ctrl_iae_FOPDT[2]:.4f}")

    # 9. Graficas
    fig, axs = plt.subplots(2, 2, figsize=(12, 8))

    # Original vs Recortada
    axs[0, 0].plot(tiempo, temperatura1, label='Temperatura Real', color='red')
    axs[0, 0].plot(tiempo, pwm, label='PWM', color='black')
    axs[0, 0].set_title('Senales Originales')
    axs[0, 0].set_ylabel('Temperatura [°C]')
    axs[0, 0].legend()
    axs[0, 0].grid()

    axs[1, 0].plot(dt, dyt, label='Temp Recortada (ΔT)', color='red')
    axs[1, 0].plot(dt, dxt, label='PWM Recortado', color='black')
    axs[1, 0].set_title('Senal Recortada')
    axs[1, 0].set_ylabel('Temperatura [°C]')
    axs[1, 0].set_xlabel('Tiempo [s]')
    axs[1, 0].legend()
    axs[1, 0].grid()

    # Modelos
    axs[0, 1].plot(dt, dxt, label='PWM', color='black', alpha=0.3)
    axs[0, 1].plot(dt, dyt, label='Real (ΔT)', color='red')
    axs[0, 1].plot(t1, y1, label='FOPDT', color='orange')
    axs[0, 1].plot(t2, y2, label='Mod. Termico', color='blue')
    axs[0, 1].plot(t3, y3, label='FOPDT Excel', color='darkgreen')
    axs[0, 1].set_title(f'Respuestas a {amplitud_escalon}% PWM')
    axs[0, 1].legend()
    axs[0, 1].grid()

    # Control PID
    axs[1, 1].plot(tc1, yc1, label='Ziegler-Nichols', color='orange')
    axs[1, 1].plot(tc2, yc2, label='IAE', color='blue')
    axs[1, 1].plot(tc3, yc3, label='Empirico', color='red')
    axs[1, 1].set_title('Respuesta Control PID (Lazo Cerrado)')
    axs[1, 1].set_xlabel('Tiempo [s]')
    axs[1, 1].legend()
    axs[1, 1].grid()

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
