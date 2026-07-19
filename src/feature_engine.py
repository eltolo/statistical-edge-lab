"""
feature_engine.py — Statistical Edge Lab
Phase 2: Calculate technical indicators used by event definitions.

Indicators required by spec §18 experiments:
  - SMA (200d, 20d, 60d)
  - Return over N days
  - Volume ratio (vs 20d average)
  - ATR (14d) + percentile over 60d
  - Distance from SMA
  - Z-score of returns
  - Bollinger Bands %b
  - MACD cross
  - RSI (14d)
  - Slope of SMA
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=window).mean()


def rolling_return(series: pd.Series, window: int) -> pd.Series:
    """Return over N periods as a decimal (e.g., 0.05 = 5%)."""
    return series.pct_change(periods=window)


def zscore(series: pd.Series, window: int = 60) -> pd.Series:
    """Rolling z-score."""
    roll_mean = series.rolling(window=window).mean()
    roll_std = series.rolling(window=window).std(ddof=1)
    return (series - roll_mean) / roll_std.replace(0, np.nan)


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Current volume / average volume over window."""
    avg_vol = volume.rolling(window=window).mean()
    return volume / avg_vol.replace(0, np.nan)


def sma_slope(series: pd.Series, sma_window: int, slope_window: int = 20) -> pd.Series:
    """Slope of SMA over slope_window periods (using linear regression)."""
    sma_vals = sma(series, sma_window)
    slope = sma_vals.diff(periods=slope_window) / slope_window
    return slope


def distance_from_sma(series: pd.Series, window: int) -> pd.Series:
    """(price - sma) / sma as decimal."""
    sma_vals = sma(series, window)
    return (series - sma_vals) / sma_vals.replace(0, np.nan)


def percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """Rolling percentile rank of the latest value vs its own history."""
    def _pct_rank(x):
        v = x.iloc[-1]
        h = x.iloc[:-1]
        if len(h) == 0:
            return 0.5
        return (h < v).sum() / len(h)
    return series.rolling(window=window + 1).apply(_pct_rank, raw=False)


def bollinger_b(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.Series:
    """Bollinger Bands %b: (price - lower) / (upper - lower)."""
    sma_vals = sma(series, window)
    std = series.rolling(window=window).std(ddof=1)
    upper = sma_vals + n_std * std
    lower = sma_vals - n_std * std
    b = (series - lower) / (upper - lower).replace(0, np.nan)
    return b


def macd(series: pd.Series) -> pd.DataFrame:
    """MACD: line, signal, histogram."""
    ema_12 = ema(series, 12)
    ema_26 = ema(series, 26)
    macd_line = ema_12 - ema_26
    signal = ema(macd_line, 9)
    histogram = macd_line - signal
    return pd.DataFrame({
        "macd_line": macd_line,
        "macd_signal": signal,
        "macd_hist": histogram,
    })


def high_minus_low(df: pd.DataFrame, window: int = 60) -> pd.Series:
    """Distance from 60-day high as decimal."""
    high_60 = df["high"].rolling(window=window).max()
    return (df["close"] - high_60) / high_60.replace(0, np.nan)


def compute_all_features(
    df: pd.DataFrame,
    price_col: str = "close",
    high_col: str = "high",
    low_col: str = "low",
) -> pd.DataFrame:
    """
    Compute all features used by the 5 experiments.

    Audit P0 #5: Uses configurable price/high/low columns.
    For Argentine assets, pass price_col="close_usd", high_col="high_usd",
    low_col="low_usd" so features are computed in hard currency.

    Returns DataFrame with added feature columns.
    """
    result = df.copy()
    close = result[price_col]

    # Need high/low from the same currency for ATR, distance_to_high
    if high_col in result.columns and low_col in result.columns:
        result["_high"] = result[high_col]
        result["_low"] = result[low_col]
        has_hl = True
    else:
        result["_high"] = close
        result["_low"] = close
        has_hl = False

    # SMAs
    result["sma_20"] = sma(close, 20)
    result["sma_60"] = sma(close, 60)
    result["sma_200"] = sma(close, 200)

    # Returns (in hard currency)
    result["return_1d"] = rolling_return(close, 1)
    result["return_3d"] = rolling_return(close, 3)
    result["return_5d"] = rolling_return(close, 5)
    result["return_10d"] = rolling_return(close, 10)
    result["return_20d"] = rolling_return(close, 20)
    result["return_60d"] = rolling_return(close, 60)

    # RSI
    result["rsi_14"] = rsi(close, 14)

    # ATR (from USD high/low)
    hl_df = pd.DataFrame({"high": result["_high"], "low": result["_low"], "close": close})
    result["atr_14"] = atr(hl_df, 14)
    result["atr_percentile_60d"] = percentile_rank(result["atr_14"], 60)

    # Volume
    if "volume" in result.columns:
        result["volume_ratio_20d"] = volume_ratio(result["volume"], 20)
        result["volume_ratio_50d"] = volume_ratio(result["volume"], 50)

    # Gap (open vs prev close)
    result["gap_pct"] = (result["open"] / close.shift(1) - 1.0) * 100.0

    # Consecutive down days
    down = (close.diff() < 0).astype(int)
    result["consecutive_down"] = down * (down.groupby((down != down.shift()).cumsum()).cumcount() + 1)

    # Distance from SMAs (in hard currency)
    result["dist_sma_20"] = distance_from_sma(close, 20)
    result["dist_sma_200"] = distance_from_sma(close, 200)

    # Distance from 60d high (in hard currency)
    result["distance_to_high_60d"] = (
        close - result["_high"].rolling(window=60).max()
    ) / result["_high"].rolling(window=60).max().replace(0, np.nan)

    # Z-score of 3d returns
    result["return_3d_zscore"] = zscore(result["return_3d"], 60)

    # Bollinger %b
    result["bb_pct_b"] = bollinger_b(close, 20)

    # Close above SMA200 (boolean)
    result["close_above_sma_200"] = (close > result["sma_200"]).astype(float)

    # Close breaks 20d high (in hard currency)
    result["close_breaks_high_20d"] = (
        close > result["_high"].rolling(window=20).max().shift(1)
    ).astype(float)

    # SMA200 slope
    result["sma_200_slope"] = sma_slope(close, 200, 20)

    # Clean up temporary columns
    result = result.drop(columns=["_high", "_low"], errors="ignore")

    return result
