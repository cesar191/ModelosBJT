import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from scipy.signal import lti, step


# Ubicación del archivo de datos
PATH_DOCUMENTO = 'DatosGrafica_AdquirirQ1_20260525_113127.xlsx'
# =====================================================================
# 1. MODELOS MATEMÁTICOS (Fáciles de expandir en el futuro)
# =====================================================================

def modelo_primer_orden_puro(t, K, tau, u_step):
    """Modelo clásico de primer orden sin retraso."""
    return K * u_step * (1 - np.exp(-t / tau))

def modelo_fopdt(t, K, tau, theta, u_step, tf_init):
    """Modelo de primer orden más tiempo muerto (FOPDT)."""
    t_adj = t - theta
    respuesta = np.zeros_like(t_adj)
    indices_activos = t_adj > 0
    
    # y(t) = T_init + K * ΔU * (1 - e^(-(t-θ)/τ))
    respuesta[indices_activos] = K * u_step * (1 - np.exp(-t_adj[indices_activos] / tau))
    return tf_init + respuesta


# =====================================================================
# 2. CLASE PRINCIPAL DE IDENTIFICACIÓN (Clean Code & Arquitectura)
# =====================================================================

class ThermicIdentifier:
    """Clase encargada de procesar datos experimentales e identificar 
    funciones de transferencia térmicas."""
    
    def __init__(self, path_excel):
        self.path = path_excel
        self.tiempo = None
        self.temperatura = None
        self.pwm = None
        self.cargar_datos()

    def cargar_datos(self):
        """Lee el archivo Excel y extrae las señales base."""
        df = pd.read_excel(self.path)
        self.tiempo = df.iloc[:, 0].astype(float).values
        self.temperatura = df.iloc[:, 1].astype(float).values
        self.pwm = df.iloc[:, 3].astype(float).values

    def detectar_escalon(self):
        """Detecta automáticamente el inicio, magnitudes y recorta el segmento útil."""
        valor_pwm_inicial = self.pwm[0]
        temp_inicial = self.temperatura[0]
        
        # Encontrar dónde cambia el PWM
        indices_cambio = np.where(self.pwm != valor_pwm_inicial)[0]
        if len(indices_cambio) == 0:
            raise ValueError("No se detectó un cambio de escalón en la señal de PWM.")
            
        idx_inicio = indices_cambio[0]
        
        # Recortar y normalizar segmentos
        t_segmento = self.tiempo[idx_inicio:] - self.tiempo[idx_inicio]
        temp_segmento = self.temperatura[idx_inicio:]
        pwm_segmento = self.pwm[idx_inicio:]
        
        u_step = pwm_segmento[0] - valor_pwm_inicial
        
        return t_segmento, temp_segmento, u_step, temp_inicial

    def identificar_primer_orden_puro(self, t_seg, temp_seg, u_step):
        """MÉTODO 1: Identificación de Primer Orden Puro (Ajustando delta de Temp)."""
        temp_cambio = temp_seg - temp_seg.min()
        
        # Estimaciones iniciales
        K_ini = temp_cambio.max() / u_step
        tau_ini = t_seg[-1] / 3
        
        # Ajuste de curva fijando 'u_step' mediante una función lambda
        popt, _ = curve_fit(
            lambda t, K, tau: modelo_primer_orden_puro(t, K, tau, u_step),
            t_seg, temp_cambio, p0=[K_ini, tau_ini]
        )
        return popt[0], popt[1]  # Retorna K, tau

    def identificar_fopdt(self, t_seg, temp_seg, u_step, temp_init):
        """MÉTODO 2: Identificación de Primer Orden + Tiempo Muerto (FOPDT)."""
        # Estimaciones iniciales
        final_temp_avg = np.mean(temp_seg[-5:]) if len(temp_seg) >= 5 else temp_seg[-1]
        K_ini = (final_temp_avg - temp_init) / u_step
        tau_ini = t_seg[-1] / 3
        theta_ini = 5.0  # Suposición inicial de 5 segundos de retraso
        
        # Ajuste de curva fijando 'u_step' y 'temp_init'
        popt, _ = curve_fit(
            lambda t, K, tau, theta: modelo_fopdt(t, K, tau, theta, u_step, temp_init),
            t_seg, temp_seg, p0=[K_ini, tau_ini, theta_ini]
        )
        return popt[0], popt[1], popt[2]  # Retorna K, tau, theta


# =====================================================================
# 3. BLOQUE DE EJECUCIÓN PRINCIPAL (Script de Usuario)
# =====================================================================

if __name__ == "__main__":
    
    
    
    # Inicializar el identificador
    identificador = ThermicIdentifier(PATH_DOCUMENTO)
    
    try:
        # Segmentar los datos automáticamente
        t_seg, temp_seg, u_step, temp_init = identificador.detectar_escalon()
        
        print(f"¡Escalón detectado! Magnitud ΔU = {u_step} %PWM. Temperatura inicial = {temp_init}°C.\n")
        
        # --- SOLUCIÓN AL ERROR DE ESPACIADO ---
        # Creamos un vector de tiempo ideal, perfectamente equiespaciado, con la misma duración y cantidad de puntos
        t_sim_ideal = np.linspace(t_seg.min(), t_seg.max(), len(t_seg))
        
        # -----------------------------------------------------------------
        # EJECUCIÓN MÉTODO 1: Primer Orden Puro
        # -----------------------------------------------------------------
        K1, tau1 = identificador.identificar_primer_orden_puro(t_seg, temp_seg, u_step)
        
        # Usamos el tiempo ideal para la simulación de SciPy
        sistema1 = lti([K1], [tau1, 1])
        _, y_sim1 = step(sistema1, T=t_sim_ideal)
        y_pred1 = temp_init + (y_sim1 * u_step) 
        
        print("=== MÉTODO 1: PRIMER ORDEN PURO ===")
        print(f"G(s) = {K1:.4f} / ({tau1:.2f}s + 1)\n")
        
        # -----------------------------------------------------------------
        # EJECUCIÓN MÉTODO 2: FOPDT (Con tiempo muerto)
        # -----------------------------------------------------------------
        K2, tau2, theta2 = identificador.identificar_fopdt(t_seg, temp_seg, u_step, temp_init)
        # Evaluamos el modelo FOPDT usando también el tiempo ideal
        y_pred2 = modelo_fopdt(t_sim_ideal, K2, tau2, theta2, u_step, temp_init)
        
        print("=== MÉTODO 2: FOPDT (TIEMPO MUERTO) ===")
        print(f"G(s) = ({K2:.4f} / ({tau2:.2f}s + 1)) * exp(-{theta2:.2f}s)\n")
        
        # -----------------------------------------------------------------
        # GRÁFICA COMPARATIVA FINAL
        # -----------------------------------------------------------------
        plt.figure(figsize=(12, 6))
        # Graficamos los datos reales dispersos como puntos
        plt.plot(t_seg, temp_seg, 'b.', alpha=0.4, label='Datos Reales del Excel')
        # Graficamos las curvas continuas usando el tiempo ideal síncrono
        plt.plot(t_sim_ideal, y_pred1, 'g--', linewidth=2, label=f'Método 1: 1er Orden Puro (τ={tau1:.1f}s)')
        plt.plot(t_sim_ideal, y_pred2, 'r-', linewidth=2.5, label=f'Método 2: FOPDT (τ={tau2:.1f}s, θ={theta2:.1f}s)')
        
        plt.title('Comparativa de Modelos de Identificación Térmica BJT')
        plt.xlabel('Tiempo normalizado (segundos)')
        plt.ylabel('Temperatura Absoluta (°C)')
        plt.legend(loc='lower right')
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.show()
        
    except Exception as error:
        print(f"Ocurrió un error durante la ejecución: {error}")