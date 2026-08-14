# librerias
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import control as co
from collections import Counter


def funcion_fopdt_planta(dt, dyt, pwm_trabajo):
    # 1. Ganancia proporcional
    Kp_gain = ((dyt[-1])-dyt[0]) / (pwm_trabajo)
    # tau
    temp_63 = 0.632 * (dyt[-1] - dyt[0])
    index_63 = np.where(dyt >= temp_63)[0][0]
    tiempo_63 = dt[index_63]-dt[0]
    #para encontrar el tiempo de inicio se considera que es cuando el valor de temperatura es mayor a 1°C
    index_inicio = np.where(dyt >= 0.5)[0][0]
    time_star = dt[index_inicio]-dt[0] #también es el tiempo muerto
    tau_opt = tiempo_63 - time_star
    print(f"Ganancia: {Kp_gain:.4f}, Tau: {tau_opt:.4f}s, death_time: {time_star:.4f}s")
    print(f"G(s): {Kp_gain:.4f}/({tau_opt:.4f}s*s + 1) * e^(-{time_star:.4f}s*s)")
    Tau_opt = tau_opt
    theta_opt = time_star

    return [Kp_gain, Tau_opt, theta_opt]
def funcion_modelo_termico(cap_cal, alpha, cof_tra_cal,t_final):
    sigma = 5.67e-8         # Constante de Stefan-Boltzmann     fijo
    area = 1.2e-3           # Área efectiva del disipador [m²]  fijo
    eps = 0.9               # Emisividad del material           fijo
    masa = 0.004            # Masa del componente [kg]          fijo

    """Calcula K y tau basándose en leyes físicas."""
    den_comun = cof_tra_cal * area + 4 * eps * sigma * area * (t_final+273.15)**3
    K = alpha / den_comun
    tau = (masa * cap_cal) / den_comun
    print(f"Modelo térmico: K = {K:.4f}, tau = {tau:.2f}s")
    print(f"G(s): {K:.4f}/({tau:.2f}s + 1)")
    return [K, tau]
#valores del modelo termico que se pueden modificar dependiendo del pwm estos valores pueden cambiar.
cap_cal = 700     #Capacidead Calorica [J/K]  
alpha = 0.018     #Factor del calentador
cof_tra_cal = 10  #Coeficiente de transferencia de calor por convección [W/m²K] 

# el excel que contiene los datos de la grafica
#path_document = 'DatosGrafica_AdquirirQ1_20260530_195139.xlsx'
path_document = 'DatosGrafica_AdquirirQ1_20260525_113127.xlsx'
archivo = pd.read_excel(path_document)

# pwm de trabajo para recortar la señal y los datos en el tiempo


tiempo = archivo.iloc[:, 0]
tiempo = np.double(tiempo)

temperatura1 = archivo.iloc[:, 1]
temperatura1 = np.double(temperatura1)

pwm = archivo.iloc[:, 3]
pwm = np.double(pwm)

pwm_trabajo,_= Counter(pwm).most_common(1)[0]


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
#paramaetros de la funcion de transferencia FOPDT y del modelo termico
default_params = funcion_fopdt_planta(dt, dyt, pwm_trabajo)
default_params_termico = funcion_modelo_termico(cap_cal, alpha, cof_tra_cal, dyt[-1])

Gs_timeDeath = co.tf([-default_params[2]/2,1], [default_params[2]/2,1])
Gs = co.tf([default_params[0]], [default_params[1], 1])
Gs_termico1 = co.tf([default_params_termico[0]], [default_params_termico[1], 1])
Gs_termico=Gs_termico1*Gs_timeDeath
Gs_FOPDT = Gs*Gs_timeDeath

print(f"Función de transferencia FOPDT: {Gs}")
print(f"Función de transferencia Modelo Térmico: {Gs_termico1}")

# Fix for ValueError: Parameter `T`: time values must be equally spaced.
# Create an equally spaced time vector for the simulation
t_sim_start = dt[0]
t_sim_end = dt[-1]
num_sim_points = len(dt) # Use the same number of points for similar resolution
t_sim = np.linspace(t_sim_start, t_sim_end, num_sim_points)

# Simulate the step response using the equally spaced time vector
# and the constant PWM value as the input magnitude for both systems
t1, y1 = co.forced_response(Gs_FOPDT, t_sim, pwm_trabajo)
t2, y2 = co.forced_response(Gs_termico, t_sim, pwm_trabajo)

# Gráficas

plt.figure(1)
# Gráfica 1: Señal original completa (Entrada y Salida)
plt.plot(tiempo, temperatura1, label='Temperatura Real (°C)', color='tab:blue')
plt.plot(tiempo, pwm, label='PWM de Entrada (%)', color='tab:orange')
plt.ylabel('Temperatura [°C]')
plt.xlabel('Tiempo [s]')
plt.title('Señales Originales')
plt.legend()
plt.grid(True)

# Gráfica 2: Comparación de la señal real recortada vs Función de Transferencia FOPDT
plt.figure(2)
plt.plot(dt, dyt, label='Temperatura Real Recortada (ΔT)')
plt.plot(dt, dxt, label='PWM Recortado (%)', color='tab:orange')
plt.xlabel('Tiempo [s]')
plt.ylabel('Temperatura [°C]')
plt.title('señal recortada')
plt.legend()
plt.grid(True)

plt.figure(3)
plt.plot(t1, y1, label='FOPDT')
plt.plot(t2, y2, label='Modelo Térmico', color='tab:orange')
plt.plot(dt, dyt, label='Temperatura Real Recortada (ΔT)', color='tab:red')
plt.plot(dt, dxt, label='PWM Recortado (%)')
plt.xlabel('Tiempo [s]')
plt.ylabel('Temperatura [°C]')
plt.title('Step response')
plt.legend()
plt.grid(True)

# Corrected plotting: y1 already represents the response to pwm_trabajo
#plt.plot(t1, y1, 'k.', label='FOPDT (Simulated)', alpha=0.4)

plt.tight_layout()
plt.show()



