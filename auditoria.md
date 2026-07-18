# Statistical Edge Lab — Correctness Audit and Required Fixes

Stop adding experiments or features.

Do not implement EXP-002 through EXP-005 yet.

The current priority is to correct the research engine and rerun EXP-001 from scratch. The existing EXP-001 result must be treated as invalid or unverified until all P0 issues below are fixed.

## Current assessment

The repository has a good modular structure and a reasonable MVP direction. However, several implementation errors can materially change returns, baselines, event classification, transaction-cost results, robustness metrics, and the final decision.

The README currently reports EXP-001 as complete with 859 events and decision `RESEARCH`, but `AGENTS.md` still reports the entire implementation as pending. Synchronize project documentation only after the corrected pipeline has been executed successfully.

---

# P0 — Blocking correctness issues

## 1. Fix all forward-return calculations

The following expression is incorrect:

```python
prices.pct_change(periods=-horizon).shift(-horizon)
```

It does not calculate:

```text
price[t + horizon] / price[t] - 1
```

Replace it everywhere with an explicit forward-return expression:

```python
forward_return = (
    prices.shift(-horizon)
    .div(prices)
    .sub(1.0)
    .mul(100.0)
)
```

Audit at least:

```text
src/currency_adjustment.py
src/baseline_comparator.py
src/robustness.py
```

Use one shared function for forward-return calculation. Do not duplicate this formula across modules.

The event-return implementation in `forward_returns.py` uses explicit price indexing, while baseline and helper functions use the incorrect `pct_change` expression, making event returns and baselines incomparable.

### Required test

For prices:

```text
100, 110, 121, 133.1
```

The expected one-period forward returns are:

```text
10%, 10%, 10%, NaN
```

The expected two-period forward returns are:

```text
21%, 21%, NaN, NaN
```

---

## 2. Remove execution look-ahead

The event is detected using information from the close of day `t`, but the current implementation uses the close of day `t` as the entry price.

That assumes the trade can be executed at a price already used to confirm the signal.

Default execution must be:

```text
Signal confirmed: close of session t
Entry: open of session t + 1
1-day exit: close of session t + 1
5-day exit: close of session t + 5
```

Implement configurable execution rules:

```yaml
execution:
  signal_time: close
  entry_mode: next_open
  exit_mode: close
```

The default must be `next_open`.

A same-close entry may be supported only as an explicitly named sensitivity test:

```yaml
entry_mode: signal_close
```

It must not be the default or primary result.

Add the following fields to every event record:

```text
signal_date
entry_date
exit_date
signal_price
entry_price
exit_price
```

The current implementation enters at the event-date close even though the event is confirmed using that same close.

---

## 3. Correct MFE and MAE

MFE and MAE are currently calculated from closing prices only.

For a long trade:

```text
MFE = maximum future adjusted high / entry price - 1
MAE = minimum future adjusted low / entry price - 1
```

Use:

```text
high_usd
low_usd
```

or properly adjusted OHLC columns.

Do not use `close_usd` for both MFE and MAE.

Required output:

```text
mfe_pct
mae_pct
mfe_date
mae_date
```

The current `forward_returns.py` implementation calculates both excursions from the close series.

---

## 4. Rebuild the CCL fallback

The fallback CCL implementation has two critical problems.

### Problem A: wrong ADR ticker resolution

`load_ccl_series()` attempts to load the GGAL ADR using:

```python
load_data(["GGAL"], ...)
```

However, `_ticker_to_yahoo("GGAL")` converts it to `GGAL.BA`, because GGAL is not included in the hardcoded US ticker set.

Therefore, the fallback may compare the local GGAL price against the same local instrument instead of the US ADR.

Remove symbol guessing.

Use explicit instrument metadata:

```yaml
instruments:
  GGAL.BA:
    yahoo_symbol: GGAL.BA
    market: argentina
    currency: ARS

  GGAL:
    yahoo_symbol: GGAL
    market: usa
    currency: USD
    instrument_type: adr
```

### Problem B: inverted ADR-ratio formula

When:

```text
ADR ratio R = local shares represented by one ADR
```

the implied CCL must be:

```text
CCL = local_share_price_ARS × R / ADR_price_USD
```

For GGAL with a configured ratio of 10:

```python
ccl = local_price_ars * 10 / adr_price_usd
```

The current implementation calculates:

```python
local_price_ars / (adr_price_usd * 10)
```

which is algebraically incorrect.

### Required test

Given:

```text
Local share price = ARS 1,000
ADR price = USD 10
ADR ratio = 10
```

Expected:

```text
CCL = 1,000 ARS/USD
Local share value = USD 1
```

### Additional CCL rules

* ADR ratios must be configurable, not hardcoded.
* Store the CCL source and ratio used in metadata.
* Validate CCL against realistic minimum and maximum ranges.
* Do not silently accept absurd values.
* Do not use backfill with future CCL observations.
* Forward-fill only within a configurable maximum gap.
* Remove rows before the first valid CCL observation.
* Fail the experiment if CCL data is unavailable for Argentine assets.

The current code backfills missing CCL observations and may fill unresolved values with `1.0`. It also treats an Argentine ticker as already denominated in USD when no CCL series is available. Both behaviors must be removed.

---

## 5. Calculate Argentine features in hard currency

`dollarize_dataframe()` creates `close_usd`, but `compute_all_features()` continues calculating SMA, momentum, returns, ATR-related signals and pullbacks using the raw `close`, `high`, and `low` columns.

For Argentine assets, this means event detection is primarily based on nominal ARS prices, while future performance is evaluated in USD.

That allows inflation and currency depreciation to distort trend and pullback classifications.

Refactor the feature engine:

```python
compute_all_features(
    df,
    price_col="close_usd",
    high_col="high_usd",
    low_col="low_usd",
    volume_col="volume",
)
```

Add to the experiment configuration:

```yaml
pricing:
  signal_currency: USD
  evaluation_currency: USD
  price_adjustment: adjusted
```

Default for Argentine assets:

```text
signal_currency = USD
evaluation_currency = USD
```

Optionally produce a secondary ARS diagnostic, but the primary result must use hard-currency signals and returns.

The current feature engine explicitly reads `result["close"]`, and the pipeline runs it after creating the USD columns without passing a USD price column.

---

## 6. Correct EXP-001 definition

EXP-001 is documented as:

```text
Three-day pullback between -3% and -7%
```

The current YAML only enforces:

```yaml
return_3d:
  operator: "<"
  value: -0.03
```

This includes declines of:

```text
-8%
-15%
-30%
```

which belong to a different event family.

EXP-001 must require:

```text
-7% <= return_3d < -3%
```

The event schema must support multiple rules for the same feature.

Recommended schema:

```yaml
conditions:
  - feature: close_above_sma_200
    operator: "=="
    value: 1.0

  - feature: return_60d
    operator: ">"
    value: 0.10

  - feature: return_3d
    operator: ">="
    value: -0.07

  - feature: return_3d
    operator: "<"
    value: -0.03
```

Alternatively, implement:

```yaml
return_3d:
  operator: between
  lower: -0.07
  upper: -0.03
  lower_inclusive: true
  upper_inclusive: false
```

The configuration description and implementation currently disagree.

---

## 7. Apply transaction costs to every event

The pipeline currently loads and summarizes transaction costs, but it does not apply costs to each event-return DataFrame before computing the main metrics.

Add:

```text
gross_return_pct
transaction_cost_pct
net_return_pct
```

Cost selection must depend on the instrument market:

```text
Argentina asset → Argentina cost model
US asset → USA cost model
```

Primary metrics must be calculated using `net_return_pct`.

The main edge must be:

```text
incremental_edge_net =
    event_return_gross
    - matched_regime_baseline_return
    - transaction_cost
```

Calculate and report:

```text
gross mean
gross median
net mean
net median
gross incremental edge
net incremental edge
break-even cost
estimated cost / gross edge
```

The final decision must not select a horizon merely because its gross mean minus a generic cost is positive.

The pipeline currently loads `cost_summary` after metrics and baselines have already been calculated. The decision logic uses gross mean minus one global cost assumption rather than per-event net returns.

---

## 8. Make the temporal split operational

`TemporalSplit.fit()` is called, but its result is not used to calculate discovery, validation, or holdout metrics.

This means the current final decision is not actually based on out-of-sample validation.

Produce separate results for:

```text
discovery
validation
holdout
full_sample
```

For every split and horizon, calculate:

```text
n_events
gross mean
gross median
net mean
net median
win rate
incremental edge
bootstrap confidence interval
```

Decision rules:

```text
REJECTED:
- holdout net median <= 0
- holdout incremental edge <= 0
- validation and holdout have opposite signs without a justified explanation

CANDIDATE:
- positive validation net median
- positive holdout net median
- positive holdout incremental edge
- sufficient holdout event count
```

The holdout result must be a hard requirement. It must not be calculated and ignored.

The current pipeline determines split boundaries but passes full-sample metrics directly to `make_decision()`.

---

## 9. Rebuild baseline comparison

### Fix forward-return formula

Use the same shared forward-return function used by event returns.

### Do not use one dominant regime

The current baseline comparator finds the dominant regime among all event dates and uses that single regime for every event.

Instead, each event must be compared against observations from its own regime:

```text
Event in BULL/HIGH_VOL → BULL/HIGH_VOL control observations
Event in NEUTRAL/LOW_VOL → NEUTRAL/LOW_VOL control observations
```

### Prevent baseline contamination

Exclude:

```text
the event date
the event cooldown window
dates whose forward window overlaps the event forward window
```

### Report two aggregation methods

Produce:

```text
event_weighted_result
asset_equal_weighted_result
```

Do not average ticker-level baseline means without considering different event counts unless the report explicitly labels the result as asset-equal-weighted.

The current implementation uses a dominant regime and later averages ticker baseline values equally, while the event metrics are pooled across events.

---

## 10. Separate target assets from reference assets

The current pipeline concatenates:

```text
argentina.tickers
reference.tickers
```

and runs event detection across both groups.

Reference assets must not automatically become research targets.

Use:

```yaml
targets:
  - ticker: GGAL.BA
    market: argentina
  - ticker: YPFD.BA
    market: argentina

references:
  - ticker: SPY
    role: global_benchmark
  - ticker: QQQ
    role: technology_benchmark
  - ticker: EWZ
    role: regional_benchmark
  - ticker: ARGT
    role: argentina_usd_reference
```

Default behavior:

```text
Detect events only in targets.
Use references for regimes, relative strength and baseline comparisons.
```

Allow cross-market experiments only when explicitly configured.

The current universe configuration distinguishes Argentine and reference instruments, but `run_experiment.py` merges both lists before loading and event detection.

---

## 11. Use trading-session cooldowns

The current cooldown compares calendar-day differences:

```python
(current_date - last_event_date).days
```

The specification refers to trading-day horizons.

Implement cooldown using DataFrame row positions:

```text
keep event if current_position - last_kept_position >= cooldown_sessions
```

Rename the field:

```yaml
cooldown_sessions: 20
```

Default it to:

```text
maximum forward horizon
```

A 10-session cooldown must mean 10 actual market sessions, regardless of weekends or holidays.

The current cooldown implementation uses calendar days.

---

# P1 — Robustness corrections

## 12. Fix leave-one-asset-out calculations

The current implementation combines returns from all horizons into one array and then assigns the same combined mean and observation count to every horizon.

Each horizon must be calculated independently:

```text
excluded_ticker
horizon
n_events
mean_net_return
median_net_return
incremental_edge_net
```

Do not reuse one combined return vector for all horizons.

---

## 13. Fix leave-one-year-out

Do not remove an entire year from the DataFrame and then calculate forward returns on the shortened DataFrame.

Removing rows creates artificial adjacency between:

```text
December of the previous year
January of the following year
```

A forward return may incorrectly jump across the deleted year as though those sessions were consecutive.

Correct approach:

1. Keep the original continuous price series.
2. Detect and calculate events normally.
3. Exclude event records whose `signal_date` belongs to the omitted year.
4. Optionally exclude trades whose holding window intersects the omitted year.
5. Recalculate metrics from the filtered event table.

The current implementation removes the year from each DataFrame before calculating returns.

---

## 14. Calculate robustness per horizon

The following must be produced independently for each horizon:

```text
bootstrap confidence interval
leave-one-asset-out
leave-one-year-out
profit concentration
parameter neighborhood
```

Do not combine 1-day, 3-day, 5-day, 10-day and 20-day outcomes into the same profit-concentration calculation.

The same event at several horizons is not several independent trades.

Use one selected research horizon for decision-making, or clearly treat each horizon as a separate hypothesis.

---

## 15. Implement parameter-neighborhood validation in the pipeline

A `parameter_neighborhood()` helper exists, but it is not included in `run_all_robustness()`.

For EXP-001 test at least:

```text
60-day return threshold:
5%, 10%, 15%

pullback upper bound:
-2%, -3%, -4%

pullback lower bound:
-6%, -7%, -8%

SMA trend filter:
SMA100, SMA150, SMA200
```

Do not search for the best combination.

The output must show whether the result forms a stable plateau around the original hypothesis.

---

# P1 — Data and reporting requirements

## 16. Use adjusted prices consistently

Raw close prices can contain artificial jumps caused by splits, dividends or corporate actions.

Use adjusted close for return-based features whenever available.

For OHLC excursion calculations, derive adjusted OHLC:

```python
adjustment_factor = adj_close / close

open_adj = open * adjustment_factor
high_adj = high * adjustment_factor
low_adj = low * adjustment_factor
close_adj = adj_close
```

Then apply currency conversion.

Store both raw and adjusted columns.

---

## 17. Do not trust ticker-only cache files

The current cache key is based only on the ticker.

A cached file may be reused even when:

```text
requested start date changed
requested end date changed
cached data is stale
source changed
adjustment settings changed
```

Cache metadata must include:

```text
ticker
source
requested_start
requested_end
downloaded_at
last_available_date
auto_adjust setting
```

When reading cache:

* Slice it to the requested interval.
* Refresh missing dates.
* Reject an incomplete cache when required data is unavailable.

---

## 18. Preserve ticker identity in event output

The combined event DataFrames currently do not reliably preserve the ticker when concatenated.

Every event row must contain:

```text
experiment_id
ticker
market
signal_date
entry_date
exit_date
horizon
trend_regime
volatility_regime
signal_price
entry_price
exit_price
gross_return_pct
transaction_cost_pct
net_return_pct
matched_baseline_pct
incremental_edge_net_pct
mfe_pct
mae_pct
temporal_split
```

Without ticker identity, asset-level robustness and manual auditing are unreliable.

---

## 19. Make output match the specification

The specification requires:

```text
summary.md
metrics.csv
events.csv
robustness.csv
metadata.json
charts/
```

The current code writes `metrics.json`, not `metrics.csv`.

Produce both if JSON is useful:

```text
metrics.csv
metrics.json
```

Metadata must include:

```text
git commit hash
complete event configuration
universe configuration
cost configuration
CCL source
ADR ratios
data-source versions
execution model
random seed
run timestamp
code version
split boundaries
holdout status
```

---

# Decision-engine correction

## 20. Rewrite `make_decision()`

The current decision engine does not fully enforce the documented criteria.

It must receive:

```text
metrics_by_split
baseline_metrics
robustness_by_horizon
cost_metrics
concentration_metrics
asset_consistency
parameter_neighborhood
```

Do not select the best horizon after looking at all horizons and then treat it as a predeclared hypothesis.

Each horizon must have its own decision, or one primary horizon must be declared in YAML before execution:

```yaml
research:
  primary_horizon: 5
  secondary_horizons: [1, 3, 10, 20]
```

Primary CANDIDATE criteria:

```text
At least 60 independent full-sample events
Adequate validation and holdout event counts
Positive validation net median
Positive holdout net median
Positive holdout incremental edge
Positive asset-equal-weighted result
At least 60% of target assets positive
At least 60% of time subperiods positive
Bootstrap interval acceptable
No single trade explains more than 20% of total net profit
No single asset dominates the result
Nearby parameters preserve the sign and reasonable magnitude
Break-even cost >= 1.5 × estimated cost
```

Use median net return and incremental edge as core metrics, not only gross mean return.

The current decision implementation selects the best gross mean after subtracting a generic cost and does not consume temporal-split or baseline results.

---

# Mandatory regression tests

Add deterministic tests for all of the following:

```text
1. Correct 1-day and N-day forward-return formula.
2. Baseline uses the same return formula as event returns.
3. Signal confirmed at close enters at next session open.
4. Same-close entry is disabled by default.
5. MFE uses adjusted high.
6. MAE uses adjusted low.
7. Correct ADR/CCL formula.
8. "GGAL" resolves to the US ADR, not GGAL.BA.
9. Missing CCL causes a hard failure for Argentine assets.
10. CCL is never backfilled with future values.
11. Argentine features use USD-adjusted prices.
12. EXP-001 includes -5% and excludes -2% and -8%.
13. Transaction costs are deducted per event.
14. US and Argentine instruments use different cost models.
15. Negative holdout prevents CANDIDATE.
16. Positive full sample with negative holdout is rejected.
17. Reference instruments do not generate events by default.
18. Cooldown counts trading sessions.
19. Leave-one-asset-out metrics differ by horizon when returns differ.
20. Leave-one-year-out does not create returns across removed years.
21. Profit concentration is calculated per horizon.
22. Ticker identity survives event concatenation.
23. Cache refreshes when requested dates exceed cached coverage.
24. No feature or return uses future information.
```

Do not modify expected values merely to make existing code pass.

---

# Required execution order

Implement corrections in this order:

```text
1. Shared forward-return function.
2. Execution timing and adjusted OHLC.
3. CCL and ticker-metadata correction.
4. Hard-currency feature calculation.
5. EXP-001 bounded-condition support.
6. Per-event transaction costs.
7. Operational temporal split.
8. Correct matched baselines.
9. Target/reference separation.
10. Robustness corrections.
11. Decision-engine rewrite.
12. Reporting and documentation synchronization.
```

---

# Required final deliverables

Before implementing EXP-002, deliver:

```text
1. Corrected source code.
2. Updated tests.
3. Full pytest output.
4. Updated AGENTS.md.
5. Updated README.md.
6. Clean EXP-001 rerun.
7. New results/exp_001/ artifacts.
8. Comparison between old and corrected EXP-001 results.
9. Explicit statement that the old EXP-001 result is superseded.
10. Known-limitations document.
```

The comparison report must show:

```text
Old event count
Corrected event count
Old gross returns
Corrected gross returns
Corrected net returns
Discovery result
Validation result
Holdout result
Baseline edge
Parameter-neighborhood stability
Asset-level consistency
Final corrected decision
```

Do not claim that EXP-001 is `RESEARCH` or `CANDIDATE` until the corrected pipeline has completed from a clean cache and all mandatory tests pass.

The next milestone is not EXP-002.

The next milestone is:

> Produce one trustworthy, reproducible and execution-realistic EXP-001 result.

