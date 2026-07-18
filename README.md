# Statistical Edge Lab

A reusable hypothesis-testing framework for market events.

**This is NOT an automatic pattern finder or strategy optimizer.**  
A human defines **what** to test; the lab answers **whether it works**.

## Core question

> When a defined event occurs, do future returns improve relative to comparable
> market conditions, after transaction costs and out-of-sample validation?

## Quick start

```bash
pip install -r requirements.txt

# Run experiment 1: Moderate Pullback
python run_experiment.py \
  --event config/events/exp_001.yaml \
  --universe config/universe.yaml

# View the report
cat results/exp_001/summary.md
```

## Lab output

Each experiment produces a decision: **REJECTED** | **RESEARCH** | **CANDIDATE**

See `AGENTS.md` and `statistical_edge_lab_spec.md` for the full specification.

## 5 initial experiments

| ID | Name | Event |
|----|------|-------|
| EXP-001 | Moderate Pullback | -3% pullback in uptrend, price above SMA200 |
| EXP-002 | Pullback With Volume | EXP-001 + volume > 1.5x avg |
| EXP-003 | Volatility Compression | ATR < 25th percentile, price near 60d high |
| EXP-004 | Breakout From Compression | EXP-003 + close above 20d high + volume |
| EXP-005 | Extreme Decline | 3d return < -2σ, market not bear |

## Architecture

```
├── config/          # YAML configs (universe, costs, events)
├── src/             # Python modules (12 modules, 5 phases)
├── data/            # Raw/processed data cache
├── experiments/     # Human-defined experiment configs
├── results/         # Generated reports (summary.md, metrics, charts)
├── tests/           # pytest suite (40 tests)
├── run_experiment.py
└── statistical_edge_lab_spec.md  # Full specification
```

## Status

✅ EXP-001 complete — 859 events, decision: RESEARCH  
⬜ EXP-002 through EXP-005 pending
