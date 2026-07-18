# Preguntas al Auditor — sobre `auditoria_2.md`

## 1. Próximo-open horizonte (sección 3.1)

> exit_idx = entry_idx + horizon - 1

Con horizon=1: entry en open de t+1, exit en close de t+1. Son 0 sesiones de holding. ¿Es intencional? Un trade de 1 sesión significa comprar al open y vender al close del mismo día. Si el objetivo es 1 día de holding, ¿no debería ser `exit_idx = entry_idx + horizon`?

Pregunta concreta: **para horizon=1, ¿entry open t+1, exit close t+1 está bien, o debería ser exit close t+2 (1 sesión completa de diferencia)?**

---

## 2. Feature engine: close_breaks_high_20d (sección 2)

La feature `close_breaks_high_20d` se calcula como:

```python
close > high.rolling(20).max().shift(1)
```

Esta feature se usa en EXP-04. ¿Es correcta o debería comparar contra el máximo de las últimas 20 sesiones *anteriores* (excluyendo la actual)? El `.shift(1)` ya hace eso, pero quiero confirmar que la intención es "cierra por arriba del máximo de los últimos 20 días" (breakout), no "está por arriba del máximo incluyendo hoy" (que sería siempre true).

---

## 3. Fechas de holdout y purge (sección 10)

La auditoría pide que un trade pertenezca a una partición solo si `signal_date`, `entry_date` y `exit_date` están todos dentro de la misma partición. También sugiere excluir trades cuyo holding window cruce un borde.

Para un trade signal=T, entry=T+1, exit=T+6: si T está en discovery pero T+6 cae en validation, ¿debería descartarse el trade completamente, o asignarse a la partición donde cae la mayoría de las fechas?

Pregunta concreta: **¿qué partición gana cuando las tres fechas no coinciden? ¿Descartar siempre, o asignar por majority?**

---

## 4. Baselines matching (sección 6.2)

La auditoría pide baselines matched por `trend_regime` + `volatility_regime`. En el mercado argentino, la combinación BULL+LOW_VOL es común, pero BEAR+HIGH_VOL tiene muy pocas observaciones. ¿Qué hacer cuando el pool de control es insuficiente (< 5 observaciones)?

Opciones:
- Descartar ese evento (reduce muestra)
- Usar solo trend_regime (simplifica)
- Flag como "insuficiente" en el reporte

**¿Qué criterio preferís?**

---

## 5. Costos de futuros vs sensibilidad (sección 7)

La auditoría dice que cambiar el modelo de costos no es un backtest de futuros. Estoy de acuerdo. Pero para el paper trading real, ¿esperás que implementemos:

- (a) Conexión real a ROFEX API para precios de futuros?
- (b) Simulación de futuros desde precios cash + basis estimado?
- (c) Dejar el paper trader como está (señal cash, costos futuros) y etiquetarlo como "low-cost sensitivity analysis"?

La pregunta es: **¿cuál es el mínimo acceptable para considerar el paper trading "válido"?**

---

## 6. Parameter neighborhood (sección 9.4)

Para EXP-05, proponés testear z-score = -1.75, -2.00, -2.25. Pero el z-score se calcula sobre una ventana de 60d. Si cambiamos el threshold, ¿debemos mantener la ventana fija o también testear 40d/80d?

**¿El parameter neighborhood es solo sobre el threshold, o también sobre ventanas de cálculo?**

---

## 7. Clean cache antes de rerun

La auditoría pide "clear or validate all cached source data" antes de rerun. ¿Querés que borremos todo `data/raw/` y redescarguemos, o basta con agregar metadata de cobertura y validar que los rangos pedidos están cubiertos?

**¿Delete + fresh download, o validate + refresh?**

---

## 8. Documentación contradictoria (sección 11.4)

`AGENTS.md` actualmente dice que todo está ❌ no implementado. La auditoría pide sincronizar. ¿Querés que `AGENTS.md` refleje el estado exacto post-cada commit (generado automáticamente), o es suficiente actualizarlo manualmente al final de cada milestone?

**¿Automático desde metadata.json, o manual al cierre de milestone?**
