#ejecutar pip install numpy pandas matplotlib control
# librerias
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import control as co
from collections import Counter

#modelo FOPDT
def funcion_fopdt_planta(dyt, pwm_trabajo, dt):
    # 1. Ganancia proporcional
    Kp_gain = ((dyt[-1])-dyt[0]) / (pwm_trabajo*1)
    # 2. tau es el tiempo en el que tarda al llegar al 63.2%
    temp_63 = 0.632 * (dyt[-1] - dyt[0])
    index_63 = np.where(dyt >= temp_63)[0][0]
    tiempo_63 = dt[index_63]-dt[0]
    #para encontrar el tiempo de inicio se considera que es cuando el valor de temperatura es mayor a 1°C
    index_inicio = np.where(dyt >= 0.5)[0][0]
    time_star = dt[index_inicio]-dt[0] #también es el tiempo muerto del sistema 
    tau_opt = tiempo_63 - time_star
    Tau_opt = tau_opt
    #3. tetha valor del tiempo muerto
    Theta_opt = time_star

    return [Kp_gain, Tau_opt, Theta_opt]
#modelo termico 
def funcion_modelo_termico(cap_cal, alpha, cof_tra_cal,t_final):
    sigma = 5.67e-8         # Constante de Stefan-Boltzmann     fijo    
    eps = 0.9               # Emisividad del material           fijo
    #pueden cambiar si se pone un disipador
    area = 1.2e-3           # Área efectiva del disipador [m²]  fijo
    masa = 0.004            # Masa del componente [kg]          fijo

    den_comun = cof_tra_cal * area + 4 * eps * sigma * area * (t_final+273.15)**3
    
    Kp_gain = alpha / den_comun
    tau = (masa * cap_cal) / den_comun
    return [Kp_gain, tau]
#funcion para recortar
def recort_signal(y,u,t,value_recort):
    ''' y:salida u:entrada t:salida value_recort:valor de busqueda para el escalon'''
    dyt,dxt,dt=[],[],[]
    escalon=[],[]  #para guardar el escalon y el tiempo para futuras mejoras
    for i in range(len(u)):
        if(i!=0):
            if((u[i]-u[i-1]>0 or u[i]-u[i-1]<0) and u[i]==value_recort):
                escalon[0].append(u[i]-u[i-1])
                escalon[1].append(t[i])          
        if(u[i]==value_recort):
            dyt.append(y[i]-y[0])
            dxt.append(u[i])
            dt.append(t[i])
    dyt=np.array(dyt)
    dxt=np.array(dxt)
    escalon=np.array(escalon)
    dt=np.array(dt)-dt[0]
    
    return dyt,dxt,dt,escalon
#control de zieguels a nichols y IAE
def system_control(Kp_Gain,Tau,Tetha,T_muestreo,typePID):
    T_Control=Tetha+(T_muestreo/2)
    resolucion=4
    if(typePID=="PID" or typePID=="pid" or typePID=="Pid"   ):
        #control Zieguels a nichols
        kpzn=(1.2*(Tau/(Kp_Gain*T_Control)))/resolucion
        kizn=(kpzn/(2*T_Control))/resolucion
        kdzn=(kpzn*(0.5*T_Control))/resolucion
        #control IAE
        kpiae=(1.086/Kp_Gain)*((T_Control/Tau)**(-0.869))
        kiiae=kpiae/(Tau/(0.740-0.130*(T_Control/Tau)))
        kdiae=kpiae*0.348*Tau*((T_Control/Tau)**(0.914))

    elif(typePID=="PI" or typePID=="pi" or typePID=="Pi"):
       kpzn,kizn,kdzn=0,0,0
       kpiae,kiiae,kdiae=0,0,0

    else:
        kpzn,kizn,kdzn=0,0,0
        kpiae,kiiae,kdiae=0,0,0
            
    controlZn=[kpzn,kizn,kdzn]
    controlIAE=[kpiae,kiiae,kdiae]
    return controlZn,controlIAE
#valores del modelo termico que se pueden modificar dependiendo del pwm estos valores pueden cambiar.
cap_cal = 650     #Capacidead Calorica [J/K]   ayuda a la curva lo que se refiere al Tau
alpha = 0.018     #Factor del calentador        ayuda a la ganancia pero afecta mucho más 
cof_tra_cal = 5.5  #Coeficiente de transferencia de calor por convección [W/m²K]  # este ayuda a la ganancia 

# el excel que contiene los datos de la grafica

#path_document = 'data\\DatosGrafica_AdquirirQ1_20260525_113127.xlsx' #100%
path_document = 'data\\DatosGrafica_AdquirirQ1_20260530_195139.xlsx' #50%
#path_document = 'data\\DatosGrafica_AdquirirQ1_20260826_144802.xlsx' #60%
#path_document ='data\\DatosGrafica_AdquirirQ1_20260826_170243.xlsx'#40%

archivo = pd.read_excel(path_document)

# datos sacados del excel
tiempo = archivo.iloc[:, 0]
tiempo = np.double(tiempo)

temperatura1 = archivo.iloc[:, 1]
temperatura1 = np.double(temperatura1)

pwm = archivo.iloc[:, 3]
pwm = np.double(pwm)
pwm_trabajo,_= Counter(pwm).most_common(1)[0]#valor más repetido del PWM

##modelo Excel
print(archivo.iloc[0, 6])
Kp_Excel = archivo.iloc[0, 6]
Tau_Excel = archivo.iloc[1, 6]
Tetha_Excel = archivo.iloc[2, 6]
Gs_Excel=co.tf([Kp_Excel],[Tau_Excel,1])
Gs_timeDeath_Excel = co.tf([-Tetha_Excel/2,1], [Tetha_Excel/2,1])
Gs_Excel_DeathTime=Gs_Excel*Gs_timeDeath_Excel

#modelo a Codigo
dyt,dxt,dt,e=recort_signal(temperatura1,pwm,tiempo,pwm_trabajo)
print(f"temperatura final {dyt[-1]}")
#paramaetros de la funcion de transferencia FOPDT y del modelo termico
parametros_fopdt = funcion_fopdt_planta(dyt, e[0][0],dt)
parametros_termicos= funcion_modelo_termico(cap_cal, alpha, cof_tra_cal, dyt[-1])
#modelo de Pade
Gs_timeDeath = co.tf([-parametros_fopdt [2]/2,1], [parametros_fopdt [2]/2,1])
#modelos con tiempo muerto
Gs = co.tf([parametros_fopdt [0]], [parametros_fopdt [1], 1])
Gs_termico1 = co.tf([parametros_termicos[0]], [parametros_termicos[1], 1])
Gs_termico=Gs_termico1*Gs_timeDeath
Gs_FOPDT = Gs*Gs_timeDeath
print("\n-----Funciones de transferencia-----\n")
print(f"FOPDT: ({parametros_fopdt[0]:.2f})/({parametros_fopdt[1]:.2f}s+1) *e^{parametros_fopdt[2]*-1:.2f}")
print(f"Modelo Térmico: ({parametros_fopdt[0]:.2f})/({parametros_termicos[1]:.2f}s+1)*e^{parametros_fopdt[2]*-1:.2f}")
print(f"FOPDT Excel: ({Kp_Excel:.2f})/({Tau_Excel:.2f}s+1)*e^{Tetha_Excel*-1:.2f}")

#saco los valores iniciales de tiempo para una respeus simulada 
t_sim_start = dt[0]
t_sim_end = dt[-1]
num_sim_points = len(dt) 
t_sim = np.linspace(t_sim_start, t_sim_end, num_sim_points)
#simulo la respuestas con el tiempo establecido
t1, y1 = co.forced_response(Gs_FOPDT, t_sim, e[0][0])
t2, y2 = co.forced_response(Gs_termico, t_sim, e[0][0])
t3, y3 = co.forced_response(Gs_Excel_DeathTime, t_sim, e[0][0])


#sacamos el tiempo de muestreo analizando las funciones de trasnferencia
# metodo 1 Tau
print("\n--------Metodo tau---------\n")
print(f"Excel: {Tau_Excel*0.05:.2f}< T <{Tau_Excel*0.15:.2f}")
print(f"Termico: {parametros_termicos[1]*0.05:.2f}< T <{parametros_termicos[1]*0.15:.2f}")
print(f"FOPDT: {parametros_fopdt[1]*0.05:.2f}< T <{parametros_fopdt[1]*0.15:.2f}")
#metodo 2 tiempo Muerto

print("\n--------Metodo tetha---------\n")
print(f"Excel:      {Tetha_Excel*0.2:.2f}< T <{Tetha_Excel*0.6:.2f}")
print(f"Termico:    {parametros_fopdt[2]*0.2:.2f}< T <{parametros_fopdt[2]*0.6:.2f}")
print(f"FOPDT:      {parametros_fopdt[2]*0.2:.2f}< T <{parametros_fopdt[2]*0.6:.2f}")

#definimos un tiempo de muestreo de 5 segundos
muestreo=5

#controlzn,controliae=system_control(Kp_Excel,Tau_Excel,Tetha_Excel,muestreo,"PID") #parametros de control excel
controlzn,controliae=system_control(parametros_fopdt[0],parametros_fopdt[1],parametros_fopdt[2],muestreo,"PID") #parametros de control FOPDT
#controlzn,controliae=system_control(parametros_termicos[0],parametros_termicos[1],parametros_fopdt[2],muestreo,"PID") #parametros de control modelo fisico


Gscontrolzn=co.tf([controlzn[2],controlzn[0],controlzn[1]],[1,0])
Gscontroliae=co.tf([controliae[2],controliae[0],controliae[1]],[1,0])
Gscontrolempirico=co.tf([0.3,3,0.02],[1,0])

#Gs_control=Gs_Excel
Gs_control=Gs_FOPDT
#Gs_control=Gs_termico

GsFeedbackzn=co.feedback(Gs_control*Gscontrolzn,1,sign=-1)
GsFeedbackiae=co.feedback(Gs_control*Gscontroliae,1,sign=-1)
GsFeedbackempirico=co.feedback(Gs_control*Gscontrolempirico,1,sign=-1)

t4,y4=co.step_response(GsFeedbackzn,t_sim)
t5,y5=co.step_response(GsFeedbackiae,t_sim)
t6,y6=co.step_response(GsFeedbackempirico,t_sim)

print(f"\n------- metodos de control FOPDT T = {muestreo} ---\n")
print(f"empirico: KP= 3 ki= 0.02 kd= 0.3")
print(f"ZN: KP= {controlzn[0]:.4f} ki= {controlzn[1]:.4f} kd= {controlzn[2]:.4f}")
print(f"IAE: KP= {controliae[0]:.4f} ki= {controliae[1]:.4f} kd= {controliae[2]:.4f}")

# Gráficas
plt.figure()
# Gráfica 1: Señal original completa (Entrada y Salida)
plt.subplot(2,1,1)
plt.plot(tiempo, temperatura1, label='Temperatura Real (°C)',color='red')
plt.plot(tiempo, pwm, label='PWM de Entrada (%)',color='black')
plt.ylabel('Temperatura [°C]')
#plt.xlabel('Tiempo [s]')
plt.title('Señales Originales Vs Recordad')
plt.legend()
plt.grid(True)

# Gráfica 2: Comparación de la señal real recortada
#plt.figure(2)
plt.subplot(2,1,2)
plt.plot(dt, dyt, label='Temperatura Real Recortada (ΔT)',color='red')
plt.plot(dt, dxt, label='PWM Recortado (%)',color='black')
plt.xlabel('Tiempo [s]')
plt.ylabel('Temperatura [°C]')
#plt.title('señal recortada')
plt.legend()
plt.grid(True)
# Grafica 3: respuesta de la señal FOPDT
plt.figure()
plt.plot(dt, dxt, label='PWM Recortado (%)',color='black')
plt.plot(dt, dyt, label='Temperatura Real Recortada (ΔT)',color='red')
plt.plot(t1, y1, label='FOPDT',color='orange')
plt.plot(t2, y2, label='Modelo Térmico',color='blue')
plt.plot(t3, y3, label='FOPDT Excel',color='darkgreen')
plt.xlabel('Tiempo [s]')
plt.ylabel('Temperatura [°C]')
plt.title(f'Respuesta a {e[0][0]} % PWM')
plt.legend()
plt.grid(True)
#Grafica 4: PID
plt.figure()
plt.plot(t4, y4, label='Zn',color='orange')
plt.plot(t5, y5, label='IAE',color='blue')
plt.plot(t6, y6, label='empirico',color='red')
plt.xlabel('Tiempo [s]')
plt.ylabel('Temperatura [°C]')
plt.title('Control  FOPDT')
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()
