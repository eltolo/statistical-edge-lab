# Preguntas al Auditor — Respuestas definitivas

**Repository:** `eltolo/statistical-edge-lab`  
**Branch reviewed:** `main`  
**Reviewed HEAD:** `d86e47a`  
**Relevant code revision:** `945f8da`  
**Purpose:** Close the implementation questions raised after `auditoria_2.md`.

These answers are normative. Implement them as written and do not choose alternative interpretations without documenting a new design decision.

---

## 1. Next-open horizon semantics

### Question

For `horizon=1`, should the trade enter at the open of `t+1` and exit at the close of `t+1`, or at the close of `t+2`?

### Decision

For this project:

```text
horizon = number of trading sessions in which the position is held
```

Therefore:

```text
Signal confirmed: close of t
Entry: open of t+1
horizon=1 exit: close of t+1
horizon=3 exit: close of t+3
horizon=5 exit: close of t+5
```

The correct implementation is:

```python
exit_idx = entry_idx + horizon - 1
```

A trade entered at the open and closed at the close of the same session has one session of market exposure. The fact that the entry and exit are in the same DataFrame row does not mean the holding period is zero.

The current implementation still uses:

```python
exit_idx = entry_idx + horizon
```

That makes every next-open trade one session longer than declared.

### Required implementation

```python
if horizon < 1:
    raise ValueError("horizon must be >= 1")

entry_idx = signal_idx + 1
exit_idx = entry_idx + horizon - 1
```

Also rename internal concepts where useful:

```text
forward_horizons → holding_sessions
```

The YAML field may remain `forward_horizons` for compatibility, but its documented meaning must be “number of held trading sessions.”

### Required tests

```text
horizon=1 → open t+1 to close t+1
horizon=2 → open t+1 to close t+2
horizon=5 → open t+1 to close t+5
```

---

## 2. `close_breaks_high_20d`

### Question

Is this calculation correct?

```python
close > high.rolling(20).max().shift(1)
```

### Decision

Yes. It is correct for the intended breakout definition.

At session `t`, the expression compares:

```text
current close at t
```

against:

```text
maximum high from the previous 20 completed sessions
```

The `.shift(1)` is required because it excludes the current session from the reference high.

Use:

```python
previous_20_session_high = high.rolling(20).max().shift(1)
close_breaks_high_20d = close > previous_20_session_high
```

Do not compare against a rolling maximum that includes the current session. Since:

```text
close[t] <= high[t]
```

including the current high would make a strict close breakout impossible whenever the current session sets the maximum.

### Additional requirement

For Argentine assets, both series must use the same adjusted USD price domain:

```text
close_usd_adjusted
high_usd_adjusted
```

Do not compare an adjusted close against an unadjusted high, or a USD close against an ARS high.

### Required tests

```text
Current close above every high from t-20 through t-1 → True
Current close equal to previous 20-session high → False with strict ">"
Current high makes a new high but close remains below old maximum → False
Current session must not be included in the reference maximum
```

---

## 3. Trades crossing temporal split boundaries

### Question

If the signal belongs to discovery but the entry or exit falls in validation, should the trade be discarded or assigned by majority?

### Decision

Discard it from all formal split metrics.

Never assign a boundary-crossing trade by majority.

A trade is eligible for a temporal partition only when all of the following belong to the same partition:

```text
signal_date
entry_date
exit_date
```

For example:

```text
signal_date = discovery
entry_date = discovery
exit_date = validation
```

Result:

```text
exclude from discovery
exclude from validation
exclude from holdout
classification = boundary_crossing
```

Majority assignment is arbitrary and allows one partition to consume price information from another partition.

### Required implementation

First calculate the full canonical trade table, including actual entry and exit dates.

Then assign:

```python
def assign_trade_split(signal_date, entry_date, exit_date, splitter):
    periods = {
        splitter.get_period(signal_date),
        splitter.get_period(entry_date),
        splitter.get_period(exit_date),
    }

    if len(periods) != 1:
        return "boundary_crossing"

    return periods.pop()
```

Exclude `boundary_crossing` from:

```text
discovery metrics
validation metrics
holdout metrics
decision engine
bootstrap by split
```

Keep those rows in a diagnostic artifact so the exclusion is auditable.

### Preferred additional protection

Apply an embargo around each boundary equal to:

```text
maximum holding horizon + one entry session
```

However, even with an embargo, the actual trade dates must still be checked.

---

## 4. Insufficient matched-baseline controls

### Question

What should happen when the exact `trend_regime + volatility_regime` control pool is too small?

### Decision

Do not silently replace the primary matched baseline with a weaker one.

Use the following hierarchy:

```text
Exact primary match:
same ticker
same trend regime
same volatility regime
same execution model
non-overlapping control window
```

Control-pool classification:

```text
n_controls >= 20 → VALID
5 <= n_controls < 20 → LOW_CONFIDENCE
n_controls < 5 → INSUFFICIENT
```

For `INSUFFICIENT`:

- Keep the event in raw event-return statistics.
- Do not calculate a primary matched incremental edge for that event.
- Mark `baseline_status = INSUFFICIENT`.
- Exclude that event from the primary matched-edge aggregation.
- Report matched-baseline coverage.

Do not discard the event from the entire study merely because its baseline is unavailable.

### Secondary diagnostic fallback

A trend-only baseline may be calculated as a separate diagnostic:

```text
fallback_baseline = same trend regime, any volatility regime
```

But it must be labeled:

```text
secondary_trend_only_baseline
```

It must not replace the exact primary baseline when making a `CANDIDATE` decision.

### Candidate coverage requirement

For the primary horizon, require:

```text
at least 80% of evaluated events have VALID or LOW_CONFIDENCE exact matched baselines
```

Additionally:

```text
at least 50% should have VALID pools with n_controls >= 20
```

If coverage is lower, the maximum decision is:

```text
RESEARCH
```

even if the available matched edge is positive.

### Important correction to current code

The current baseline implementation matches only `trend_regime`. It must be extended to match both:

```text
trend_regime
volatility_regime
```

---

## 5. Minimum valid futures paper trading

### Question

Is a real ROFEX connection required, is a cash-plus-estimated-basis simulation sufficient, or should the existing low-cost version remain only a sensitivity analysis?

### Decision

The existing implementation must remain labeled:

```text
LOW-COST EXECUTION SENSITIVITY ANALYSIS
```

It is not valid futures paper trading.

Changing only commission and slippage assumptions does not model the tradable futures instrument.

### Minimum acceptable futures paper trader

A valid futures paper-trading engine requires actual market data for the tradable contract.

A direct ROFEX API connection is not mandatory if another reliable source provides actual contract quotes. Acceptable sources may include:

```text
broker API
market data collector
historical contract files
Matriz feed
ROFEX/Matba market data
```

The minimum required data and logic are:

```text
actual contract symbol
contract expiry
contract multiplier
bid
ask
last price
quote timestamp
volume
open interest when available
margin requirement
contract-specific fees
entry and exit fill rules
expiry handling
roll rule
daily settlement / mark-to-market
```

The signal may still originate from the cash asset.

Example:

```text
Signal source: GGAL.BA
Execution instrument: actual GGAL futures contract
```

But returns and fills must be calculated from actual futures quotes.

### Classification of the three options

```text
(a) Actual futures quotes through ROFEX, broker, Matriz, or equivalent:
    VALID minimum path.

(b) Cash price + estimated basis:
    research prototype only.
    Not valid paper trading.

(c) Cash signal + futures-like costs:
    low-cost sensitivity analysis only.
    Not valid paper trading.
```

### Minimum fill model

For a long paper trade:

```text
entry = executable ask at or after signal execution time
exit = executable bid at exit time
```

For a short paper trade:

```text
entry = executable bid
exit = executable ask
```

Using only last price is insufficient for execution validation.

---

## 6. Parameter neighborhood for EXP-005

### Question

Should the neighborhood vary only the z-score threshold, or also the rolling window?

### Decision

Test both, but in two controlled stages.

Do not immediately perform an unrestricted Cartesian optimization.

The declared primary hypothesis remains:

```text
z-score threshold = -2.00
z-score window = 60 sessions
primary horizon = 10 sessions
```

### Stage A — Threshold sensitivity

Keep the window fixed at 60:

```text
-1.75
-2.00
-2.25
```

Purpose:

```text
Determine whether the result is stable around the selected threshold.
```

### Stage B — Window sensitivity

Keep the threshold fixed at `-2.00`:

```text
40 sessions
60 sessions
80 sessions
```

Purpose:

```text
Determine whether the result depends on one exact lookback window.
```

### Optional Stage C — Small robustness surface

After Stages A and B, a predeclared `3 × 3` matrix may be reported:

```text
thresholds = [-1.75, -2.00, -2.25]
windows = [40, 60, 80]
```

This matrix is diagnostic only.

Do not:

- Select the best cell.
- Change the primary hypothesis after observing the holdout.
- Reclassify a failed primary configuration because a neighboring cell performed better.

### Desired result

Look for a plateau:

```text
same sign
similar magnitude
reasonable event counts
consistent behavior across adjacent settings
```

Do not require every cell to pass, but reject a result that works only at one isolated coordinate.

---

## 7. Cache policy before the corrected rerun

### Question

Should all raw data be deleted and downloaded again, or should the cache be validated and refreshed?

### Decision for the next corrected rerun

Use:

```text
DELETE OR ARCHIVE CURRENT CACHE + FRESH DOWNLOAD
```

Reason:

The current cache implementation is ticker-based and does not validate:

```text
requested start date
requested end date
download timestamp
last available session
source options
adjustment settings
content hash
```

Therefore, the current cache cannot prove that it is complete or compatible with the corrected pipeline.

Recommended procedure:

```bash
mv data/raw data/raw_pre_audit2_backup
mkdir -p data/raw
```

Then perform a complete fresh download.

Do not mix pre-audit cache files with the corrected official rerun.

### Policy after cache metadata is implemented

Normal future behavior should be:

```text
VALIDATE + REFRESH
```

not delete everything on every run.

Each cache artifact must store metadata such as:

```json
{
  "ticker": "GGAL.BA",
  "source": "yfinance",
  "requested_start": "2015-01-01",
  "requested_end": "2026-07-17",
  "downloaded_at": "...",
  "first_available_date": "...",
  "last_available_date": "...",
  "auto_adjust": false,
  "schema_version": "...",
  "content_sha256": "..."
}
```

The loader should:

1. Verify coverage.
2. Verify schema and adjustment settings.
3. Refresh missing leading or trailing periods.
4. Fail if required coverage remains incomplete.
5. Record cache hashes in experiment metadata.

### Final rule

```text
First official post-audit rerun:
fresh download.

Subsequent normal runs:
validate + incremental refresh.
```

---

## 8. Synchronizing `AGENTS.md`

### Question

Should `AGENTS.md` be generated automatically after every commit, or updated manually at milestone completion?

### Decision

Manual milestone updates are sufficient.

Do not regenerate the entire `AGENTS.md` file after every commit.

Use this division of responsibility:

```text
AGENTS.md
→ stable operational guide
→ architecture
→ rules
→ current milestone status
→ manually updated at milestone closure

metadata.json / status.json
→ exact machine-generated run state
→ commit hash
→ tests
→ experiment decisions
→ generated for every official run
```

### Required workflow

At the end of each milestone:

1. Run the complete test suite.
2. Generate experiment metadata.
3. Verify repository artifacts.
4. Update `AGENTS.md` manually.
5. Update `README.md`.
6. Commit documentation and generated status together.

### Recommended drift check

Add a small CI or local validation script that fails when obvious contradictions exist.

Example checks:

```text
README says EXP-001 complete but no result metadata exists
AGENTS says module not implemented but source file is operational
README decision differs from metadata.json
reported test count differs from pytest collection
```

The script may generate:

```text
results/project_status.json
```

But it should not rewrite narrative documentation automatically.

### Current repository correction

The current `AGENTS.md` marks all modules and experiments as unimplemented, while the repository contains implemented modules and the README claims EXP-001 is complete.

Update both documents at the next milestone closure, after the corrected rerun—not before.

---

# Final implementation decisions

```text
Q1  horizon=1 means next open to same-session close.
Q2  close > prior 20-session high with shift(1) is correct.
Q3  discard every trade crossing a split boundary.
Q4  exact trend+volatility baseline is primary; insufficient pools are flagged, not silently replaced.
Q5  valid futures paper trading requires actual futures contract quotes and execution.
Q6  test threshold and window separately, then optionally show a fixed 3×3 robustness surface.
Q7  fresh download for the next official rerun; validate+refresh after metadata support exists.
Q8  update AGENTS.md manually at milestone closure; machine-generate status metadata and use a drift check.
```

---

# Immediate next actions

Implement in this order:

```text
1. Correct next-open horizon indexing.
2. Include the entry session in MFE/MAE.
3. Add boundary-crossing purge logic.
4. Extend matched baselines to trend + volatility regime.
5. Add baseline pool status and coverage metrics.
6. Implement cache metadata and coverage validation.
7. Archive/delete the current raw cache.
8. Perform a clean data download.
9. Execute corrected EXP-005 using its declared primary configuration.
10. Update AGENTS.md and README.md only after tests and artifacts are complete.
```
