# ModelosBJT

Este repositorio tiene como objetivo identificar y comparar modelos de la planta térmica de temperatura a partir de señales de entrada y salida. El análisis se centra en la estimación de parámetros físicos y en la identificación de modelos tipo primer orden más tiempo muerto (FOPDT), con la finalidad de apoyar la validación y el diseño de estrategias de control.

## Objetivo del proyecto

- Procesar datos experimentales de temperatura y PWM.
- Detectar el segmento útil de un escalón de entrada.
- Identificar parámetros de los modelos térmicos.
- Comparar un modelo físico con un modelo empírico basado en FOPDT.
- Visualizar la respuesta del sistema para validar la aproximación.

## Estructura del repositorio

- `recomedados/FOPDTplantasinIA.py`: script principal para analizar la respuesta del sistema con base en FOPDT.
- `modelosCalculo/comparacionModelos.py`: comparación entre modelos físico y identificado.
- `modelosCalculo/modeloTermicoIA.py`: enfoque de identificación térmica con ajuste y validación.
- `data/`: archivos Excel usados como entrada experimental.

## Recomendado

Para el uso principal del proyecto, se recomienda seguir este flujo:

1. Usar `recomedados/FOPDTplantasinIA.py` como referencia para la identificación rápida del comportamiento principal del sistema con FOPDT.
2. Validar y comparar resultados con `modelosCalculo/comparacionModelos.py` para contrastar el modelo identificado frente a un modelo térmico físico.
3. Usar `modelosCalculo/modeloTermicoIA.py` como base de análisis y comparación, especialmente cuando se quiera ajustar parámetros físicos o probar diferentes configuraciones.
4. Verificar la calidad del ajuste con métricas como error cuadrático medio (RMSE), tiempo de asentamiento y correlación con la respuesta real.

## Flujo sugerido de trabajo

1. Preparar o ajustar el archivo de Excel con las señales de tiempo, temperatura y PWM.
2. Ejecutar el script recomendado según la etapa del estudio.
3. Revisar la respuesta del sistema en la gráfica generada.
4. Ajustar parámetros de potencia, capacidad calorífica o coeficientes térmicos si el modelo no representa bien el proceso.
5. Guardar los resultados para comparación entre distintas condiciones de operación.

## Recomendación práctica

El modelo más apropiado para el análisis inicial y para la automatización del proceso es el enfoque FOPDT, porque ofrece un balance entre simplicidad, interpretación física y facilidad de ajuste con datos experimentales. El modelo físico puede servir como referencia teórica, pero la identificación experimental suele ser la mejor base para control y validación en este tipo de plantas térmicas.

## Cómo ejecutar

Desde la raíz del repositorio:

```bash
python recomedados/FOPDTplantasinIA.py
```

También pueden ejecutarse los scripts de comparación en la carpeta `modelosCalculo/` para estudiar distintos enfoques.

## Siguientes mejoras sugeridas

- Mejorar la detección automática del escalón.
- Agregar validación con métricas de error.
- Parametrizar más valores físicos en un archivo de configuración.
- Guardar gráficas y resultados en carpetas de salida.
- Separar lógica de carga, identificación y visualización en módulos.

