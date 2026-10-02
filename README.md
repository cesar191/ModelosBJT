# ModelosBJT

Este repositorio tiene como objetivo identificar y comparar modelos de una planta térmica (temperatura) a partir de señales de entrada (PWM) y salida (Temperatura). El análisis se centra en la estimación de parámetros físicos y en la identificación de modelos empíricos tipo **Primer Orden Más Tiempo Muerto (FOPDT)**, con la finalidad de apoyar la validación y el diseño de estrategias de control.

## Objetivo del Proyecto

- **Procesar datos experimentales** de temperatura y PWM obtenidos del sistema real.
- **Detectar el segmento útil** de un escalón de entrada en los datos.
- **Identificar parámetros** de los modelos térmicos (Ganancia, Constante de tiempo, Tiempo muerto).
- **Comparar** un modelo físico teórico con un modelo empírico basado en FOPDT.
- **Visualizar la respuesta del sistema** para validar la aproximación y diseñar controladores PID/PI.

## Estructura del Repositorio

El proyecto ha sido optimizado para mayor legibilidad y facilidad de uso:

- `src/analisis_fopdt.py`: Script principal optimizado para analizar la respuesta del sistema con base en modelos FOPDT. Incluye una interfaz interactiva por consola para seleccionar el archivo de datos deseado.
- `src/comparacion_modelos.py`: Script para comparar detalladamente el modelo empírico identificado frente a un modelo térmico físico.
- `data/`: Directorio que contiene los archivos de datos experimentales en formato Excel (`.xlsx`), junto con imágenes de gráficas comparativas.
- `matlab/`: Archivos y scripts adicionales (ej. `pruebaPlantaExcel.mlx`).

## Cómo Empezar

### Requisitos

Instalar las librerías necesarias ejecutando:

```bash
pip install numpy pandas matplotlib control scipy
```

### Ejecución de los Scripts

Desde la raíz del repositorio, puedes ejecutar los scripts principales:

**1. Análisis Interactivo de FOPDT**
Este script permite seleccionar un archivo Excel de la carpeta `data/` y realiza el cálculo de FOPDT y la simulación de control:
```bash
python src/analisis_fopdt.py
```

**2. Comparación de Modelos Físicos y Empíricos**
Para comparar el comportamiento de la planta frente a modelos teóricos:
```bash
python src/comparacion_modelos.py
```

## Flujo Sugerido de Trabajo

1. **Preparar datos**: Coloca tu archivo Excel con las señales (tiempo, temperatura y PWM) en la carpeta `data/`.
2. **Análisis FOPDT**: Ejecuta `src/analisis_fopdt.py` y selecciona interactivamente tu archivo.
3. **Revisar visualización**: Analiza las gráficas generadas que comparan la señal real recortada con las respuestas simuladas y las acciones de control.
4. **Validar y Comparar**: Si necesitas contrastar con el modelo físico, ejecuta `src/comparacion_modelos.py` y ajusta los parámetros de potencia, capacidad calorífica, o coeficientes térmicos en el código si fuera necesario.

## Recomendación Práctica

El modelo más apropiado para el análisis inicial y para la automatización del proceso es el enfoque **FOPDT**, ya que ofrece un balance óptimo entre simplicidad, interpretación física y facilidad de ajuste con datos experimentales. El modelo físico es excelente como referencia teórica, pero la identificación experimental es la mejor base para el control y validación de plantas térmicas.
