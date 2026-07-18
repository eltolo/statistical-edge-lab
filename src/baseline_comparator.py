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
    Baseline 2: Average forward return during dates with the SAME market regime,
    EXCLUDING event dates and their cooldown windows.

    Audit P0 #9: Per-event regime matching (no dominant regime shortcut).
    Audit: Excludes cooldown window to prevent baseline contamination.
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
    regime_column: str = "trend_regime",
    price_col: str = "close_usd",
    cooldown_sessions: int = 10,
) -> dict[int, dict]:
    """
    Compute all three baselines for all horizons.

    Audit P0 #9: Each event's baseline uses its own regime,
    not a dominant regime averaged across all events.

    Returns dict[horizon -> {
        'unconditional': float,
        'regime_conditioned': float,
        'benchmark': float,
        'per_event_regime': dict — regime breakdown
    }]
    """
    event_set = set(event_dates)

    # Get regime for each event date (per-event matching)
    event_regimes = {}
    for ed in event_dates:
        if ed in asset_df.index and regime_column in asset_df.columns:
            event_regimes[ed] = asset_df.loc[ed, regime_column]

    results = {}
    for h in horizons:
        # Regime-conditioned: use each event's own regime
        regime_vals = []
        for ed in event_dates:
            regime = event_regimes.get(ed, "NEUTRAL")
            rv = regime_conditioned_baseline(
                asset_df, h, regime_column, regime, price_col,
                event_set, cooldown_sessions
            )
            regime_vals.append(rv)

        bl = {
            "unconditional": unconditional_baseline(asset_df, h, price_col),
            "regime_conditioned": float(np.mean(regime_vals)) if regime_vals else 0.0,
            "regime_conditioned_median": float(np.median(regime_vals)) if regime_vals else 0.0,
        }

        if benchmark_df is not None:
            bl["benchmark"] = benchmark_baseline(benchmark_df, event_dates, h)
        else:
            bl["benchmark"] = 0.0

        # Regime breakdown
        regime_counts = {}
        for r in event_regimes.values():
            regime_counts[r] = regime_counts.get(r, 0) + 1
        bl["per_event_regime"] = regime_counts

        results[h] = bl

    return results


def incremental_edge(
    event_mean_return: float,
    baseline_return: float,
) -> float:
    """Edge = event return - baseline return."""
    return event_mean_return - baseline_return
