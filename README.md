# Statistical Edge Lab

Laboratorio reusable para evaluar si un evento de mercado definido explícitamente produce un edge estadístico real, repetible y tradeable.

**⚠️ Esto NO es un buscador automático de patrones.** El humano define qué testear; el lab responde si funciona.

---

## Resultados finales (post-auditoría, pipeline corregido)

5 experimentos ejecutados sobre 8 acciones argentinas (2015-2026) con datos frescos, pipeline auditado.

| Exp | Familia | Eventos | Bruto (mejor H) | Neto | Cobertura Baseline | Decisión |
|:---:|:--------|:-------:|:---------------:|:----:|:------------------:|:--------:|
| EXP-01 | Moderate Pullback | 287 | 10d +0.55% | -1.41% | 100% | ❌ REJECTED |
| EXP-02 | Pullback With Volume | 74 | 5d +1.50% | -0.46% | 100% | ❌ REJECTED |
| EXP-03 | Volatility Compression | 1,024 | 20d +2.48% | +0.52% | 6.5% | 🔬 RESEARCH |
| EXP-04 | Breakout From Compression | 285 | 20d +6.14% | +4.18% | 98.2% | 🔬 RESEARCH |
| EXP-05 | Extreme Decline | 233 | 5d +1.66% | -0.30% | 99.2% | ❌ REJECTED |

Costos: Argentina 1.96% round-trip (0.98%/side).

### Hallazgos clave

1. **Ningún edge sobrevive costos de acciones argentinas (1.96% RT).** EXP-01, 02 y 05 son REJECTED.
2. **EXP-04 (Breakout) tiene el mejor retorno bruto** (+6.14% a 20d) pero alta concentración en CEPU.BA (39% del profit).
3. **EXP-03 (Compresión) tiene 1,024 eventos** pero cobertura baseline 6.5% — el match exacto trend+vol es insuficiente para CANDIDATE.
4. **Futuros ROFEX cambiarían el panorama** (0.46% RT vs 1.96%) pero requieren datos de contrato reales (Q5).
5. **100% de cobertura baseline** en EXP-01/02/04/05 gracias al matching exacto trend+vol.

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
