# Statistical Edge Lab — Audit 4

**Date:** 2026-07-18  
**Repository:** `github.com/eltolo/statistical-edge-lab`  
**Audited branch:** current public `main`  
**Repository state observed:** 8 commits  
**Audit scope:** source code, experiment configurations, test definitions, documentation, and published result artifacts  
**Previous documents superseded for current-state assessment:** `auditoria.md`, `auditoria_2.md`, and `20260718_respuestas.md`

---

# 1. Executive verdict

The repository has improved materially.

The following corrections are genuinely implemented in the current public code:

- `next_open` execution now uses the intended holding-session semantics.
- `horizon=1` enters at `open(t+1)` and exits at `close(t+1)`.
- MFE and MAE include the entry session.
- Boundary-crossing trades are identified and excluded from formal temporal-split metrics.
- Target assets are separated from reference assets.
- Event rows receive instrument-specific transaction-cost and net-return columns.
- Exact `trend_regime + volatility_regime` baseline matching exists.
- The experiment configurations declare a primary horizon.

However, the current reported experiment decisions are still not trustworthy.

The decisive problems are:

1. EXP-003 and EXP-004 are still configured with invalid feature scales and operators.
2. The primary metrics continue to summarize gross returns instead of event-level net returns.
3. The decision engine ignores validation, holdout, incremental edge, and baseline coverage.
4. The decision engine selects the best historical horizon instead of using the predeclared primary horizon.
5. Event trades and control baselines use different execution models.
6. The target assets are evaluated in USD while benchmark regimes are still generated from nominal ARS data.
7. Robustness analysis continues to use gross returns and contains a broken parameter-neighborhood path.
8. The repository publishes exact results while `results/` contains no auditable experiment artifacts.

Therefore:

```text
The project is not ready for paper trading.
The current README decisions must be treated as provisional.
EXP-003 and EXP-004 results must be considered invalid.
All experiments require a corrected clean rerun.
```

---

# 2. Audit methodology

This audit reviewed the current public files rather than relying on earlier audit documents.

The following were inspected:

```text
run_experiment.py
src/forward_returns.py
src/report_generator.py
src/baseline_comparator.py
src/currency_adjustment.py
src/feature_engine.py
src/robustness.py
src/event_detector.py
src/validator.py
config/events/exp_001.yaml through exp_005.yaml
tests/test_statistical_edge_lab.py
README.md
HANDOFF.md
AGENTS.md
results/
data/
```

Execution performed during this audit:

```text
Python syntax compilation of the downloaded current src/ modules:
PASS

Targeted audit smoke tests:
5 passed
```

The targeted tests verified:

```text
1. Correct next-open horizon semantics.
2. Correct inclusion of entry-session high and low in MFE/MAE.
3. Primary metrics ignore net_return_pct.
4. Baselines use a different execution window from event trades.
5. The decision function cannot consume holdout results and selects among horizons.
6. parameter_neighborhood is incompatible with current list-based conditions.
```

Some tests intentionally assert the presence of a defect. A passing audit test means the finding was reproduced.

The repository's full official pytest suite was inspected but was not independently executed in this environment because the repository could not be cloned through the execution shell. Do not interpret this audit as independent confirmation of the repository's claimed full-suite result.

---

# 3. Corrections verified as implemented

## 3.1 Next-open horizon

Current behavior:

```text
Signal confirmed: close t
Entry: open t+1
horizon=1 exit: close t+1
horizon=3 exit: close t+3
```

The implementation correctly uses:

```python
exit_idx = entry_idx + horizon - 1
```

This issue from the previous audit is closed.

---

## 3.2 MFE and MAE holding window

For `next_open`, the implementation now begins the excursion window at:

```python
hold_start = entry_idx
```

This correctly includes the entry session's high and low.

This issue from the previous audit is closed.

---

## 3.3 Boundary-crossing trades

The pipeline now classifies the trade using:

```text
signal_date
entry_date
exit_date
```

and removes trades that cross discovery, validation, or holdout boundaries from split metrics.

This is the correct policy.

However, the resulting split metrics are not yet used by the decision engine. The leakage correction is implemented, but its output is operationally ignored.

---

## 3.4 Exact regime baseline

The baseline module now supports matching controls by:

```text
same ticker
same trend regime
same volatility regime
excluding event and cooldown windows
```

It also returns:

```text
VALID
LOW_CONFIDENCE
INSUFFICIENT
```

This is a meaningful improvement.

The remaining defects are in execution comparability, aggregation, coverage use, and decision integration.

---

# 4. P0 — EXP-003 and EXP-004 remain invalid

This is the most direct and serious configuration error.

## 4.1 ATR percentile scale mismatch

The feature engine calculates percentile rank as:

```python
(historical_values < current_value).sum() / len(historical_values)
```

Therefore:

```text
atr_percentile_60d range = 0.0 to 1.0
```

The current EXP-003 and EXP-004 configurations use:

```yaml
- feature: atr_percentile_60d
  operator: "<"
  value: 25
```

Every normal percentile value is lower than 25.

This condition is effectively always true.

### Required correction

```yaml
- feature: atr_percentile_60d
  operator: "<"
  value: 0.25
```

---

## 4.2 Distance-to-high condition is reversed

The feature is:

```python
distance_to_high_60d =
    (close - rolling_high_60d) / rolling_high_60d
```

Its normal values are non-positive:

```text
at the high: 0.00
5% below the high: -0.05
20% below the high: -0.20
```

The current condition is:

```yaml
- feature: distance_to_high_60d
  operator: "<"
  value: 0.05
```

A price 5%, 20%, or 80% below its high all satisfy this condition.

The intended condition “within 5% of the high” is:

```yaml
- feature: distance_to_high_60d
  operator: ">="
  value: -0.05
```

---

## 4.3 Consequence

The current EXP-003 event is not a volatility-compression-near-high event.

It is approximately:

```text
almost every eligible date after feature warm-up and cooldown
```

The current EXP-004 is approximately:

```text
20-session close breakout + relative volume > 1.5
```

Its two compression filters are effectively inactive.

Therefore:

```text
EXP-003 event count is invalid.
EXP-003 returns and decision are invalid.
EXP-004 event count is invalid.
EXP-004 returns and decision are invalid.
README conclusions for EXP-003 and EXP-004 must be removed or marked superseded.
```

### Required prevention

Add feature metadata and configuration validation:

```python
FEATURE_SCHEMA = {
    "atr_percentile_60d": {
        "minimum": 0.0,
        "maximum": 1.0,
    },
    "distance_to_high_60d": {
        "minimum": -1.0,
        "maximum": 0.0,
    },
}
```

The experiment must fail before execution when a configured value is outside the declared feature range.

Also add semantic tests for the actual experiment YAML files, not only unit tests for generic operators.

---

# 5. P0 — Net returns are computed but not used

The pipeline correctly adds:

```text
transaction_cost_pct
net_return_pct
```

to each event record.

Immediately afterward, it calls:

```python
metrics = compute_overall_metrics(combined_returns)
```

But `summarize_forward_returns()` hardcodes:

```python
returns = fr_df["forward_return"].values
```

Therefore:

```text
mean_return is gross
median_return is gross
win_rate is gross
profit_factor is gross
bootstrap is gross
split metrics are gross
robustness is gross
```

The decision engine later subtracts one generic cost from the gross mean. That is not equivalent to calculating the distribution of event-level net returns.

## Required refactor

Use explicit return columns:

```python
def summarize_forward_returns(
    fr_df,
    horizon,
    return_col: str,
):
    returns = fr_df[return_col].dropna().values
```

Generate:

```text
gross_metrics → return_col="forward_return"
net_metrics   → return_col="net_return_pct"
```

For all formal decisions, use:

```text
net median
net mean
net win rate
net profit factor
net bootstrap
net asset consistency
net year consistency
```

Do not approximate the net distribution by subtracting a constant from one aggregate gross mean.

---

# 6. P0 — Holdout exists but is ignored

The pipeline calculates:

```text
split_metrics["discovery"]
split_metrics["validation"]
split_metrics["holdout"]
```

It correctly purges boundary-crossing trades.

But the final decision call is:

```python
make_decision(
    metrics,
    robustness_results,
    cost_summary,
    n_total,
)
```

The decision function does not receive:

```text
split_metrics
baselines
baseline coverage
primary horizon
```

The generated report also does not receive split metrics.

As a result, a strategy can be declared `CANDIDATE` even when:

```text
validation is negative
holdout is negative
holdout incremental edge is negative
holdout contains too few events
```

## Required decision interface

```python
make_decision(
    primary_horizon: int,
    full_sample_net_metrics: dict,
    split_net_metrics: dict,
    baseline_metrics: dict,
    baseline_coverage: dict,
    robustness_metrics: dict,
    concentration_metrics: dict,
    cost_metrics: dict,
    n_total_events: int,
) -> tuple[str, str]
```

## Mandatory rejection conditions

For the predeclared primary horizon:

```text
validation net median <= 0
holdout net median <= 0
holdout incremental edge <= 0
holdout event count below minimum
```

Any of these must prevent `CANDIDATE`.

A positive full sample must never override a failed holdout.

---

# 7. P0 — Primary horizon is ignored

The YAML configurations declare:

```yaml
research:
  primary_horizon: 10
```

The current decision engine searches every horizon and chooses:

```text
the horizon with the largest gross mean minus generic costs
```

The README explicitly reports:

```text
Bruto (mejor H)
```

This is post-selection.

It increases the risk of choosing a chance historical winner and contradicts the research protocol.

## Required correction

Read before execution:

```python
primary_horizon = event_config["research"]["primary_horizon"]
```

Use only that horizon for the formal classification.

Secondary horizons are diagnostics.

Do not permit a better-performing secondary horizon to rescue a failed primary hypothesis.

Each horizon can alternatively be treated as a separate registered hypothesis, but this must be declared before opening validation and holdout.

---

# 8. P0 — Incremental edge is not used by the decision engine

The current decision code contains only a comment:

```python
# Check incremental edge
# (already computed in baseline comparison)
```

No baseline result is passed to the function.

Therefore, the engine can call a pattern a candidate merely because it has a positive absolute return, even if the same asset and regime normally performed better without the event.

## Required primary metric

For each event:

```text
net_incremental_edge =
    event_net_return
    - matched_control_return
```

Then calculate by split:

```text
validation median net incremental edge
holdout median net incremental edge
full-sample median net incremental edge
```

A candidate requires all three to be positive at the primary horizon.

---

# 9. P0 — Event and baseline execution are not comparable

Event trades use:

```text
signal close t
entry open t+1
exit close t+h
```

Baselines use:

```python
forward_return_series(close, horizon)
```

which means:

```text
entry close t
exit close t+h
```

These are different trades.

A gap between close `t` and open `t+1` affects event returns but not control returns.

The baseline module's claim that the shared function “matches event-return calculation” is incorrect.

## Required correction

Use one canonical trade-return function for both events and controls:

```python
trade_return_at_signal(
    df,
    signal_index,
    holding_sessions,
    entry_mode="next_open",
    exit_mode="close",
)
```

For every event and control date:

```text
entry = next session open
exit = close after the declared holding sessions
cost treatment = same
price adjustment = same
currency = same
```

Store event-level control data:

```text
ticker
signal_date
horizon
trend_regime
vol_regime
event_net_return_pct
matched_control_return_pct
incremental_edge_net_pct
n_controls
baseline_status
```

---

# 10. P0 — Benchmark and regime currency mismatch

Argentine target features are computed from:

```text
close_usd
high_usd
low_usd
```

But the benchmark path is:

```python
bench_feat = compute_all_features(bench)
compute_all_regimes(asset, bench_feat["close"])
```

For `^MERV`, that close is nominal ARS.

Therefore:

```text
target event features: USD
target forward returns: USD
market trend regime: nominal ARS
benchmark baseline: nominal ARS
```

This can classify a market as bullish because nominal prices rose with inflation or devaluation, even when USD performance was weak.

## Required correction

Use one currency domain.

Recommended:

```text
Regime benchmark:
dollarized ^MERV

External comparison benchmark:
ARGT in USD
```

Example:

```python
benchmark_usd = dollarize_dataframe({"^MERV": bench}, ccl)["^MERV"]

bench_feat = compute_all_features(
    benchmark_usd,
    price_col="close_usd",
    high_col="high_usd",
    low_col="low_usd",
)
```

EXP-005 must be rerun after this fix because its event explicitly depends on `trend_regime != BEAR`.

---

# 11. P0 — Baseline coverage aggregation is wrong

`baseline_coverage` is initialized once before looping through horizons:

```python
baseline_coverage = {}

for horizon in horizons:
    ...
    baseline_coverage[k] += ...
```

The counts accumulate across all five horizons.

The final accumulated dictionary is attached only to the first horizon.

This can multiply the apparent number of baseline observations and makes the reported coverage ambiguous.

## Additional weighting error

For a ticker, the exact matched mean is calculated only from events with usable control pools.

The aggregation then multiplies that mean by:

```text
all events for the ticker
```

including events with `INSUFFICIENT` controls.

The correct weight is:

```text
number of events included in that matched mean
```

or, preferably, aggregate from the event-level control table directly.

## Required correction

Store coverage separately:

```python
baseline_coverage[horizon] = {
    ...
}
```

Aggregate exact matched results only from event rows with:

```text
VALID or LOW_CONFIDENCE
```

Report:

```text
coverage by horizon
coverage by split
coverage by ticker
coverage by regime
```

The primary-horizon coverage rule must be enforced by the decision engine.

---

# 12. P0 — CCL alignment and adjusted prices remain incomplete

## 12.1 Inner join prevents gap handling

The currency module uses:

```python
asset.join(ccl, how="inner")
```

and only afterward calls:

```python
ffill(limit=5)
```

Rows with no exact CCL date were already removed by the inner join.

The forward fill cannot restore them.

Use:

```python
merged = asset.join(ccl[["ccl"]], how="left")
merged["ccl"] = merged["ccl"].ffill(limit=max_gap_sessions)
```

Then fail when gaps exceed the limit.

---

## 12.2 Raw OHLC is dollarized

The code converts:

```text
open
high
low
close
```

directly to USD.

It does not use adjusted OHLC derived from `adj_close`.

Corporate actions can therefore create artificial returns and technical signals.

## Required correction

```python
adjustment_factor = adj_close / close

open_adj = open * adjustment_factor
high_adj = high * adjustment_factor
low_adj = low * adjustment_factor
close_adj = adj_close
```

Then:

```python
open_usd = open_adj / ccl
high_usd = high_adj / ccl
low_usd = low_adj / ccl
close_usd = close_adj / ccl
```

Use adjusted USD prices for features, returns, MFE, and MAE.

---

# 13. P1 — Robustness is still gross and incomplete

The robustness module uses:

```python
fr[h]["forward_return"]
```

for:

```text
bootstrap
leave-one-asset-out
leave-one-year-out
profit concentration
```

Costs are not applied.

No matched incremental edge is tested.

## Required correction

Robustness must operate on the canonical event table after:

```text
execution
costs
split classification
matched baseline
```

For the primary horizon, calculate:

```text
net bootstrap
net incremental-edge bootstrap
leave-one-asset-out net median
leave-one-asset-out incremental edge
leave-one-year-out net median
leave-one-year-out incremental edge
profit concentration from net P&L
```

---

## 13.1 Profit concentration with negative total profit

The current formula divides the best trade by total profit.

When total profit is negative or close to zero, the percentage becomes misleading or unstable.

Use concentration metrics only when total net P&L is positive and materially above zero.

Otherwise report:

```text
status = NOT_APPLICABLE_NEGATIVE_TOTAL
```

---

## 13.2 Leave-one-year-out boundary handling

Events are excluded only when `signal_date.year` equals the removed year.

A trade whose signal is in December and exit is in January can still cross the omitted year boundary.

Filter based on the complete holding interval:

```text
signal_date
entry_date
exit_date
```

---

# 14. P1 — Parameter neighborhood is broken

`parameter_neighborhood()` currently:

- expects dictionary-style conditions;
- current experiment conditions use a list;
- imports `apply_cooldown`, which is not the active cooldown function;
- hardcodes cooldown 10;
- hardcodes horizon 5;
- calculates close-to-close returns;
- does not use costs;
- is not called by `run_all_robustness()`.

Therefore parameter-neighborhood validation is not operational.

## Required replacement

Run every neighboring configuration through the same canonical experiment pipeline.

For EXP-005:

```text
Primary:
z-score = -2.00
window = 60
horizon = 10

Stage A:
z-score = -1.75, -2.00, -2.25
window fixed at 60

Stage B:
window = 40, 60, 80
z-score fixed at -2.00
```

Do not select the best cell.

The objective is to verify a stable plateau around the registered hypothesis.

---

# 15. P1 — Current tests validate the old decision behavior

The test suite includes a candidate test based on:

```text
gross mean = 5%
100 events
generic round-trip cost = 1.96%
```

and expects `CANDIDATE`.

It does not require:

```text
validation
holdout
incremental edge
baseline coverage
registered primary horizon
net median
```

Therefore, the existing test suite can pass while the research protocol is violated.

## Required decision tests

Add deterministic tests:

```text
1. Positive full sample + negative validation → not CANDIDATE.
2. Positive full sample + negative holdout → REJECTED.
3. Positive holdout return + negative holdout edge → REJECTED.
4. Secondary horizon succeeds but primary fails → primary decision remains failed.
5. Baseline coverage below threshold → maximum RESEARCH.
6. Gross positive but net median negative → REJECTED.
7. Net mean positive but net median negative → not CANDIDATE.
8. Event and control return use identical next-open timing.
```

---

# 16. P1 — Published results are not reproducible

The README publishes exact values for five experiments and labels them “final post-audit results.”

But the public `results/` directory contains only:

```text
.gitkeep
```

Missing:

```text
summary.md
metrics.csv
split_metrics.csv
baselines.csv
robustness.csv
metadata.json
configuration snapshot
data hashes
test output
```

Consequently, an external auditor cannot reproduce or verify the published values.

The absence is especially serious because EXP-003 and EXP-004 configurations are still invalid.

## Required repository artifacts

For each official experiment:

```text
results/<experiment_id>/
├── summary.md
├── metrics_gross.csv
├── metrics_net.csv
├── split_metrics.csv
├── baselines.csv
├── baseline_coverage.csv
├── robustness.csv
├── metadata.json
└── config_snapshot.yaml
```

`metadata.json` must include:

```text
git commit hash
dirty working-tree status
Python version
dependency-lock hash
random seed
data source
data hashes
CCL source and ADR ratio
cache metadata
start/end dates by ticker
primary horizon
execution model
cost model
split boundaries
purged trade count
holdout-open timestamp
test-suite result
```

Large event tables can be compressed or published as release artifacts, but their hash must be retained.

---

# 17. P1 — Documentation drift

The README calls the results final and audited.

`HANDOFF.md` still references an older commit and contains older experiment classifications.

`20260718_respuestas.md` describes pre-fix conditions as though they were current.

This creates ambiguity about which document is authoritative.

## Required policy

```text
README.md
→ current verified public results only

HANDOFF.md
→ current milestone and exact commit

AUDIT_STATUS.md or metadata.json
→ machine-readable implementation and experiment status

Historical audits
→ clearly marked SUPERSEDED
```

Do not update the README until corrected artifacts exist.

---

# 18. Current experiment status

## EXP-001 — Moderate Pullback

```text
Configuration appears structurally correct.
Execution semantics are corrected.
Current decision remains unverified because:
- metrics are gross;
- holdout is ignored;
- baseline timing differs;
- regime benchmark currency differs;
- results are not published.
```

Status:

```text
RERUN REQUIRED
```

---

## EXP-002 — Pullback With Volume

```text
Configuration appears structurally correct.
Current decision remains unverified for the same engine-level reasons as EXP-001.
```

Status:

```text
RERUN REQUIRED
```

---

## EXP-003 — Volatility Compression

```text
ATR percentile threshold is invalid.
Distance-to-high operator and threshold are invalid.
```

Status:

```text
CURRENT RESULT INVALID
```

---

## EXP-004 — Breakout From Compression

```text
Inherits both invalid EXP-003 filters.
Current result is primarily a breakout-plus-volume study, not the declared compression-breakout study.
```

Status:

```text
CURRENT RESULT INVALID
```

---

## EXP-005 — Extreme Decline

```text
Event definition is plausible.
Current result remains unverified because:
- market regime benchmark is nominal ARS;
- primary horizon is ignored;
- holdout is ignored;
- metrics and robustness are gross;
- parameter neighborhood is not operational.
```

Status:

```text
RERUN REQUIRED
```

---

# 19. Required implementation order

Do not add experiments, machine learning, futures execution, or UI work.

Implement in this order:

```text
1. Correct EXP-003 and EXP-004 YAML values.
2. Add feature-range validation and fail-fast configuration checks.
3. Create a canonical event-trade table.
4. Make net_return_pct the formal metric input.
5. Enforce the predeclared primary horizon.
6. Pass validation and holdout metrics into make_decision().
7. Pass matched baseline edge and coverage into make_decision().
8. Rebuild baselines with next-open execution.
9. Dollarize the benchmark used for regimes.
10. Correct baseline coverage aggregation by horizon and covered event.
11. Use adjusted OHLC before USD conversion.
12. Change CCL alignment to left join plus bounded forward fill.
13. Run robustness from the canonical net event table.
14. Replace parameter_neighborhood with pipeline-level reruns.
15. Expand decision tests.
16. Generate reproducible result artifacts.
17. Perform a clean-cache rerun of EXP-001 through EXP-005.
18. Update README, HANDOFF, and AGENTS only after acceptance.
```

---

# 20. Acceptance gate

No experiment may receive `CANDIDATE` until all conditions are true:

```text
Experiment YAML passes feature-range validation.
Primary horizon was registered before validation and holdout.
Adjusted USD OHLC is used.
Signal, entry, and exit timing are correct.
Event and control execution models are identical.
Costs are applied per event.
Primary metrics use net_return_pct.
Validation net median is positive.
Holdout net median is positive.
Holdout matched incremental edge is positive.
Exact baseline coverage meets the threshold.
Robustness uses net returns and the primary horizon.
Nearby parameter values preserve the sign and reasonable magnitude.
No single trade, asset, or year dominates the result.
Results are reproducible from committed metadata and configuration.
```

---

# 21. Final instruction to the development AI

Do not attempt to preserve the current README conclusions.

Do not optimize parameters before correcting the common engine.

Do not rerun only EXP-005.

The next milestone is:

> Produce a fully reproducible EXP-001 result using adjusted USD prices, event-level net metrics, the registered primary horizon, mandatory validation and holdout, and execution-matched controls.

After that result passes the acceptance gate, rerun EXP-002 through EXP-005.

EXP-003 and EXP-004 must be treated as new official runs because the current configurations do not represent their stated hypotheses.
