# Tasks for DeepSeek (modelo económico)
# Estas son tareas de bajo costo cognitivo, bien definidas, con output esperado claro.
# Prioridad: costo computacional mínimo.

## Tarea 1: Calendario de feriados argentinos 2010-2030
# Output: CSV con columnas [date, name]
# Formato: YYYY-MM-DD, nombre del feriado
# Usar pandas o python-holidays
# Guardar en: shared/data/lab_inputs/feriados_ar.csv

## Tarea 2: Validar cobertura de ccl_diario
# Input: historico.duckdb → ccl_diario
# Output: reporte de gaps > 5 días, rango total, estadísticas básicas
# Script simple de 20 líneas

## Tarea 3: Extraer tasa de caución diaria
# Input: caucion.duckdb
# Output: CSV con [date, tna_promedio, volumen_total]
# La tabla de caución tiene estructura ya conocida
# Validar que los tipos de datos sean correctos

## Tarea 4: Generar feature ccl_return_Nd en feature_engine.py
# Agregar al compute_all_features:
#   ccl_return_1d, ccl_return_5d (pct_change del CCL)
# Debe usar el parámetro de columna configurable (price_col)
# Tests mínimos: verificar que el signo sea correcto

## Tarea 5: Test de integración del duckdb_loader.py
# Verificar que los 11 tickers US cargan sin errores
# Verificar que las fechas son consistentes entre tickers
# Output: print de rangos de fechas por ticker
