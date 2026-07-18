"""
baseline_comparator.py — Statistical Edge Lab
Phase 3: Compare event returns against three baselines.

Spec §11:
  Baseline 1: Unconditional return (same asset, same horizon)
  Baseline 2: Regime-conditioned return (same regime, no event)
  Baseline 3: Benchmark return (same dates, same horizon)
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def unconditional_baseline(
    df: pd.DataFrame,
    horizon: int,
    price_col: str = "close_usd",
) -> float:
    """
    Baseline 1: Average return of ALL eligible dates (no event required).

    Returns mean forward return for the asset over the given horizon.
    """
    prices = df[price_col]
    forward_returns = prices.pct_change(periods=-horizon).shift(-horizon) * 100
    # Exclude NaN
    valid = forward_returns.dropna()
    if len(valid) == 0:
        return 0.0
    return float(valid.mean())


def regime_conditioned_baseline(
    df: pd.DataFrame,
    horizon: int,
    regime_column: str = "trend_regime",
    regime_value: str = "BULL",
    price_col: str = "close_usd",
    event_dates: Optional[set] = None,
) -> float:
    """
    Baseline 2: Average forward return during dates with the SAME market regime,
    EXCLUDING event dates.

    This isolates whether the event adds value beyond just being in that regime.
    """
    prices = df[price_col]
    forward_returns = prices.pct_change(periods=-horizon).shift(-horizon) * 100

    # Filter by regime
    in_regime = df[regime_column] == regime_value

    # Exclude event dates
    if event_dates is not None:
        event_mask = pd.Series(False, index=df.index)
        event_mask[list(event_dates)] = True
        in_regime = in_regime & ~event_mask

    valid = forward_returns[in_regime].dropna()
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

    Returns mean benchmark forward return aligned to event dates.
    """
    prices = benchmark[price_col]
    forward_returns = prices.pct_change(periods=-horizon).shift(-horizon) * 100

    # Align to event dates
    aligned = forward_returns.reindex(
        pd.DatetimeIndex(event_dates), method=None
    ).dropna()

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
) -> dict[int, dict]:
    """
    Compute all three baselines for all horizons.

    Returns dict[horizon -> {
        'unconditional': float,
        'regime_conditioned': float,
        'benchmark': float,
    }]
    """
    event_set = set(event_dates)
    # Get dominant regime at event dates
    dominant_regimes = []
    for ed in event_dates:
        if ed in asset_df.index and regime_column in asset_df.columns:
            dominant_regimes.append(asset_df.loc[ed, regime_column])
    dominant_regime = max(set(dominant_regimes), key=dominant_regimes.count) if dominant_regimes else "BULL"

    results = {}
    for h in horizons:
        bl = {
            "unconditional": unconditional_baseline(asset_df, h, price_col),
            "regime_conditioned": regime_conditioned_baseline(
                asset_df, h, regime_column, dominant_regime, price_col, event_set
            ),
        }
        if benchmark_df is not None:
            bl["benchmark"] = benchmark_baseline(benchmark_df, event_dates, h)
        else:
            bl["benchmark"] = 0.0
        results[h] = bl

    return results


def incremental_edge(
    event_mean_return: float,
    baseline_return: float,
) -> float:
    """Edge = event return - baseline return."""
    return event_mean_return - baseline_return
