# librerias
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

# el excel que contiene los datos de la grafica
# path_document = 'DatosGrafica_AdquirirQ1_20260530_195139.xlsx'
path_document = 'data\\DatosGrafica_AdquirirQ1_20260530_195139.xlsx'
archivo = pd.read_excel(path_document, dtype=float)

# pwm de trabajo para recortar la señal y los datos en el tiempo
pwm_trabajo = 100

tiempo = archivo.iloc[:, 0]
tiempo = np.double(tiempo)

temperatura1 = archivo.iloc[:, 1]
temperatura1 = np.double(temperatura1)

pwm = archivo.iloc[:, 3]
pwm = np.double(pwm)

# datos para recortar la señal y graficar solo el segmento útil
dxt, dyt, dt = [], [], []

for i in range(len(pwm)):
    if pwm[i] == pwm_trabajo:
        dxt.append(pwm[i])
        dyt.append(temperatura1[i] - temperatura1[0])
        dt.append(tiempo[i])

dt = np.array(dt) - dt[0]  # Normalizar vector de tiempo para que inicie en 0s
dyt = np.array(dyt)
dxt = np.array(dxt)

# 1. Ganancia proporcional estática (Método rápido basado en punto final)
Kp_gain = (dyt[-1]) / (pwm_trabajo)

# 2. Definición matemática del modelo FOPDT (First Order Plus Dead Time)
def fopdt_modelo(t, Kp, tau, theta):
    """
    Respuesta temporal analítica de un sistema FOPDT ante un escalón:
    y(t) = Kp * ΔU * (1 - exp(-(t - theta) / tau)) para t > theta
    """
    t_adj = t - theta
    respuesta = np.zeros_like(t_adj, dtype=float)
    indices = t_adj > 0
    respuesta[indices] = Kp * pwm_trabajo * (1.0 - np.exp(-t_adj[indices] / tau))
    return respuesta

# Estimaciones iniciales de parámetros: [Kp, tau, theta]
p0 = [Kp_gain, dt[-1] / 3.0, 5.0]
bounds = ([0.0, 0.1, 0.0], [np.inf, np.inf, dt[-1] / 2.0])

# Ajuste de curvas por mínimos cuadrados
popt, _ = curve_fit(fopdt_modelo, dt, dyt, p0=p0, bounds=bounds)
Kp_opt, tau_opt, theta_opt = popt

# Simulación de la función de transferencia FOPDT obtenida
y_sim_fopdt = fopdt_modelo(dt, Kp_opt, tau_opt, theta_opt)

# Impresión de la función de transferencia en consola
print("==========================================================================")
print("             IDENTIFICACIÓN DE LA FUNCIÓN DE TRANSFERENCIA FOPDT")
print("==========================================================================")
print(f"Ganancia proporcional estática inicial : {Kp_gain:.4f} °C/%PWM")
print(f"Ganancia proporcional óptima (Kp)      : {Kp_opt:.4f} °C/%PWM")
print(f"Constante de tiempo dominante (tau)    : {tau_opt:.2f} segundos")
print(f"Tiempo muerto / retardo (theta)        : {theta_opt:.2f} segundos")
print("--------------------------------------------------------------------------")
print(f"FUNCIÓN DE TRANSFERENCIA G(s) = ({Kp_opt:.4f} / ({tau_opt:.2f}s + 1)) * e^(-{theta_opt:.2f}s)")
print("==========================================================================\n")

# Gráficas
fig, ax = plt.subplots(2, 1, figsize=(10, 8))

# Gráfica 1: Señal original completa (Entrada y Salida)
ax[0].plot(tiempo, temperatura1, label='Temperatura Real (°C)', color='tab:blue')
ax[0].plot(tiempo, pwm, label='PWM de Entrada (%)', color='tab:orange', alpha=0.7)
ax[0].set_ylabel('Magnitud')
ax[0].set_title('Señales de Entrada (PWM) y Salida (Temperatura) Originales')
ax[0].legend()
ax[0].grid(True)

# Gráfica 2: Comparación de la señal real recortada vs Función de Transferencia FOPDT
ax[1].plot(dt, dyt, 'k.', label='Temperatura Real Recortada (ΔT)', alpha=0.4)
ax[1].plot(dt, y_sim_fopdt, 'r-', linewidth=2.5, 
           label=f'FOPDT Identificado: G(s) = ({Kp_opt:.4f} / ({tau_opt:.2f}s + 1)) e^(-{theta_opt:.2f}s)')
ax[1].set_xlabel('Tiempo [s]')
ax[1].set_ylabel('ΔTemperatura [°C]')
ax[1].set_title('Comparación: Respuesta Experimental vs Modelo FOPDT')
ax[1].legend()
ax[1].grid(True)

plt.tight_layout()
plt.show()