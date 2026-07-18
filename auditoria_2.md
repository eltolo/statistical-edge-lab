# Statistical Edge Lab — Audit 2

**Repository:** `eltolo/statistical-edge-lab`  
**Audited commit:** `70b6fe5cfcf9dfb8a10a799c4fe0e08ab777a6c6`  
**Audit type:** Static source-code and repository-state review  
**Test execution:** Not independently executed during this audit  
**Status:** This document supersedes `auditoria.md`

> ⚠️ **Nota post-auditoría:** Los commits `945f8da` y `d86e47a` (posteriores al commit auditado) 
> implementaron varias correcciones señaladas en este documento, incluyendo:
> - ATR percentile scale corregida (0-1, no 0-100) — §2.1
> - distance_to_high operator corregido (>= -0.05) — §2.2
> - Próximo-open horizonte corregido — §3.1
> - MFE/MAE incluyen entry session — §3.2
> - Adjusted OHLC usado en USD path — §3.3
> - Métricas netas como canónicas — §4.1
> - Holdout enforcement en decision engine — §4.3
> - Primary horizon enforcement — §4.4
> - Benchmark dolarizado para regímenes — §5
> - CCL left join (preserva sesiones) — §8.1
>
> Ver `git log --oneline` para el detalle completo. Las secciones marcadas como
> P0 deben verificarse contra el HEAD actual antes de asumir que siguen vigentes.

---

# 1. Executive verdict

The project has improved materially since the first audit. Several important corrections are now present:

- A shared forward-return function exists.
- The GGAL ADR mapping and implied CCL formula were corrected.
- Argentine features can be computed from USD-converted prices.
- Event conditions support repeated features and bounded ranges.
- Cooldowns use trading-session positions.
- Event entry defaults to the next session open.
- Target assets are separated from reference assets.
- Transaction-cost columns are added to event records.
- Discovery, validation, and holdout periods are calculated.

However, the current experiment conclusions are **not yet reliable**.

The main blockers are:

1. EXP-003 and EXP-004 event definitions are logically invalid.
2. The next-open holding horizon is off by one session.
3. The primary metrics and decision engine still use gross returns.
4. Holdout results are calculated but ignored by the decision engine.
5. Baselines do not use the same execution model as event trades.
6. The benchmark and regime calculation use nominal ARS data while target returns are evaluated in USD.
7. Robustness calculations still combine different horizons incorrectly.
8. The repository claims futures candidates without backtesting futures.
9. Reported experiment artifacts are absent from `results/`.

Therefore:

| Experiment | Current repository claim | Audit 2 status |
|---|---:|---|
| EXP-001 | REJECTED | **RERUN REQUIRED** |
| EXP-003 | RESEARCH | **INVALID CONFIGURATION** |
| EXP-004 | RESEARCH / futures CANDIDATE | **INVALID CONFIGURATION** |
| EXP-005 | RESEARCH / futures CANDIDATE | **UNVERIFIED** |
| Futures conclusions | CANDIDATE for EXP-04/05 | **NOT A FUTURES BACKTEST** |

Do not add more experiments until the P0 items below are corrected and all existing experiments are rerun from a clean cache.

---

# 2. Critical discovery: EXP-003 and EXP-004 are invalid

## 2.1 ATR percentile scale mismatch

`src/feature_engine.py` defines percentile rank as:

```python
return (history < current_value).sum() / len(history)
```

Therefore:

```text
atr_percentile_60d ∈ [0.0, 1.0]
```

But both configurations use:

```yaml
- feature: atr_percentile_60d
  operator: "<"
  value: 25
```

Since every valid percentile rank is lower than 25, this condition is effectively always true.

### Required correction

Choose one consistent representation.

Recommended:

```text
Percentile rank remains in [0, 1].
```

Then configure:

```yaml
- feature: atr_percentile_60d
  operator: "<"
  value: 0.25
```

Alternatively, multiply the feature by 100 and document that its range is `[0, 100]`. Do not mix both conventions.

Add schema-level range validation so a percentile feature rejects impossible thresholds such as `25` when its declared range is `[0, 1]`.

---

## 2.2 Distance-to-high operator is reversed

The feature is calculated as:

```python
distance_to_high_60d = (close - rolling_high_60d) / rolling_high_60d
```

Its normal range is:

```text
-1.0 <= distance_to_high_60d <= 0.0
```

A price within 5% of the 60-session high means:

```text
distance_to_high_60d >= -0.05
```

The current configuration uses:

```yaml
- feature: distance_to_high_60d
  operator: "<"
  value: 0.05
```

Nearly every valid observation is lower than `+0.05`, including a price 30%, 50%, or 80% below its high. This condition is therefore effectively always true.

### Required correction

Use:

```yaml
- feature: distance_to_high_60d
  operator: ">="
  value: -0.05
```

For additional safety, optionally add:

```yaml
- feature: distance_to_high_60d
  operator: "<="
  value: 0.0
```

---

## 2.3 Consequence

As currently implemented:

```text
EXP-003 ≈ almost every eligible date after warm-up and cooldown.
```

EXP-004 is effectively reduced to:

```text
20-session breakout + relative volume > 1.5
```

because its two supposed compression filters are nearly always true.

The current EXP-003 and EXP-004 event counts, returns, bootstrap intervals, decisions, and README conclusions must be discarded.

### Mandatory action

After correcting the configuration:

1. Delete previous EXP-003 and EXP-004 outputs.
2. Clear or validate all cached source data.
3. Rerun both experiments.
4. Record old versus corrected event counts.
5. Mark the previous results as superseded.

---

# 3. P0 — Execution and return correctness

## 3.1 Next-open horizon is off by one session

Current logic in `src/forward_returns.py`:

```python
entry_idx = signal_idx + 1
exit_idx = entry_idx + horizon
```

For a signal confirmed at close on session `t`:

```text
Entry for horizon 1: open at t+1
Current exit: close at t+2
```

This is not a one-session holding period. A one-session trade should enter at the next open and exit at that same session's close.

### Required correction

```python
exit_idx = entry_idx + horizon - 1
```

Expected behavior:

```text
horizon 1 → entry open t+1, exit close t+1
horizon 3 → entry open t+1, exit close t+3
horizon 5 → entry open t+1, exit close t+5
```

Correct the future-data availability check accordingly.

### Mandatory test

Given five consecutive sessions and a signal on session 0:

```text
horizon 1 exit must be session 1
horizon 3 exit must be session 3
```

---

## 3.2 MFE and MAE exclude the entry session

Current logic:

```python
hold_start = entry_idx + 1
```

This ignores the high and low of the entry session.

For a trade entered at the next session open, the entry session is part of the holding period and must be included.

### Required correction

```python
hold_start = entry_idx
hold_end = exit_idx
```

Then:

```python
high_slice = high.iloc[hold_start:hold_end + 1]
low_slice = low.iloc[hold_start:hold_end + 1]
```

For `horizon=1`, MFE and MAE must be calculated from the entry session's high and low.

---

## 3.3 Use adjusted OHLC consistently

`src/data_loader.py` creates adjusted OHLC fields, but `src/currency_adjustment.py` does not reference `adj_close` or the adjusted OHLC columns when producing:

```text
open_usd
high_usd
low_usd
close_usd
```

This leaves the main USD research path exposed to splits, dividends, and corporate-action discontinuities.

### Required correction

For each asset:

```python
adjustment_factor = adj_close / close

open_adj = open * adjustment_factor
high_adj = high * adjustment_factor
low_adj = low * adjustment_factor
close_adj = adj_close
```

For Argentine assets:

```python
open_usd = open_adj / ccl
high_usd = high_adj / ccl
low_usd = low_adj / ccl
close_usd = close_adj / ccl
```

For US assets:

```python
open_usd = open_adj
high_usd = high_adj
low_usd = low_adj
close_usd = close_adj
```

Store both raw and adjusted values.

---

# 4. P0 — Costs, metrics, and decision engine

## 4.1 Costs are added to rows but ignored by primary metrics

`run_experiment.py` adds:

```python
transaction_cost_pct
net_return_pct
```

However, `compute_overall_metrics()` calls `summarize_forward_returns()`, which reads only:

```python
fr_df["forward_return"]
```

Therefore the main metrics remain gross.

### Required refactor

Make the metric column explicit:

```python
compute_overall_metrics(
    event_returns,
    return_col="net_return_pct",
)
```

Generate both:

```text
gross_metrics
net_metrics
```

The default decision input must be `net_metrics`.

Do not reconstruct net mean inside the report by subtracting a generic cost from gross mean. Net statistics must be calculated from each event's actual `net_return_pct`.

---

## 4.2 Split metrics do not include transaction costs

The full-sample event records receive costs, but discovery, validation, and holdout records are recalculated without applying costs.

### Required correction

Use one shared event-evaluation pipeline:

```text
calculate returns
→ apply instrument-specific costs
→ assign temporal split
→ calculate gross and net metrics
```

Do not independently recalculate split returns with a different path.

A preferred design is to create one canonical event-trade table and aggregate it by:

```text
horizon
temporal_split
ticker
regime
```

---

## 4.3 Holdout is calculated but ignored

`run_experiment.py` creates `split_metrics`, but then calls:

```python
make_decision(
    metrics,
    robustness_results,
    cost_summary,
    n_total,
)
```

`split_metrics` is not passed to the decision engine or report.

The current decision can therefore assign `CANDIDATE` even if the holdout is negative.

### Required decision signature

```python
make_decision(
    primary_horizon,
    full_sample_net_metrics,
    split_net_metrics,
    baseline_metrics,
    robustness_metrics,
    concentration_metrics,
    cost_metrics,
)
```

### Mandatory rejection rules

Assign `REJECTED` when any is true:

```text
validation net median <= 0
holdout net median <= 0
holdout incremental edge <= 0
holdout event count below the declared minimum
```

A positive full sample must never override a failed holdout.

---

## 4.4 The declared primary horizon is ignored

Experiment YAML files declare:

```yaml
research:
  primary_horizon: 10
```

The decision engine instead searches all horizons for the best gross mean minus cost.

This creates horizon-selection bias.

### Required correction

Read the predeclared primary horizon:

```python
primary_horizon = config["research"]["primary_horizon"]
```

Use it for the formal decision.

Treat secondary horizons only as diagnostics.

Do not select the best horizon after examining results.

---

## 4.5 The decision engine ignores incremental edge

The current `make_decision()` contains a comment about incremental edge but does not receive baseline results and does not enforce them.

### Required correction

For the primary horizon calculate:

```text
net_incremental_edge =
    event_net_return
    - execution-matched_same-regime_baseline_return
```

A `CANDIDATE` requires:

```text
validation incremental edge > 0
holdout incremental edge > 0
full-sample incremental edge > 0
```

---

## 4.6 Bootstrap is performed on gross returns

Bootstrap inputs currently use:

```python
combined_returns[h]["forward_return"]
```

Use:

```python
combined_returns[h]["net_return_pct"]
```

Bootstrap separately for:

```text
full sample
validation
holdout
```

The primary confidence interval must correspond to the predeclared primary horizon.

---

# 5. P0 — Benchmark and regime currency mismatch

The target assets are converted to USD, but the benchmark is loaded separately and processed using raw:

```python
bench_feat = compute_all_features(bench)
```

Regimes are then assigned from:

```python
bench_feat["close"]
```

For the configured `^MERV` benchmark, this is nominal ARS.

The event returns are evaluated in USD, while:

- market regimes are based on nominal ARS;
- benchmark returns are also based on nominal ARS.

This creates a unit mismatch. A nominal Merval bull market caused primarily by inflation or devaluation may coexist with poor USD performance.

### Required correction

Use a benchmark expressed in the same currency as the target returns.

Acceptable options:

```text
1. Dollarize ^MERV with the same CCL series.
2. Use ARGT as a USD Argentina benchmark.
3. Produce both and explicitly select one as primary.
```

Recommended configuration:

```yaml
benchmark:
  regime_ticker: "^MERV"
  regime_currency: "USD"
  comparison_ticker: "ARGT"
  comparison_currency: "USD"
```

Then:

```python
benchmark_usd = dollarize_dataframe({"^MERV": benchmark}, ccl)["^MERV"]
benchmark_features = compute_all_features(
    benchmark_usd,
    price_col="close_usd",
    high_col="high_usd",
    low_col="low_usd",
)
```

All return comparisons must use the same currency.

This correction is especially important for EXP-005 because its event condition explicitly depends on:

```yaml
trend_regime != BEAR
```

EXP-005 must be rerun after this fix.

---

# 6. P0 — Baseline comparability

## 6.1 Baselines use a different execution window

Event trades use next-open entry.

Baseline returns use close-to-close forward returns from the event date or control date.

Those are not comparable.

### Required baseline execution model

For both event and control observations:

```text
Signal/control date: close t
Entry: open t+1
Exit: close t+h
```

Use the same shared trade-return function for:

```text
event returns
unconditional controls
regime-conditioned controls
benchmark controls
```

Do not compare next-open event trades with close-to-close baselines.

---

## 6.2 Create event-level matched baselines

The current implementation generates scalar regime averages and then aggregates them. It does not store a baseline matched to each event.

Build an event-control table containing:

```text
ticker
signal_date
horizon
trend_regime
volatility_regime
event_net_return_pct
matched_unconditional_baseline_pct
matched_regime_baseline_pct
benchmark_return_pct
incremental_edge_net_pct
```

For every event, select eligible control dates with:

```text
same asset
same trend regime
same volatility regime
same execution model
no overlap with event/cooldown windows
no future information
```

If a matched pool is too small, flag the event or regime as insufficient rather than silently using an unrelated baseline.

---

## 6.3 Report both weighting schemes

Generate:

```text
event_weighted_edge
asset_equal_weighted_edge
```

A pooled result can be dominated by the ticker with the largest number of events.

A candidate must not depend on only one asset.

---

# 7. P0 — Futures conclusions are unsupported

The README labels EXP-004 and EXP-005 as futures `CANDIDATE` after replacing the equity cost configuration with a lower round-trip percentage.

This is not a futures backtest.

The current pipeline does not model:

```text
actual futures contracts
contract multipliers
expiry dates
roll rules
basis versus cash
daily settlement
margin requirements
liquidity
open interest
bid-ask spread by contract
price limits
continuous-contract construction
contract-specific commissions
which target equities have a tradable equivalent future
```

The signals and returns still come from cash equities. Only the assumed cost changes.

### Required terminology

Until actual futures data and execution are implemented, call this:

```text
LOW-COST EXECUTION SENSITIVITY ANALYSIS
```

Do not call it:

```text
futures backtest
futures candidate
ROFEX candidate
```

### Required action

Remove `CANDIDATE futures` claims from the README.

A valid futures study requires a separate instrument layer:

```yaml
execution_instrument:
  signal_source: GGAL.BA
  tradable_symbol: actual_contract_symbol
  multiplier: ...
  expiry: ...
  roll_rule: ...
  margin_model: ...
  commission_model: ...
```

Then calculate returns from actual futures prices, not cash-equity returns.

---

# 8. P1 — CCL alignment and data integrity

## 8.1 Inner join defeats gap filling

`src/currency_adjustment.py` joins asset and CCL data using:

```python
how="inner"
```

Any asset session without an exact CCL observation is removed before forward filling. The later forward-fill logic cannot restore a row that was already discarded.

### Required correction

```python
merged = asset_df.join(ccl_df[["ccl"]], how="left")
merged["ccl"] = merged["ccl"].ffill(limit=max_ccl_gap_sessions)
```

Then:

- remove rows before the first valid CCL;
- reject gaps longer than the configured limit;
- report how many rows were filled and removed;
- never backfill from future CCL values.

---

## 8.2 Cache does not validate requested coverage

Cache files are keyed primarily by ticker. A cache hit may return stale or incomplete data without checking:

```text
requested start
requested end
last available session
download timestamp
data-source options
adjustment settings
```

### Required correction

Store cache metadata:

```json
{
  "ticker": "GGAL.BA",
  "source": "yfinance",
  "requested_start": "...",
  "requested_end": "...",
  "downloaded_at": "...",
  "first_available_date": "...",
  "last_available_date": "...",
  "auto_adjust": false
}
```

On load:

1. Slice to the requested interval.
2. Refresh missing beginning or ending periods.
3. Reject incomplete required coverage.
4. Record cache hashes in experiment metadata.

---

## 8.3 CCL metadata must be reproducible

Store:

```text
CCL source
ADR pair
ADR ratio
ratio effective dates
fallback method
fill limit
validation range
first and last CCL date
number of filled observations
```

Do not rely only on hardcoded source-code constants.

---

# 9. P1 — Robustness module remains incorrect

## 9.1 Leave-one-asset-out combines all horizons

Current logic appends returns from every horizon into one combined vector, then assigns the same event count and mean to every horizon.

This makes all horizon-specific leave-one-asset-out results identical.

### Required correction

Calculate independently:

```text
excluded_ticker
horizon
n_events
mean_net_return
median_net_return
incremental_edge_net
```

Never concatenate different holding horizons.

---

## 9.2 Leave-one-year-out creates artificial adjacency

Current logic removes every row belonging to the excluded year and then recalculates forward returns on the shortened DataFrame.

This can make December before the removed year adjacent to January after the removed year.

### Required correction

Keep the full continuous price series.

Then:

1. Detect events on the original data.
2. Calculate trades on the original data.
3. Remove event records whose signal date belongs to the excluded year.
4. Optionally remove trades whose holding interval intersects the excluded year.
5. Aggregate the remaining event table.

---

## 9.3 Profit concentration combines different horizons

`run_all_robustness()` accumulates returns from every horizon into the same per-asset arrays before calculating concentration.

The same signal is therefore counted several times as if it were several independent trades.

### Required correction

Calculate concentration separately for each horizon, especially the primary horizon:

```text
best trade contribution
best three trades contribution
best asset contribution
best year contribution
```

Use net returns.

Handle negative or near-zero total profit explicitly; percentage-of-profit metrics become unstable or meaningless in those cases.

---

## 9.4 Parameter-neighborhood helper is not operational

A helper exists, but:

- it is not called by `run_all_robustness()`;
- it assumes a dictionary-style condition schema, while current events use a list;
- it hardcodes cooldown `10`;
- it hardcodes horizon `5`;
- it uses close-to-close returns instead of the canonical execution model.

### Required correction

Build parameter neighborhoods from each experiment's YAML and execute them through the same canonical pipeline.

For EXP-005, test a small predeclared grid such as:

```text
z-score threshold: -1.75, -2.00, -2.25
cooldown sessions: 15, 20, 25
primary horizon remains fixed
```

Do not choose the best value. Report whether a stable region exists around the original hypothesis.

---

# 10. P1 — Temporal split integrity

The split is assigned using only `signal_date`.

A signal near a boundary can enter or exit in the following partition, allowing discovery or validation trades to consume prices from the next period.

### Required correction

Add a purge/embargo around split boundaries.

A trade belongs to a partition only when:

```text
signal_date
entry_date
exit_date
```

all fall inside that same partition.

Alternatively, exclude all trades whose holding window crosses a boundary.

Store:

```text
discovery_start/end
validation_start/end
holdout_start/end
purged event count
holdout opened timestamp
configuration hash before holdout
```

The holdout must be opened once and then locked.

---

# 11. P1 — Reporting and repository reproducibility

## 11.1 README claims cannot be independently reproduced from the repository

The README reports event counts, returns, bootstrap intervals, and decisions, but `results/` contains only `.gitkeep`.

No committed artifacts are available to verify those claims.

### Required deliverables per experiment

```text
results/<experiment_id>/
├── summary.md
├── metrics.csv
├── metrics.json
├── split_metrics.csv
├── baselines.csv
├── robustness.csv
├── metadata.json
└── charts/
```

If `events.csv` is too large for the repository, publish it as a release artifact or compressed research artifact and store its SHA-256 hash in `metadata.json`.

---

## 11.2 Report generator documentation does not match output

The report generator says it writes `metrics.csv`, but it currently writes only `metrics.json`.

Implement the declared output or correct the documentation. Prefer both.

The report also labels cooldown as days while the configuration uses sessions.

---

## 11.3 Metadata is insufficient

Current metadata contains mainly:

```text
experiment_id
generated_at
decision
decision_reason
```

Add:

```text
git commit hash
dirty working-tree status
Python version
dependency-lock hash
full event configuration
full universe configuration
full cost configuration
data-source identifiers
cache hashes
CCL metadata
execution model
primary horizon
random seed
split boundaries
holdout integrity status
row counts by ticker
event counts before and after cooldown
```

---

## 11.4 Documentation is contradictory

`README.md` reports completed experiments, while `AGENTS.md` still marks modules and experiments as pending.

Update documentation from generated metadata rather than manual statements.

`auditoria.md` is now stale and must be marked as superseded by this document.

---

# 12. Required integration tests

Add deterministic tests for all items below.

## Event definitions

```text
1. atr_percentile_60d=0.20 passes threshold 0.25.
2. atr_percentile_60d=0.30 fails threshold 0.25.
3. distance_to_high=-0.03 passes >= -0.05.
4. distance_to_high=-0.20 fails >= -0.05.
5. EXP-003 does not trigger when only one condition is satisfied.
6. EXP-004 requires compression, near-high, breakout, and volume simultaneously.
```

## Execution

```text
7. next-open horizon 1 exits on the entry session close.
8. next-open horizon 3 exits on the third session after the signal.
9. MFE includes the entry session high.
10. MAE includes the entry session low.
11. No return uses a price beyond the declared exit date.
```

## Prices and currency

```text
12. Adjusted OHLC is used before USD conversion.
13. A split does not create an artificial return.
14. CCL left join preserves asset sessions.
15. CCL never backfills from future dates.
16. A CCL gap beyond the configured limit raises an error.
17. Benchmark and event returns use the same currency.
```

## Costs and decisions

```text
18. Gross and net metrics differ by the event-specific cost.
19. Split metrics include transaction costs.
20. Negative holdout net median forces REJECTED.
21. Negative holdout incremental edge forces REJECTED.
22. The decision uses the predeclared primary horizon.
23. A stronger secondary horizon cannot override the primary horizon.
24. Bootstrap uses net returns.
```

## Baselines

```text
25. Event and baseline use the same next-open execution window.
26. Controls overlapping event windows are excluded.
27. Regime-matched baseline uses both trend and volatility regime.
28. Benchmark baseline uses USD when event returns use USD.
```

## Robustness

```text
29. Leave-one-asset-out differs by horizon when inputs differ.
30. Leave-one-year-out never joins prices across a removed year.
31. Profit concentration is calculated separately per horizon.
32. Parameter neighborhood accepts the list-based condition schema.
```

## Reproducibility

```text
33. A rerun with the same data and configuration produces identical results.
34. Metadata stores commit hash and configuration hash.
35. Stale cache coverage triggers a refresh or hard failure.
```

---

# 13. Required implementation order

Do not work on UI, machine learning, new event families, short strategies, or additional instruments.

Implement in this order:

```text
1. Correct EXP-003 and EXP-004 configurations.
2. Fix next-open horizon and MFE/MAE window.
3. Use adjusted OHLC throughout the USD path.
4. Unify event, split, robustness, and baseline execution.
5. Make net-return metrics canonical.
6. Make validation and holdout mandatory in the decision engine.
7. Enforce the predeclared primary horizon.
8. Dollarize benchmark and regime inputs.
9. Build execution-matched event-level baselines.
10. Correct robustness by horizon.
11. Add split-boundary purge/embargo.
12. Correct CCL alignment and cache validation.
13. Expand metadata and generated artifacts.
14. Rerun EXP-001, EXP-003, EXP-004, and EXP-005.
15. Update README and AGENTS.md from generated results.
```

---

# 14. Required rerun protocol

After all P0 corrections:

```text
1. Use a clean environment.
2. Pin dependencies.
3. Clear or audit data caches.
4. Run the complete test suite.
5. Record the pytest output.
6. Run each experiment only once against the locked holdout.
7. Save all generated artifacts.
8. Compare old and corrected results.
9. Mark every previous conclusion as superseded.
```

The comparison must include:

```text
raw signal count
independent event count
events per asset
events per regime
gross mean and median
net mean and median
validation result
holdout result
execution-matched baseline
net incremental edge
bootstrap interval
leave-one-asset-out
leave-one-year-out
profit concentration
parameter-neighborhood stability
final decision
```

---

# 15. Acceptance gate

No experiment may receive `CANDIDATE` until all conditions below are true:

```text
All P0 tests pass.
The primary horizon was declared before execution.
The event definition has validated feature ranges.
The execution horizon is correct.
Adjusted prices are used.
Event and baseline execution models match.
All primary returns are in the same currency.
Costs are applied per event.
Validation net median is positive.
Holdout net median is positive.
Holdout incremental edge is positive.
Robustness is calculated per horizon.
Parameter neighborhood is stable.
No single asset or trade dominates the result.
Generated artifacts are reproducible from the audited commit.
```

A lower-cost sensitivity analysis must never be labeled as a futures strategy without actual futures data and execution modeling.

---

# 16. Final instruction to the development AI

Do not optimize the reported results.

Do not try to preserve the existing `RESEARCH` or `CANDIDATE` labels.

The objective is to make incorrect conclusions impossible.

The immediate milestone is:

> Produce one internally consistent, reproducible, net-of-cost, holdout-validated EXP-005 result using corrected event definitions, adjusted USD prices, execution-matched baselines, and the predeclared primary horizon.

Only after that result is trustworthy should the project continue to other experiments or instrument types.
