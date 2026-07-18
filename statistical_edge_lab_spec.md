# Project: Statistical Edge Lab

## 1. Objective

Build a reusable research laboratory to evaluate whether a market event produces a real, repeatable, and tradable statistical edge.

The system must not automatically search through thousands of patterns or optimize complete trading strategies.

It must answer one specific question:

> When a defined event occurs, do future returns improve relative to comparable market conditions, after transaction costs and out-of-sample validation?

The main output must be one of the following decisions:

- `REJECTED`: there is no sufficient evidence of an edge.
- `RESEARCH`: the result is interesting, but the evidence is insufficient.
- `CANDIDATE`: the edge is robust enough to justify building a complete strategy.
- `PAPER_READY`: the strategy has passed the additional requirements needed for paper trading.

---

## 2. Design Principle

The system must try to reject each hypothesis.

It must not search for the parameter combination with the highest Sharpe ratio, nor classify a rule as valid simply because it performed well historically.

Every result must be compared against:

1. The asset's unconditional return.
2. The asset's return under the same market regime.
3. The appropriate benchmark.
4. Realistic execution costs.
5. Out-of-sample data.

A signal has value only if it produces an incremental improvement over those references.

---

## 3. MVP Scope

### Frequency

Use daily data only.

Do not implement:

- Intraday analysis.
- Order book analysis.
- Machine learning.
- Neural networks.
- Reinforcement learning.
- Visual chart-pattern recognition.
- Massive automatic optimization.
- Automatic strategy generation.

### Initial Universe

Liquid Argentine equities:

```text
GGAL
YPFD
PAMP
BBAR
BMA
TGSU2
CEPU
TXAR
```

Reference assets:

```text
SPY
QQQ
EWZ
ARGT
```

The universe must be configurable through YAML.

### Currency

For Argentine assets, calculate:

- Returns in ARS.
- Returns adjusted by MEP or CCL.
- Returns relative to the selected index or benchmark.

The main evaluation must be performed in hard currency.

---

## 4. Event Families

Implement only the following three event families.

### 4.1 Pullback Within an Uptrend

Example event:

```yaml
name: pullback_in_uptrend
conditions:
  close_above_sma_200: true
  return_60d_min: 0.10
  return_3d_max: -0.04
  volume_ratio_min: 1.0
```

Objective:

Evaluate whether a short-term decline inside an established positive trend creates a favorable entry opportunity.

### 4.2 Breakout After Volatility Compression

Example event:

```yaml
name: compression_breakout
conditions:
  atr_percentile_60d_max: 25
  distance_to_high_60d_max: 0.03
  close_breaks_high_20d: true
  volume_ratio_min: 1.5
```

Objective:

Evaluate whether volatility expansion following a compression phase produces price continuation.

### 4.3 Reversal After an Extreme Move

Example event:

```yaml
name: extreme_reversal
conditions:
  return_3d_max: -0.08
  zscore_return_3d_max: -2.0
  distance_from_sma_20_max: -0.07
  market_regime_not_bearish: true
```

Objective:

Evaluate whether an abnormal short-term decline produces a measurable mean-reversion effect.

Do not add new event families until these three have been implemented and validated.

---

## 5. Architecture

```text
statistical_edge_lab/
├── config/
│   ├── universe.yaml
│   ├── costs.yaml
│   ├── benchmarks.yaml
│   └── events/
├── data/
│   ├── raw/
│   ├── processed/
│   └── metadata/
├── src/
│   ├── data_loader.py
│   ├── data_validator.py
│   ├── currency_adjustment.py
│   ├── feature_engine.py
│   ├── event_detector.py
│   ├── regime_detector.py
│   ├── forward_returns.py
│   ├── baseline_comparator.py
│   ├── cost_model.py
│   ├── robustness.py
│   ├── validator.py
│   └── report_generator.py
├── experiments/
├── results/
├── tests/
└── run_experiment.py
```

Each module must be independent, testable, and reusable.

Do not duplicate ticker-specific or event-specific logic.

---

## 6. Execution Flow

```text
1. Load data.
2. Validate data quality.
3. Adjust returns for currency.
4. Calculate features.
5. Detect events.
6. Remove overlapping events.
7. Calculate forward returns.
8. Calculate MFE and MAE.
9. Compare results against baselines.
10. Deduct transaction costs.
11. Split data into in-sample and out-of-sample periods.
12. Run robustness tests.
13. Generate a decision and report.
```

---

## 7. Required Data

For each asset:

```text
date
open
high
low
close
adjusted_close
volume
```

Additional data:

```text
Daily MEP or CCL exchange rate
Daily benchmark data
Market regime classification
```

### Mandatory Data Checks

Detect and report:

- Duplicate dates.
- Missing values.
- Zero or negative prices.
- Abnormal price jumps.
- Periods with no trading volume.
- Invalid OHLC relationships.
- Unadjusted corporate actions.
- Missing exchange-rate observations.

The experiment must stop when critical data errors are detected.

---

## 8. Event Definition

Each event must be declared through configuration.

Example:

```yaml
event:
  id: pullback_v1
  family: pullback
  description: Short-term pullback within an uptrend

  conditions:
    close_vs_sma_200:
      operator: ">"
      value: 1.0

    return_60d:
      operator: ">"
      value: 0.10

    return_3d:
      operator: "<"
      value: -0.04

    volume_ratio_20d:
      operator: ">"
      value: 1.0

  cooldown_days: 10

  forward_horizons:
    - 1
    - 3
    - 5
    - 10
    - 20
```

Do not hardcode event parameters in the application code.

---

## 9. Event Independence

Events that occur close together must not be treated as independent observations.

Apply a configurable exclusion period:

```text
cooldown_days = maximum evaluated forward horizon
```

When multiple signals occur inside the exclusion period, keep only the first event.

The report must include:

- Raw signal count.
- Independent event count.
- Percentage of signals removed because of overlap.

---

## 10. Mandatory Metrics

For each forward horizon, calculate:

```text
Number of events
Mean return
Median return
Standard deviation
25th percentile
75th percentile
Win rate
Average gain
Average loss
Profit factor
Expected value
Maximum Favorable Excursion (MFE)
Maximum Adverse Excursion (MAE)
Worst result
Best result
```

Also calculate:

```text
Incremental return versus baseline
Net return after costs
Bootstrap confidence interval
Percentage of assets with positive results
Percentage of subperiods with positive results
```

The median and confidence interval must receive more weight than the isolated mean return.

---

## 11. Baselines

Each event must be evaluated against three baselines.

### Baseline 1: Unconditional Return

The average return of the asset for the same forward horizon using all eligible dates.

### Baseline 2: Regime-Conditioned Return

The average return of the asset during dates with the same market regime, without requiring the event.

### Baseline 3: Benchmark Return

The benchmark return over the same dates and forward horizon.

Primary metric:

```text
incremental_edge =
    event_return
    - same_regime_baseline_return
    - transaction_costs
```

Do not evaluate an event only by its absolute forward return.

---

## 12. Market Regime

Use a simple and explainable classification for the MVP.

```text
BULL:
benchmark > SMA200
and SMA200 slope > 0

BEAR:
benchmark < SMA200
and SMA200 slope < 0

NEUTRAL:
all remaining cases
```

Add a second regime dimension:

```text
LOW_VOL
NORMAL_VOL
HIGH_VOL
```

Define volatility regimes using historical percentiles of ATR or realized volatility.

Do not use HMMs or clustering in the MVP.

---

## 13. Transaction Costs

The `costs.yaml` file must support:

```yaml
argentina:
  commission_per_side: 0.007
  market_fees_per_side: 0.0008
  estimated_slippage_per_side: 0.002
  minimum_total_roundtrip: 0.015
```

Deduct the full round-trip cost from every event return.

Also calculate:

```text
break_even_cost
```

Definition:

> The maximum round-trip transaction cost that would completely eliminate the observed edge.

A candidate must have sufficient margin between gross edge and estimated execution cost.

---

## 14. Temporal Split

Use chronological splits only. Never use random train-test splits.

Initial configuration:

```text
60% discovery
20% validation
20% final holdout
```

Rules:

- `discovery`: may be used to define or reasonably adjust the hypothesis.
- `validation`: may be used to decide whether research should continue.
- `holdout`: must be evaluated only once for the final decision.

Do not modify parameters after observing holdout results.

Store the following metadata:

```text
Hypothesis creation date
Original parameters
Parameter changes
Number of tested variants
Holdout opening date
```

---

## 15. Robustness Tests

Every candidate must pass the following tests.

### 15.1 Parameter Neighborhood

Test nearby parameter values.

Example:

```text
return_3d < -3%
return_3d < -4%
return_3d < -5%
```

Do not approve a result that works only at one exact parameter value.

### 15.2 Leave-One-Asset-Out

Recalculate the result while excluding one ticker at a time.

The result must not depend on a single asset.

### 15.3 Leave-One-Year-Out

Recalculate the result while excluding one calendar year at a time.

The result must not depend on one exceptional market period.

### 15.4 Profit Concentration

Measure the percentage of total profit explained by:

```text
Best trade
Best three trades
Best-performing asset
Best-performing year
```

### 15.5 Bootstrap

Calculate confidence intervals by resampling independent events.

---

## 16. Decision Criteria

### REJECTED

Assign `REJECTED` when any of the following conditions is true:

```text
Fewer than 40 independent events
Net median return <= 0
Incremental edge <= 0
Negative final holdout result
Result depends materially on one asset or period
Transaction costs consume more than 70% of gross edge
```

### RESEARCH

Assign `RESEARCH` when:

```text
The signal is positive
But the number of observations is insufficient
Or stability is insufficient
Or the confidence interval still includes zero by a wide margin
```

### CANDIDATE

Minimum requirements:

```text
At least 60 independent events
Positive net median return
Positive incremental edge
Positive final holdout result
At least 60% of assets show positive results
At least 60% of subperiods show positive results
Nearby parameter values remain valid
No single trade explains more than 20% of total profit
Break-even cost >= 1.5 times estimated transaction cost
```

### PAPER_READY

The event laboratory must not assign `PAPER_READY` directly.

This status is available only after the event has been converted into a complete trading strategy and has passed:

```text
Executable entry rules
Exit rules
Stop-loss or explicit maximum risk
Position sizing
Portfolio-level backtest
Walk-forward validation
Liquidity and transaction-cost validation
Paper trading
```

---

## 17. Report Output

Generate:

```text
results/<experiment_id>/
├── summary.md
├── metrics.csv
├── events.csv
├── robustness.csv
├── metadata.json
└── charts/
```

### `summary.md`

Must include:

```text
Hypothesis
Universe
Evaluation period
Number of events
Results by forward horizon
Results by asset
Results by market regime
Baseline comparison
Transaction costs
Robustness results
Known limitations
Decision
Reason for decision
```

Avoid promotional language.

Do not use phrases such as:

```text
Winning strategy
Highly profitable pattern
Exceptional opportunity
```

Use cautious statistical language.

---

## 18. Initial Experiments

Implement only the following experiments.

### EXP-001: Moderate Pullback

```text
Positive 60-day trend
Price above SMA200
Three-day return between -3% and -7%
```

### EXP-002: Pullback With Volume

```text
All EXP-001 conditions
Volume greater than 1.5 times the 20-day average
```

### EXP-003: Volatility Compression

```text
ATR percentile below 25
Price less than 5% below the 60-day high
```

### EXP-004: Breakout From Compression

```text
All EXP-003 conditions
Close above the previous 20-day high
Relative volume greater than 1.5
```

### EXP-005: Extreme Decline

```text
Three-day return below -2 standard deviations
Market regime is not BEAR
```

Do not create additional experiments until these five have been completed and reviewed.

---

## 19. Technical Constraints

- Python 3.11 or newer.
- Type hints required.
- YAML configuration.
- Reproducible results.
- Fixed random seed.
- Notebooks must not be the system core.
- Pandas or Polars are allowed.
- Pytest is mandatory.
- Structured logging.
- Avoid unnecessary dependencies.
- No ticker-specific logic.
- No hardcoded event parameters.
- Every experiment must have a unique identifier.
- Every run must store its complete configuration and code version.
- Avoid look-ahead bias.
- Use only information available at the event date.
- Forward returns must begin after the event has been fully confirmed.

---

## 20. Minimum Test Coverage

Create tests for:

```text
Forward-return calculation
Currency conversion
Event detection
Overlapping-event removal
MFE and MAE calculation
Transaction-cost application
Baseline comparison
Chronological split
Market-regime classification
Decision generation
Look-ahead prevention
```

Include small synthetic datasets with known expected results.

---

## 21. Implementation Order

### Phase 1

```text
Data loader
Data validation
Currency adjustment
Forward returns
```

### Phase 2

```text
Configurable event detector
Cooldown handling
MFE and MAE
```

### Phase 3

```text
Baselines
Transaction costs
Market regimes
```

### Phase 4

```text
Temporal split
Robustness analysis
Bootstrap confidence intervals
```

### Phase 5

```text
Reports
Automated tests
Execution of EXP-001 through EXP-005
```

Do not build a graphical interface.

Use a command-line interface:

```bash
python run_experiment.py \
  --event config/events/exp_001.yaml \
  --universe config/universe.yaml
```

---

## 22. Deliverables

The development AI must deliver:

```text
1. Complete source code.
2. README with installation and execution instructions.
3. requirements.txt or pyproject.toml.
4. Example configuration files.
5. Automated tests.
6. The five initial experiments.
7. A system-validation report.
8. A known-limitations document.
9. A sample generated experiment report.
```

---

## 23. Final Rule

Do not expand the scope without evidence.

The MVP objective is not to discover a profitable trading strategy.

The objective is to build a reliable mechanism that quickly decides:

> This hypothesis deserves further research, or it should be rejected.

A correctly validated negative result must be considered a successful outcome of the system.
