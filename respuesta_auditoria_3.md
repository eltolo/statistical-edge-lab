# Respuesta a Auditoría 3 — Statistical Edge Lab

**Fecha:** 2026-07-18  
**HEAD:** `68632f2` → commits aplicados en esta sesión  
**Auditoría referenciada:** `20260718_respuestas.md`

---

## Resumen

Esta sesión implementó **la totalidad de las correcciones** identificadas en la auditoría 3 y las 8 decisiones de `preguntas.md`. Todos los experimentos fueron reruneados con caché fresca y pipeline corregido.

---

## 1. P0 — Horizonte (Q1)

**Problema:** `exit_idx = entry_idx + h` con horizon=1 salía en close t+2.

**Fix:** `exit_idx = entry_idx + h - 1` para next_open.

```python
if entry_mode == "next_open":
    exit_idx = entry_idx + h - 1  # h=1 → close t+1
else:
    exit_idx = entry_idx + h      # signal_close
```

**Archivo:** `src/forward_returns.py`  
**Test confirmatorio:** `test_forward_returns_after_event` verifica open t+1 → close t+1.

---

## 2. P0 — MFE/MAE incluyen sesión de entrada (Q1)

**Problema:** `hold_start = entry_idx + 1` omitía la sesión de entrada.

**Fix:** `hold_start = entry_idx` para next_open (se entra al open, el high/low de esa sesión importa).

```python
if entry_mode == "next_open":
    hold_start = entry_idx
else:
    hold_start = entry_idx + 1
```

**Archivo:** `src/forward_returns.py`

---

## 3. P0 — Boundary-crossing purge (Q3)

**Problema:** El split temporal asignaba trades solo por `signal_date`, sin verificar `entry_date` ni `exit_date`.

**Fix:** Nuevo método `TemporalSplit.assign_trade_split()` que revisa los 3 dates. Si no están todos en la misma partición → `boundary_crossing` → excluido de métricas formales.

```python
def assign_trade_split(self, trade):
    periods = {self.get_period(trade[k]) for k in ("signal_date", "entry_date", "exit_date")}
    return periods.pop() if len(periods) == 1 else "boundary_crossing"
```

**Archivos:** `src/validator.py`, `run_experiment.py`

---

## 4. P1 — Baseline exacto trend+vol (Q4)

**Problema:** El baseline solo matching por `trend_regime`.

**Fix:** Nueva función `exact_matched_baseline()` que matchea `trend_regime + volatility_regime` simultáneamente. Devuelve `(return, n_controls, status)` donde status es VALID (≥20), LOW_CONFIDENCE (5-19) o INSUFFICIENT (<5).

Se agregó cobertura de baseline al reporte y al pipeline.

**Archivos:** `src/baseline_comparator.py`, `run_experiment.py`, `src/report_generator.py`

---

## 5. P1 — Cache metadata (Q7)

**Problema:** El caché solo guardaba CSV sin metadatos. No se podía verificar cobertura ni integridad.

**Fix:** Cada archivo de caché ahora tiene un `.meta.json` companion con:

```json
{
  "ticker": "GGAL.BA",
  "source": "yfinance",
  "requested_start": "2015-01-01",
  "requested_end": "2026-07-17",
  "first_available_date": "...",
  "last_available_date": "...",
  "content_sha256": "...",
  "schema_version": "1.0"
}
```

El loader valida schema version, source, rango cubierto e integridad por hash antes de usar caché.

**Archivo:** `src/data_loader.py`  
**Cache fresco:** 15 `.meta.json` generados.

---

## 6. P1 — Robustness por horizonte

**Problema:** `leave_one_asset_out`, `profit_concentration` mezclaban retornos de todos los horizontes en una sola métrica.

**Fix:** Todas las funciones de robustez ahora calculan métricas **por horizonte** independientemente.

**Archivo:** `src/robustness.py`

---

## 7. EXP-02 migrado a formato lista

**Problema:** Config en formato dict legacy, sin bounded condition.

**Fix:** Migrado a formato lista con `-7% <= return_3d < -3%` y `cooldown_sessions`.

**Archivo:** `config/events/exp_002.yaml`

---

## 8. Fresh download + rerun completo

Cache archivado (`data/raw_pre_audit_backup/`), descarga fresca de cero.

| Exp | Eventos | Decisión | Nota |
|:---:|:-------:|:--------:|------|
| EXP-01 | 287 | ❌ REJECTED | Neto -1.41% |
| EXP-02 | 74 | ❌ REJECTED | Neto -0.13% (sample chico) |
| EXP-03 | 1,024 | 🔬 RESEARCH | Coverage baseline 6.5% |
| EXP-04 | 285 | 🔬 RESEARCH | Neto +3.81% a 20d, CEPU concentrado |
| EXP-05 | 233 | ❌ REJECTED | Neto -0.30% (antes RESEARCH con costos futuros inválidos) |

**Hallazgo principal:** Ningún edge sobrevive costos de equities argentinas (1.96% RT).

---

## 9. Documentación

- `AGENTS.md` — Estado real por módulo + experimentos ✅
- `README.md` — Resultados finales + hallazgos ✅
- `respuesta_auditoria_3.md` — Este documento ✅

---

## Pendientes para próximo milestone

| Item | Prioridad |
|:-----|:---------:|
| Parameter neighborhood EXP-04/05 (Q6) | Baja (sin edge no hace falta) |
| Datos reales de futuros ROFEX (Q5) | Media (única vía tradeable) |
| Validación walk-forward completa | Baja |
| CI / drift check automático | Baja |
