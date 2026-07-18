# 20260718 — Respuestas y estado de auditoría

## Revisión del repositorio

El HEAD actual es `68632f2`. Desde la revisión anterior en `d86e47a` hubo solo dos commits:

- `e19af20`: agrega una nota aclaratoria en la auditoría.
- `68632f2`: agrega `HANDOFF.md`.

No hubo cambios en código, tests ni resultados desde `d86e47a`.

---

## Hallazgos críticos

### P0 — El horizonte sigue incorrecto

`calculate_forward_returns()` todavía utiliza:

```python
exit_idx = entry_idx + h
```

Por lo tanto, con `horizon=1` entra en `open t+1` y sale en `close t+2`, una sesión más tarde que la semántica acordada.

Debe ser:

```python
exit_idx = entry_idx + h - 1
```

También debe ajustarse el chequeo inicial de disponibilidad de datos.

Esto contradice `HANDOFF.md`, que afirma que el horizonte next-open fue verificado.

---

### P0 — MFE y MAE siguen excluyendo la sesión de entrada

El código comienza el tramo en:

```python
hold_start = entry_idx + 1
```

Eso omite el máximo y mínimo de la misma jornada en que se compra al open.

Para una operación que entra al open, el recorrido válido comienza en:

```python
hold_start = entry_idx
```

Con `horizon=1`, después de corregir el exit, el código actual produciría una ventana vacía y MFE/MAE igual a cero.

---

### P0 — El split temporal sigue teniendo leakage

La partición se asigna únicamente por la fecha de señal:

```python
filtered = [d for d in dates if splitter.get_period(d) == split_name]
```

Luego se recalcula el trade completo sin comprobar que `entry_date` y `exit_date` permanezcan dentro de la misma partición.

Un trade iniciado en discovery todavía puede consumir precios de validation.

Debe asignarse el split después de construir la tabla canónica de trades, verificando conjuntamente:

```text
signal_date
entry_date
exit_date
```

Los trades que crucen el borde deben clasificarse como:

```text
boundary_crossing
```

y excluirse de las métricas formales.

---

### P1 — El baseline todavía no cumple la decisión acordada

El pipeline sigue agregando un único valor llamado `regime_conditioned`, sin exponer:

- matching exacto por `trend_regime + volatility_regime`;
- tamaño del pool de controles;
- estado `VALID`, `LOW_CONFIDENCE` o `INSUFFICIENT`;
- cobertura del baseline;
- fallback diagnóstico separado.

Además, el decision engine recibe métricas generales y robustez, pero no recibe la cobertura de baselines como restricción explícita.

---

### P1 — Los resultados no son reproducibles desde GitHub

La carpeta `results/` contiene únicamente `.gitkeep`.

No están versionados:

```text
metadata.json
metrics.csv
summary.md
trades.parquet o trades.csv
split diagnostics
cache hashes
```

Sin embargo, el README publica decisiones y métricas específicas para cuatro experimentos.

Actualmente esas cifras no pueden auditarse ni reproducirse usando únicamente el repositorio.

Esto es especialmente importante porque los resultados actuales fueron calculados antes de corregir:

- horizonte;
- MFE/MAE;
- purge de split;
- baseline combinado.

Por lo tanto, las decisiones `CANDIDATE` del README deben considerarse provisionales y no vigentes.

---

### P1 — Documentación desalineada

`HANDOFF.md` indica que `preguntas.md` sigue esperando respuestas y que no deben implementarse cambios bajo supuestos.

Sin embargo, las respuestas definitivas preparadas no fueron incorporadas todavía a `main`.

También existe una contradicción interna:

- `HANDOFF.md`: EXP-05 futuros figura como `RESEARCH`.
- `README.md`: EXP-05 futuros figura como `CANDIDATE`.

---

## Tests

El repositorio continúa teniendo un único archivo principal de tests:

```text
tests/test_statistical_edge_lab.py
```

No se ejecutó `pytest` durante esta revisión.

Todavía faltan tests específicos para:

```text
horizon=1: open t+1 → close t+1
MFE/MAE incluyen la jornada de entrada
trade que cruza split → boundary_crossing
baseline con pools de 4, 5, 19 y 20 controles
cobertura mínima del baseline
cache incompleto o incompatible
```

Tampoco se observa un workflow de CI en la raíz publicada del repositorio.

---

## Estado real del proyecto

El proyecto no está listo para un rerun oficial.

Los resultados históricos sirven como exploración, pero no deben utilizarse para decidir paper trading hasta completar las correcciones y repetir todos los experimentos.

---

## Próximos pasos concretos

Implementar en este orden:

```text
1. Reemplazar preguntas.md por la versión respondida.
2. Corregir exit_idx = entry_idx + horizon - 1.
3. Cambiar MFE/MAE para comenzar en entry_idx.
4. Construir una tabla canónica de trades una sola vez.
5. Asignar el split usando señal, entrada y salida.
6. Implementar baseline exacto trend + volatility.
7. Agregar estado y cobertura de controles.
8. Limitar a RESEARCH cuando la cobertura sea insuficiente.
9. Implementar metadata y validación del cache.
10. Vaciar o archivar el cache previo.
11. Ejecutar todos los tests.
12. Hacer un rerun limpio de EXP-01, EXP-03, EXP-04 y EXP-05.
13. Versionar artefactos livianos de auditoría.
14. Actualizar README, AGENTS y HANDOFF únicamente después del rerun.
```

---

## Prioridad inmediata

No ejecutar todavía el parameter neighborhood de EXP-05.

Primero debe corregirse el motor común. De lo contrario, se estarían explorando parámetros sobre retornos, horizontes y splits defectuosos.
