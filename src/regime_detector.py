"""
regime_detector.py — Statistical Edge Lab
Phase 3: Classify market regime (BULL/BEAR/NEUTRAL + volatility).

Spec §12:
  BULL: benchmark > SMA200 and SMA200 slope > 0
  BEAR: benchmark < SMA200 and SMA200 slope < 0
  NEUTRAL: all remaining cases

  Vol regimes: LOW_VOL / NORMAL_VOL / HIGH_VOL (ATR percentiles)
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def classify_trend_regime(
    benchmark_series: pd.Series,
    sma_200: Optional[pd.Series] = None,
    sma_200_slope: Optional[pd.Series] = None,
) -> pd.Series:
    """
    Classify each date as BULL, BEAR, or NEUTRAL.

    Args:
        benchmark_series: Benchmark price series
        sma_200: Pre-computed SMA200 (computed if None)
        sma_200_slope: Pre-computed SMA200 slope (computed if None)

    Returns:
        Series of strings: 'BULL', 'BEAR', 'NEUTRAL'
    """
    if sma_200 is None:
        sma_200 = benchmark_series.rolling(window=200).mean()
    if sma_200_slope is None:
        sma_200_slope = sma_200.diff(periods=20) / 20

    regime = pd.Series("NEUTRAL", index=benchmark_series.index)

    bull_mask = (benchmark_series > sma_200) & (sma_200_slope > 0)
    bear_mask = (benchmark_series < sma_200) & (sma_200_slope < 0)

    # Need at least 200 days of data for SMA200
    regime.iloc[:200] = "NEUTRAL"
    regime[bull_mask] = "BULL"
    regime[bear_mask] = "BEAR"

    return regime


def classify_volatility_regime(
    df: pd.DataFrame,
    atr_column: str = "atr_14",
) -> pd.Series:
    """
    Classify each date as LOW_VOL, NORMAL_VOL, or HIGH_VOL.

    Uses historical percentiles of ATR:
      - LOW_VOL: ATR percentile < 25
      - HIGH_VOL: ATR percentile > 75
      - NORMAL_VOL: otherwise
    """
    if atr_column not in df.columns:
        logger.warning(f"ATR column '{atr_column}' not found, using NEUTRAL vol")
        return pd.Series("NORMAL_VOL", index=df.index)

    atr_vals = df[atr_column]

    # Rolling percentile
    def _pct_rank(x):
        v = x.iloc[-1]
        h = x.iloc[:-1]
        if len(h) == 0:
            return 0.5
        return (h < v).sum() / len(h)

    pct = atr_vals.rolling(window=61).apply(_pct_rank, raw=False)

    regime = pd.Series("NORMAL_VOL", index=df.index)
    regime[pct < 0.25] = "LOW_VOL"
    regime[pct > 0.75] = "HIGH_VOL"

    return regime


def get_regime_mask(
    regime_series: pd.Series,
    regime_name: str,
) -> pd.Series:
    """Get boolean mask for a specific regime."""
    return regime_series == regime_name


def compute_all_regimes(
    df: pd.DataFrame,
    benchmark_series: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    Add regime columns to DataFrame.

    Returns DataFrame with added columns:
      trend_regime, vol_regime
    """
    result = df.copy()

    if benchmark_series is not None:
        # Align benchmark to df index
        bench = benchmark_series.reindex(df.index, method="ffill")
        result["trend_regime"] = classify_trend_regime(bench)
    else:
        # Use close as proxy
        result["trend_regime"] = classify_trend_regime(df["close"])

    result["vol_regime"] = classify_volatility_regime(result)

    return result
