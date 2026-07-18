# Statistical Edge Lab

> **Documento maestro del proyecto.** La especificación técnica detallada está en
> `statistical_edge_lab_spec.md`. Este archivo es el entry point operativo.

Laboratorio reusable de hipótesis para evaluar si un **evento de mercado definido explícitamente**
produce un edge estadístico real, repetible y tradeable.

**⚠️ Esto NO es un buscador automático de patrones ni un optimizador de estrategias.**
No escanea combinaciones, no hace feature engineering automático, no optimiza parámetros.
El humano define **qué** testear; el lab responde **si funciona**.

---

## Pregunta canónica

> When a defined event occurs, do future returns improve relative to comparable
> market conditions, after transaction costs and out-of-sample validation?

---

## Decisiones posibles

| Decisión | Significado |
|----------|-------------|
| **REJECTED** | No hay evidencia suficiente de edge |
| **RESEARCH** | Resultado interesante pero evidencia insuficiente |
| **CANDIDATE** | Edge robusto, justifica construir estrategia completa |
| **PAPER_READY** | Solo tras pasar validaciones adicionales de estrategia completa |

El lab asigna hasta CANDIDATE. PAPER_READY lo asigna el pipeline de estrategias.

---

## Estado actual del código

| Módulo | Fase | Estado |
|--------|------|--------|
| `src/data_loader.py` | 1 — Carga | ✅ + cache metadata + CCL proxy |
| `src/data_validator.py` | 1 — Validación | ✅ 7 checks + DataQualityReport |
| `src/currency_adjustment.py` | 1 — Moneda | ✅ ARS→USD via CCL, fail si falta |
| `src/forward_returns.py` | 1 — Retornos | ✅ next_open default, MFE/MAE desde high/low |
| `src/feature_engine.py` | 2 — Features | ✅ SMA/RSI/ATR/zscore/BB/MACD/compute_all_features |
| `src/event_detector.py` | 2 — Eventos | ✅ condiciones lista, cooldown por sesiones |
| `src/regime_detector.py` | 3 — Regímenes | ✅ BULL/BEAR/NEUTRAL + LOW/NORMAL/HIGH_VOL |
| `src/baseline_comparator.py` | 3 — Baselines | ✅ exact trend+vol match, pool status (Q4) |
| `src/cost_model.py` | 3 — Costos | ✅ Argentina 1.96% RT, USA, ROFEX + break-even |
| `src/robustness.py` | 4 — Robustez | ✅ bootstrap/LOO/profit conc. por horizonte |
| `src/validator.py` | 4 — Split | ✅ temporal cronológico + boundary-crossing purge (Q3) |
| `src/report_generator.py` | 5 — Reportes | ✅ summary.md + make_decision + coverage |
| `run_experiment.py` | 5 — CLI | ✅ pipeline 13 pasos + --list/--show |
| Tests | 5 | ✅ 41 tests (pytest) |

## Experimentos ejecutados (Pipeline Audit 4 completo)

| Exp | Eventos | Net Full Sample | Net Holdout | Decisión | Nota |
|:---:|:-------:|:---------------:|:-----------:|:--------:|------|
| EXP-01: Moderate Pullback | 1,533 | -1.68% | -0.52% | ❌ REJECTED | Primary 10d, todas las splits negativas |
| EXP-02: Pullback With Volume | 455 | -2.07% | -1.44% | ❌ REJECTED | Primary 1d, sample chico en splits |
| EXP-03: Volatility Compression | 680 | +6.31% | +1.84% | ❌ REJECTED | Validation -4.03% (no consistente) |
| EXP-04: Breakout From Compression | 210 | -2.16% | +1.80% | ❌ REJECTED | Solo 5/6 eventos en validation/holdout |
| EXP-05: Extreme Decline | 939 | -0.13% | +3.99% | ❌ REJECTED | Full sample negativo, holdout sugiere investigación |

** hallazgo principal:** Ningún edge sobrevive costos BYMA (1.96% RT) con pipeline corregido. El lab produce 5/5 REJECTED, que es el resultado correcto.

---

## Cómo usar

```bash
cd ~/shared/proyectos/strategies/1-laboratorio

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar experimento
python run_experiment.py \
  --event config/events/exp_001.yaml \
  --universe config/universe.yaml

# Ver resultado
cat results/exp_001/summary.md
```

---

## Arquitectura (spec §5)

```
statistical_edge_lab/
├── config/
│   ├── universe.yaml        # activos, benchmark, fechas
│   ├── costs.yaml           # costos Argentina
│   ├── benchmarks.yaml      # benchmarks
│   └── events/
│       ├── exp_001.yaml     # Moderate Pullback
│       ├── exp_002.yaml     # Pullback With Volume
│       ├── exp_003.yaml     # Volatility Compression
│       ├── exp_004.yaml     # Breakout From Compression
│       └── exp_005.yaml     # Extreme Decline
├── src/
│   ├── data_loader.py       # F1: carga yahoo/duckdb
│   ├── data_validator.py    # F1: calidad de datos
│   ├── currency_adjustment.py # F1: MEP/CCL
│   ├── forward_returns.py   # F1: retornos forward + MFE/MAE
│   ├── feature_engine.py    # F2: indicadores técnicos
│   ├── event_detector.py    # F2: detección + cooldown
│   ├── regime_detector.py   # F3: BULL/BEAR/NEUTRAL + vol
│   ├── baseline_comparator.py # F3: 3 baselines
│   ├── cost_model.py        # F3: costos Argentina + break-even
│   ├── robustness.py        # F4: bootstrap, leave-one-out
│   ├── validator.py         # F4: split temporal
│   └── report_generator.py  # F5: reportes
├── data/
│   ├── raw/                 # datos descargados
│   ├── processed/           # datos limpios
│   └── metadata/
├── experiments/             # configs de experimentos
├── results/                 # outputs
├── tests/                   # pytest
├── run_experiment.py        # CLI
└── requirements.txt
```

Ver `statistical_edge_lab_spec.md` para la especificación completa.
