import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ==========================================
# CONFIGURACIÓN DE PARÁMETROS Y CONSTANTES
# ==========================================
SIGMA = 5.67e-8       # Constante de Stefan-Boltzmann
AREA = 1.2e-3         
EPS = 0.9               
COF_TRA_CAL = 5       
ALPHA = 0.014
MASA = 0.004
CAP_CAL = 500         

#PATH_DOCUMENT = 'DatosGrafica_AdquirirQ1_20260530_195139.xlsx'
PATH_DOCUMENT = 'DatosGrafica_AdquirirQ1_20260525_113127.xlsx'


# ==========================================
# DEFINICIÓN DE FUNCIONES
# ==========================================
def calcular_modelo_termico(eps, sigma, area, cof_tra_cal, qi, ta, alpha):
    """Calcula la temperatura estacionaria del modelo térmico."""
    coefs = [
        eps * sigma * area, 
        0, 
        0, 
        cof_tra_cal * area, 
        -alpha * qi - cof_tra_cal * area * ta - eps * sigma * area * ta**4
    ]
    raices = np.roots(coefs)
    raices_validas = raices[np.isreal(raices) & (raices.real > 0)].real
    return list(raices_validas - 273.15)


def calcular_funcion_transferencia(alpha, masa, cap_cal, t_final, cof_tra_cal, area, eps, sigma):
    """Calcula los coeficientes del numerador y denominador de la FT."""
    den_comun = cof_tra_cal * area + 4 * eps * sigma * area * t_final**3
    num = [0, alpha / den_comun]
    den = [masa * cap_cal / den_comun, 1]
    return num, den


def simular_sistema_discreto(u_entrada, t_tiempo, num_tf, den_tf):
    """
    Simula la respuesta del sistema continuo mediante discretización de Euler.
    
    Parámetros:
    - u_entrada: Array/Serie con la señal de entrada (ej. PWM).
    - t_tiempo: Array/Serie con los vectores de tiempo.
    - num_tf: Lista con los coeficientes del numerador [b1, b0].
    - den_tf: Lista con los coeficientes del denominador [a1, a0].
    
    Retorna:
    - y_salida: Array de NumPy con la respuesta del sistema.
    - T: Período de muestreo calculado.
    """
    N = len(t_tiempo)
    # Cálculo del período de muestreo dinámico
    T = (t_tiempo.iloc[-1] - t_tiempo.iloc[0]) / (N - 1)
    
    # Historial de estados (x: entrada, y: salida)
    x = np.zeros(2)
    y = np.zeros(2)
    y_salida = np.zeros(N)
    
    salida_actual = 0.0
    
    for i in range(N):
        # Desplazamiento de registros anteriores
        x[1] = x[0]
        y[1] = y[0]
        
        # Asignación de valores en el instante actual k
        x[0] = u_entrada.iloc[i]
        y[0] = salida_actual
        
        # Aplicación del método de Euler (Ecuación en diferencias)
        q = [num_tf[0] * x[0], (num_tf[1] * T - num_tf[0]) * x[1]]
        w = [(den_tf[1] * T - den_tf[0]) * y[0]]
        
        y_salida[i] = (sum(q) - sum(w)) / den_tf[0]
        salida_actual = y_salida[i]
        
    return y_salida, T


# ==========================================
# CARGA Y PROCESAMIENTO DE DATOS
# ==========================================

archivo = pd.read_excel(PATH_DOCUMENT, dtype=float)

tiempo = archivo.iloc[:, 0]
temperatura1 = archivo.iloc[:, 1]
pwm = archivo.iloc[:, 3]

qi = 100/100 #valor de pwm de trabajo para recortar la señal y los datos en el tiempo

ta = temperatura1.iloc[0] + 273.15
t_final_absoluta = temperatura1.max() + 273.15

# ==========================================
# OBTENCIÓN DE LA FUNCIÓN DE TRANSFERENCIA
# ==========================================
temp_estacionaria = calcular_modelo_termico(EPS, SIGMA, AREA, COF_TRA_CAL, qi, ta, ALPHA)
num_tf, den_tf = calcular_funcion_transferencia(ALPHA, MASA, CAP_CAL, t_final_absoluta, COF_TRA_CAL, AREA, EPS, SIGMA)

print(f"Temperatura Estacionaria: {temp_estacionaria[0]:.2f} °C")
print(f"FT: {num_tf[1]:.2f} / ({den_tf[0]:.2f}s + {den_tf[1]:.2f})\n")

# Recorte de señal
temp_ambiente = temperatura1.min()
indices_filtrados = pwm[np.isclose(pwm, qi*100)].index

tiempo_recortado = tiempo.loc[indices_filtrados].reset_index(drop=True)
temp_recortada = (temperatura1.loc[indices_filtrados] - temp_ambiente).reset_index(drop=True)
pwm_recortado = pwm.loc[indices_filtrados].reset_index(drop=True)


# ==========================================
# EJECUCIÓN DE LA NUEVA FUNCIÓN DE SIMULACIÓN
# ==========================================
ys_discretizada, T_muestreo = simular_sistema_discreto(pwm_recortado, tiempo_recortado, num_tf, den_tf)

print(f"Período de muestreo calculado T = {T_muestreo:.4f} s")


# ==========================================
# VISUALIZACIÓN DE RESULTADOS
# ==========================================
plt.figure(figsize=(12, 6))
plt.plot(tiempo_recortado, temp_recortada, marker='o', linestyle='-', color='b', label='Temperatura Real (ΔT)')
plt.plot(tiempo_recortado, ys_discretizada, marker='x', linestyle='--', color='g', label='Modelo Térmico (Euler)')
plt.plot(tiempo_recortado, pwm_recortado, marker='.', linestyle='-', color='r', label='Entrada PWM', alpha=0.5)

plt.title('Comparación usando Función de Discretización Modular')
plt.xlabel('Tiempo [s]')
plt.ylabel('Temperatura / PWM')
plt.legend()
plt.grid(True, linestyle=':', alpha=0.6)
plt.show()