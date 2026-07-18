"""
baseline_comparator.py — Statistical Edge Lab
Phase 3: Compare event returns against three baselines.

Audit P0 #1: Uses shared forward_return_series().
Audit P0 #9: Per-event regime matching, no dominant-regime shortcut.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from forward_returns import forward_return_series

logger = logging.getLogger(__name__)


def unconditional_baseline(
    df: pd.DataFrame,
    horizon: int,
    price_col: str = "close_usd",
) -> float:
    """
    Baseline 1: Average forward return of ALL eligible dates (no event required).

    Uses shared forward_return_series() to match event-return calculation.
    """
    fr = forward_return_series(df[price_col], horizon).dropna()
    if len(fr) == 0:
        return 0.0
    return float(fr.mean())


def exact_matched_baseline(
    df: pd.DataFrame,
    horizon: int,
    trend_regime: str,
    vol_regime: str,
    price_col: str = "close_usd",
    trend_col: str = "trend_regime",
    vol_col: str = "vol_regime",
    event_dates: Optional[set] = None,
    cooldown_sessions: int = 10,
) -> tuple[float, int, str]:
    """
    Q4 baseline: Average forward return during dates with the EXACT SAME
    trend_regime AND volatility_regime, excluding event dates and cooldown.

    Returns:
        (baseline_return_pct, n_controls, status)
        status: 'VALID' (n>=20), 'LOW_CONFIDENCE' (5<=n<20), 'INSUFFICIENT' (n<5)
    """
    fr = forward_return_series(df[price_col], horizon)

    # Filter by BOTH regimes
    in_regime = (df[trend_col] == trend_regime) & (df[vol_col] == vol_regime)

    # Exclude event dates + cooldown window
    if event_dates is not None:
        exclude_mask = pd.Series(False, index=df.index)
        for ed in event_dates:
            if ed in df.index:
                ed_idx = df.index.get_loc(ed)
                start = max(0, ed_idx - cooldown_sessions)
                end = min(len(df), ed_idx + cooldown_sessions + horizon)
                exclude_mask.iloc[start:end] = True
        in_regime = in_regime & ~exclude_mask

    valid = fr[in_regime].dropna()
    n_controls = len(valid)

    if n_controls >= 20:
        status = "VALID"
    elif n_controls >= 5:
        status = "LOW_CONFIDENCE"
    else:
        status = "INSUFFICIENT"

    baseline_return = float(valid.mean()) if n_controls > 0 else 0.0
    return baseline_return, n_controls, status


def regime_conditioned_baseline(
    df: pd.DataFrame,
    horizon: int,
    regime_column: str = "trend_regime",
    regime_value: str = "BULL",
    price_col: str = "close_usd",
    event_dates: Optional[set] = None,
    cooldown_sessions: int = 10,
) -> float:
    """
    Baseline 2 (legacy, trend-only): Average forward return during dates with
    the SAME trend_regime, excluding event dates and cooldown.

    Kept as diagnostic fallback per Q4. Not used for primary decision.
    """
    fr = forward_return_series(df[price_col], horizon)

    # Filter by regime
    in_regime = df[regime_column] == regime_value

    # Exclude event dates + cooldown window
    if event_dates is not None:
        exclude_mask = pd.Series(False, index=df.index)
        for ed in event_dates:
            if ed in df.index:
                ed_idx = df.index.get_loc(ed)
                start = max(0, ed_idx - cooldown_sessions)
                end = min(len(df), ed_idx + cooldown_sessions + horizon)
                exclude_mask.iloc[start:end] = True
        in_regime = in_regime & ~exclude_mask

    valid = fr[in_regime].dropna()
    if len(valid) == 0:
        return 0.0
    return float(valid.mean())


def benchmark_baseline(
    benchmark: pd.DataFrame,
    event_dates: list[pd.Timestamp],
    horizon: int,
    price_col: str = "close",
) -> float:
    """
    Baseline 3: Benchmark return over the SAME dates and forward horizon.

    Uses shared forward_return_series().
    """
    fr = forward_return_series(benchmark[price_col], horizon)

    aligned = fr.reindex(pd.DatetimeIndex(event_dates), method=None).dropna()
    if len(aligned) == 0:
        return 0.0
    return float(aligned.mean())


def compute_all_baselines(
    asset_df: pd.DataFrame,
    event_dates: list[pd.Timestamp],
    horizons: list[int],
    benchmark_df: Optional[pd.DataFrame] = None,
    price_col: str = "close_usd",
    cooldown_sessions: int = 10,
    trend_col: str = "trend_regime",
    vol_col: str = "vol_regime",
) -> dict[int, dict]:
    """
    Compute all baselines for all horizons, using exact trend+vol matching (Q4).

    Each event is matched against control observations with the SAME
    (trend_regime, vol_regime). Pool status is tracked per event.

    Returns dict[horizon -> {
        'unconditional': float,
        'exact_matched_mean': float,
        'exact_matched_median': float,
        'benchmark': float,
        'trend_only_fallback_mean': float,
        'trend_only_fallback_median': float,
        'baseline_coverage': {
            'n_events': int,
            'n_valid': int,
            'n_low_confidence': int,
            'n_insufficient': int,
            'valid_pct': float,
            'valid_or_low_pct': float,
        },
        'per_event_details': [
            {'event_date': ..., 'trend_regime': ..., 'vol_regime': ...,
             'matched_return': ..., 'n_controls': ..., 'status': ...,
             'trend_only_return': ...},
        ],
        'per_event_regime': dict — regime breakdown
    }]
    """
    event_set = set(event_dates)

    # Get regimes for each event date
    event_regimes = {}
    event_vol_regimes = {}
    for ed in event_dates:
        if ed in asset_df.index:
            if trend_col in asset_df.columns:
                event_regimes[ed] = asset_df.loc[ed, trend_col]
            if vol_col in asset_df.columns:
                event_vol_regimes[ed] = asset_df.loc[ed, vol_col]

    results = {}
    for h in horizons:
        per_event = []

        for ed in event_dates:
            trend_r = event_regimes.get(ed, "NEUTRAL")
            vol_r = event_vol_regimes.get(ed, "NORMAL_VOL")

            # Primary: exact trend + vol matching
            match_ret, n_ctrl, status = exact_matched_baseline(
                asset_df, h, trend_r, vol_r, price_col,
                trend_col, vol_col, event_set, cooldown_sessions
            )

            # Diagnostic: trend-only fallback
            trend_only_ret = regime_conditioned_baseline(
                asset_df, h, trend_col, trend_r, price_col,
                event_set, cooldown_sessions
            )

            per_event.append({
                "event_date": ed,
                "trend_regime": trend_r,
                "vol_regime": vol_r,
                "matched_return": match_ret,
                "n_controls": n_ctrl,
                "status": status,
                "trend_only_return": trend_only_ret,
            })

        # Aggregate matched baseline (only VALID + LOW_CONFIDENCE)
        valid_events = [e for e in per_event if e["status"] != "INSUFFICIENT"]
        matched_vals = [e["matched_return"] for e in valid_events]
        trend_only_vals = [e["trend_only_return"] for e in valid_events]

        # Coverage stats
        n_total = len(per_event)
        n_valid = sum(1 for e in per_event if e["status"] == "VALID")
        n_low = sum(1 for e in per_event if e["status"] == "LOW_CONFIDENCE")
        n_insuf = sum(1 for e in per_event if e["status"] == "INSUFFICIENT")

        bl = {
            "unconditional": unconditional_baseline(asset_df, h, price_col),
            "exact_matched_mean": float(np.mean(matched_vals)) if matched_vals else 0.0,
            "exact_matched_median": float(np.median(matched_vals)) if matched_vals else 0.0,
            "trend_only_fallback_mean": float(np.mean(trend_only_vals)) if trend_only_vals else 0.0,
            "trend_only_fallback_median": float(np.median(trend_only_vals)) if trend_only_vals else 0.0,
            "baseline_coverage": {
                "n_events": n_total,
                "n_valid": n_valid,
                "n_low_confidence": n_low,
                "n_insufficient": n_insuf,
                "valid_pct": round(n_valid / n_total * 100, 1) if n_total else 0.0,
                "valid_or_low_pct": round((n_valid + n_low) / n_total * 100, 1) if n_total else 0.0,
            },
            "per_event_details": per_event,
        }

        if benchmark_df is not None:
            bl["benchmark"] = benchmark_baseline(benchmark_df, event_dates, h)
        else:
            bl["benchmark"] = 0.0

        # Regime breakdown
        regime_counts = {}
        for ed in event_dates:
            r = event_regimes.get(ed, "NEUTRAL")
            vr = event_vol_regimes.get(ed, "NORMAL_VOL")
            key = f"{r}+{vr}"
            regime_counts[key] = regime_counts.get(key, 0) + 1
        bl["per_event_regime"] = regime_counts

        results[h] = bl

    return results


def incremental_edge(
    event_mean_return: float,
    baseline_return: float,
) -> float:
    """Edge = event return - baseline return."""
    return event_mean_return - baseline_return
