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
| `src/data_loader.py` | 1 | ❌ |
| `src/data_validator.py` | 1 | ❌ |
| `src/currency_adjustment.py` | 1 | ❌ |
| `src/forward_returns.py` | 1 | ❌ |
| `src/feature_engine.py` | 2 | ❌ |
| `src/event_detector.py` | 2 | ❌ |
| `src/regime_detector.py` | 3 | ❌ |
| `src/baseline_comparator.py` | 3 | ❌ |
| `src/cost_model.py` | 3 | ❌ |
| `src/robustness.py` | 4 | ❌ |
| `src/validator.py` | 4 | ❌ |
| `src/report_generator.py` | 5 | ❌ |
| `run_experiment.py` | 5 | ❌ |
| Tests | 5 | ❌ |
| EXP-001 a EXP-005 | 5 | ❌ |

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
