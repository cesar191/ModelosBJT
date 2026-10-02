# ModelosBJT

Este repositorio tiene como objetivo identificar y comparar modelos de la planta termica de temperatura a partir de senales de entrada y salida. El analisis se centra en la estimacion de parametros fisicos y en la identificacion de modelos tipo primer orden mas tiempo muerto (FOPDT), con la finalidad de apoyar la validacion y el diseno de estrategias de control.

## Objetivo del proyecto

- Procesar datos experimentales de temperatura y PWM.
- Detectar el segmento util de un escalon de entrada.
- Identificar parametros de los modelos termicos.
- Comparar un modelo fisico con un modelo empirico basado en FOPDT.
- Visualizar la respuesta del sistema para validar la aproximacion.

## Estructura del repositorio

- `recomedados/FOPDTplantasinIA_optimizado.py`: script principal optimizado para analizar la respuesta del sistema con base en FOPDT. Incluye seleccion interactiva de archivos.
- `recomedados/FOPDTplantasinIA.py`: script original para analizar la respuesta del sistema.
- `modelosCalculo/comparacionModelos.py`: comparacion entre modelos fisico y identificado.
- `modelosCalculo/modeloTermicoIA.py`: enfoque de identificacion termica con ajuste y validacion (con IA).
- `data/`: archivos Excel usados como entrada experimental.

## Recomendado

Para el uso principal del proyecto, se recomienda seguir este flujo:

1. Usar `recomedados/FOPDTplantasinIA_optimizado.py` para analizar de manera interactiva multiples archivos de datos, seleccionando graficamente el Excel objetivo.
2. Validar y comparar resultados con `modelosCalculo/comparacionModelos.py` para contrastar el modelo identificado frente a un modelo termico fisico.
3. Usar `modelosCalculo/modeloTermicoIA.py` como base de analisis y comparacion, especialmente cuando se quiera ajustar parametros fisicos o probar diferentes configuraciones.
4. Verificar la calidad del ajuste con metricas como error cuadratico medio (RMSE), tiempo de asentamiento y correlacion con la respuesta real.

## Flujo sugerido de trabajo

1. Preparar o ajustar el archivo de Excel con las senales de tiempo, temperatura y PWM dentro de la carpeta `data/`.
2. Ejecutar el script recomendado segun la etapa del estudio.
3. Seleccionar interactivamente el archivo desde la consola si utiliza la version optimizada.
4. Revisar la respuesta del sistema en la grafica (agrupada en un solo layout cuadruple).
5. Ajustar parametros de potencia, capacidad calorifica o coeficientes termicos si el modelo no representa bien el proceso.
6. Guardar los resultados para comparacion entre distintas condiciones de operacion.

## Recomendacion practica

El modelo mas apropiado para el analisis inicial y para la automatizacion del proceso es el enfoque FOPDT, porque ofrece un balance entre simplicidad, interpretacion fisica y facilidad de ajuste con datos experimentales. El modelo fisico puede servir como referencia teorica, pero la identificacion experimental suele ser la mejor base para control y validacion en este tipo de plantas termicas.

## Como ejecutar

Desde la raiz del repositorio:

```bash
python recomedados/FOPDTplantasinIA_optimizado.py
```

Tambien pueden ejecutarse los scripts de comparacion en la carpeta `modelosCalculo/` para estudiar distintos enfoques.

## Siguientes mejoras sugeridas

- Mejorar la deteccion automatica del escalon.
- Agregar validacion con metricas de error.
- Parametrizar mas valores fisicos en un archivo de configuracion.
- Guardar graficas y resultados en carpetas de salida.
- Separar logica de carga, identificacion y visualizacion en modulos.
