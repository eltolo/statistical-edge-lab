# Statistical Edge Lab

Laboratorio reusable para evaluar si un evento de mercado definido explícitamente produce un edge estadístico real, repetible y tradeable.

**⚠️ Esto NO es un buscador automático de patrones.** El humano define qué testear; el lab responde si funciona.

---

## Resultados finales (Pipeline Audit 4)

5 experimentos ejecutados sobre 8 acciones argentinas (2015-2026) con pipeline corregido:
- adjusted OHLC → USD
- Benchmark dolarizado para regímenes
- Feature range validation
- Primary horizon forzado
- net_return_pct como métrica formal
- Holdout + validation en decision engine
- Baseline coverage threshold

| Exp | Eventos | Net Full Sample | Net Validation | Net Holdout | Decisión |
|:---:|:-------:|:---------------:|:--------------:|:-----------:|:--------:|
| EXP-01 | 1,533 | -1.68% | -2.18% | -0.52% | ❌ REJECTED |
| EXP-02 | 455 | -2.07% | -1.85% | -1.44% | ❌ REJECTED |
| EXP-03 | 680 | +6.31% | -4.03% | +1.84% | ❌ REJECTED |
| EXP-04 | 210 | -2.16% | -9.36% | +1.80% | ❌ REJECTED |
| EXP-05 | 939 | -0.13% | -0.72% | +3.99% | ❌ REJECTED |

**5/5 REJECTED.** Ningún edge sobrevive costos BYMA (1.96% RT) con pipeline auditado.

### Hallazgos clave

1. **BYMA equities no son tradeables para estrategias de 1-20 días.** El costo de 1.96% RT destruye cualquier edge de 1-2%.
2. **EXP-05 (Extreme Decline) tiene señal en holdout** (+3.99% neto 10d) pero full sample negativo. Posible investigación futura con hipótesis refinada.
3. **EXP-03 y EXP-04 tenían configs inválidas** en versiones anteriores (atr_percentile 25 vs 0.25, distance_to_high al revés). Corregido.
4. **Resultados anteriores (RESEARCH, CANDIDATE) quedan SUPERSEDED** por el pipeline Audit 4.
5. **Futuros ROFEX** son la única vía tradeable, pero requieren datos de contrato reales y un implementation aparte.

### Lección principal

El lab funciona correctamente. Produce REJECTED cuando no hay edge. Eso no es fracaso — es el propósito del sistema.

---

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

```bash
# Ejecutar experimento
python run_experiment.py \
  --event config/events/exp_001.yaml \
  --universe config/universe.yaml

# Listar experimentos completados
python run_experiment.py --list

# Ver reporte
python run_experiment.py --show exp_001
```

## Tests

```bash
python -m pytest tests/ -v
```

---

## Arquitectura

```
src/
├── data_loader.py         # Carga Yahoo Finance + cache con metadata
├── data_validator.py      # 7 checks de calidad
├── currency_adjustment.py # ARS→USD via CCL
├── forward_returns.py     # Retornos forward + MFE/MAE
├── feature_engine.py      # Indicadores técnicos
├── event_detector.py      # Detección + cooldown por sesiones
├── regime_detector.py     # BULL/BEAR + LOW/NORMAL/HIGH_VOL
├── baseline_comparator.py # 3 baselines + exact match trend+vol
├── cost_model.py          # Costos Argentina/USA/ROFEX
├── robustness.py          # Bootstrap, LOO, profit concentration
├── validator.py           # Split temporal + boundary purge
└── report_generator.py    # Reportes + make_decision
```

## Configuración

- `config/universe.yaml` — Targets (8 argentinas) + References (SPY, QQQ, EWZ, ARGT)
- `config/costs.yaml` — Argentina 1.96% RT, USA 0.22% RT, ROFEX 0.46% RT
- `config/events/exp_*.yaml` — 5 experimentos con condiciones en formato lista

Ver `statistical_edge_lab_spec.md` para la especificación completa.
