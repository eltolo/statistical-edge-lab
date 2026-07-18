"""
currency_adjustment.py — Statistical Edge Lab
Phase 1: Convert ARS-denominated prices to hard currency (USD).

Audit P0 #4: CCL must exist for AR assets; fail if missing.
Audit P0 #5: Produces close_usd, high_usd, low_usd, open_usd.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def adjust_to_usd(
    df: pd.DataFrame,
    ccl_series: pd.DataFrame,
) -> pd.DataFrame:
    """
    Convert ARS prices to USD using CCL rate.

    Produces: close_usd, open_usd, high_usd, low_usd, ccl

    Audit P0 #5: Converts OHLC for feature computation in hard currency.
    Audit P0 #4: Does not backfill beyond limit; no fillna(1.0).
    """
    result = df.copy()

    # Merge CCL rates
    merged = result.join(ccl_series[["ccl"]], how="inner")

    if merged.empty:
        raise ValueError("No overlapping dates between asset and CCL series. "
                         "Cannot dollarize Argentine asset.")

    # Forward-fill within limit
    merged["ccl"] = merged["ccl"].ffill(limit=5)

    # Drop rows before first valid CCL
    first_valid = merged["ccl"].first_valid_index()
    if first_valid is None:
        raise ValueError("No valid CCL observations after forward-fill. "
                         "Cannot dollarize Argentine asset.")

    merged = merged.loc[first_valid:]
    merged = merged.dropna(subset=["ccl"])

    if merged.empty:
        raise ValueError("All rows dropped after CCL validation.")

    # Convert prices
    for col in ["close", "open", "high", "low"]:
        if col in merged.columns:
            merged[f"{col}_usd"] = merged[col] / merged["ccl"]

    result = merged.copy()
    logger.info(f"Dollarized via CCL: {len(result)} rows, "
                f"CCL range [{result['ccl'].min():.1f} - {result['ccl'].max():.1f}]")
    return result


def return_in_usd(
    df: pd.DataFrame,
    forward_window: int,
    ccl_series: Optional[pd.DataFrame] = None,
) -> pd.Series:
    """
    Calculate forward returns in USD using shared function.

    Audit P0 #1: Uses forward_return_series().
    """
    from forward_returns import forward_return_series

    if ccl_series is not None and "close_usd" not in df.columns:
        df = adjust_to_usd(df, ccl_series)

    price_col = "close_usd" if "close_usd" in df.columns else "close"
    return forward_return_series(df[price_col], forward_window)


def dollarize_dataframe(
    data: dict[str, pd.DataFrame],
    ccl_series: Optional[pd.DataFrame] = None,
) -> dict[str, pd.DataFrame]:
    """Apply USD adjustment to Argentine tickers. Fail if CCL missing for AR assets."""
    result = {}
    for ticker, df in data.items():
        # Check if argentine by suffix or by market info
        is_ar = ticker.endswith(".BA") or ticker == "^MERV"

        if is_ar:
            if ccl_series is None:
                raise RuntimeError(
                    f"Cannot process {ticker}: CCL series required for Argentine assets "
                    f"but none provided. Add a CCL data source or exclude this ticker."
                )
            result[ticker] = adjust_to_usd(df, ccl_series)
        else:
            # US tickers: close_usd = close (already USD)
            df["close_usd"] = df["close"]
            if "open" in df.columns:
                df["open_usd"] = df["open"]
            if "high" in df.columns:
                df["high_usd"] = df["high"]
            if "low" in df.columns:
                df["low_usd"] = df["low"]
            result[ticker] = df

    return result
