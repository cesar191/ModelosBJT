import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from scipy.signal import lti, step
from collections import Counter

# =====================================================================
# 1. PARÁMETROS FÍSICOS (De modeloTermico.py)
# =====================================================================
#para tener un comportamiento ideal se ajusta los valores del modelo fisico para que se asemeje al comportamiento del sistema real

SIGMA = 5.67e-8         # Constante de Stefan-Boltzmann     fijo
AREA = 1.2e-3           # Área efectiva del disipador [m²]  fijo
EPS = 0.9               # Emisividad del material           fijo
COF_TRA_CAL = 5         # Coeficiente de transferencia de calor por convección [W/m²K]  variable
ALPHA = 0.014           # Factor del calentador             variable
MASA = 0.004            # Masa del componente [kg]          fijo
CAP_CAL = 500           # Capacidad calorífica [J/K]        variable


#PATH_DOCUMENTO = 'data\\DatosGrafica_AdquirirQ1_20260525_113127.xlsx'
PATH_DOCUMENTO = 'data\\DatosGrafica_AdquirirQ1_20260530_195139.xlsx'
THETA_FIS = 7.0 # <--- AJUSTAR MANUALMENTE EL TIEMPO MUERTO AQUÍ

# =====================================================================
# 2. MODELOS MATEMÁTICOS Y FUNCIONES FÍSICAS
# =====================================================================

def calcular_funcion_transferencia_fisica(alpha, masa, cap_cal, t_final, cof_tra_cal, area, eps, sigma):
    """Calcula K y tau basándose en leyes físicas."""
    den_comun = cof_tra_cal * area + 4 * eps * sigma * area * t_final**3
    K = alpha / den_comun
    tau = (masa * cap_cal) / den_comun
    return K, tau

def modelo_fopdt(t, K, tau, theta, u_step, tf_init):
    """Modelo de primer orden más tiempo muerto."""
    t_adj = t - theta
    respuesta = np.zeros_like(t_adj)
    indices_activos = t_adj > 0
    respuesta[indices_activos] = K * u_step * (1 - np.exp(-t_adj[indices_activos] / tau))
    return tf_init + respuesta

# =====================================================================
# 3. CLASE DE PROCESAMIENTO (Inspirada en modeloTermicoIA.py)
# =====================================================================

class ThermicAnalyzer:
    def __init__(self, path_excel):
        self.path = path_excel
        self.cargar_datos()

    def cargar_datos(self):
        df = pd.read_excel(self.path)
        self.tiempo = df.iloc[:, 0].astype(float).values
        self.temperatura = df.iloc[:, 1].astype(float).values
        self.pwm = df.iloc[:, 3].astype(float).values

    def detectar_escalon(self):
        valor_pwm_inicial = self.pwm[0]
        temp_inicial = self.temperatura[0]
        indices_cambio = np.where(self.pwm != valor_pwm_inicial)[0]
        if len(indices_cambio) == 0:
            raise ValueError("No se detectó un cambio de escalón.")
            
        idx_inicio = indices_cambio[0]
        t_seg = self.tiempo[idx_inicio:] - self.tiempo[idx_inicio]
        temp_seg = self.temperatura[idx_inicio:]
        u_step = self.pwm[idx_inicio] - valor_pwm_inicial
        return t_seg, temp_seg, u_step, temp_inicial

    def identificar_fopdt(self, t_seg, temp_seg, u_step, temp_init):
        final_temp_avg = np.mean(temp_seg[-5:]) if len(temp_seg) >= 5 else temp_seg[-1]
        K_ini = (final_temp_avg - temp_init) / u_step
        tau_ini = t_seg[-1] / 3
        popt, _ = curve_fit(
            lambda t, K, tau, theta: modelo_fopdt(t, K, tau, theta, u_step, temp_init),
            t_seg, temp_seg, p0=[K_ini, tau_ini, 2.0]
        )
        return popt

# =====================================================================
# 4. EJECUCIÓN Y COMPARACIÓN
# =====================================================================

if __name__ == "__main__":
    
    analyzer = ThermicAnalyzer(PATH_DOCUMENTO)
    
    try:
        # 1. Obtener datos del escalón
        t_seg, temp_seg, u_step, temp_init = analyzer.detectar_escalon()
        t_sim = np.linspace(t_seg.min(), t_seg.max(), 500) # Tiempo suave para simulación
        
        print(f"--- Datos del Experimento ---")
        print(f"ΔU (PWM): {u_step}%")
        print(f"Temperatura Inicial: {temp_init:.2f}°C\n")

        # 2. MODELO FÍSICO (Teórico)
        # Usamos la temperatura final real para el cálculo de la FT física (linealización)
        
        t_final_absoluta = temp_seg.min() + 273.15
        K_fis, tau_fis = calcular_funcion_transferencia_fisica(
            ALPHA, MASA, CAP_CAL, t_final_absoluta, COF_TRA_CAL, AREA, EPS, SIGMA
        )
        
        # Respuesta del modelo físico con tiempo muerto
        y_fis = modelo_fopdt(t_sim, K_fis, tau_fis, THETA_FIS, u_step, temp_init)
        
        print(f"=== MODELO FÍSICO (Teórico) ===")
        print(f"G(s) = ({K_fis:.4f} / ({tau_fis:.2f}s + 1)) * exp(-{THETA_FIS:.2f}s)\n")

        # 3. MODELO IDENTIFICADO (FOPDT)
        K_id, tau_id, theta_id = analyzer.identificar_fopdt(t_seg, temp_seg, u_step, temp_init)
        y_id = modelo_fopdt(t_sim, K_id, tau_id, theta_id, u_step, temp_init)

        print(f"=== MODELO IDENTIFICADO (Ajuste de datos) ===")
        print(f"G(s) = ({K_id:.4f} / ({tau_id:.2f}s + 1)) * exp(-{theta_id:.2f}s)\n")

        # 4. VISUALIZACIÓN
        plt.figure(figsize=(12, 7))
        plt.plot(t_seg, temp_seg, 'k.', alpha=0.3, label='Datos Experimentales')
        plt.plot(t_sim, y_fis, 'b--', linewidth=2, label=f'Modelo Físico (τ={tau_fis:.1f}s, θ={THETA_FIS:.2f}s)')
        plt.plot(t_sim, y_id, 'r-', linewidth=2, label=f'Modelo Identificado (τ={tau_id:.1f}s, θ={theta_id:.2f}s)')
        
        plt.title('Comparativa: Modelo Físico vs Identificación Experimental')
        plt.xlabel('Tiempo desde el escalón [s]')
        plt.ylabel('Temperatura [°C]')
        plt.legend()
        plt.grid(True, linestyle=':', alpha=0.7)
        
        # Guardar resultados o mostrar
        print("Generando gráfica comparativa...")
        plt.show()

    except Exception as e:
        print(f"Error: {e}")
