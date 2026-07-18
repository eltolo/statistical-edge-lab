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

    Audit 4: Uses adjusted OHLC (open_adj, high_adj, low_adj, adj_close)
    for USD conversion, not raw OHLC.
    Audit 4: Uses LEFT JOIN so CCL can be forward-filled on missing dates.

    Produces: close_usd, open_usd, high_usd, low_usd, ccl
    """
    result = df.copy()

    # Determine which price columns to dollarize (prefer adjusted)
    price_cols = []
    for raw_col, adj_col in [
        ("close", "adj_close"),
        ("open", "open_adj"),
        ("high", "high_adj"),
        ("low", "low_adj"),
    ]:
        if adj_col in result.columns:
            price_cols.append((raw_col, adj_col))
        elif raw_col in result.columns:
            price_cols.append((raw_col, raw_col))

    # Audit 4: LEFT JOIN so CCL can be forward-filled
    merged = result.join(ccl_series[["ccl"]], how="left")

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

    # Convert prices (adjusted → USD)
    for raw_col, adj_col in price_cols:
        if adj_col in merged.columns:
            merged[f"{raw_col}_usd"] = merged[adj_col] / merged["ccl"]

    result = merged.copy()
    logger.info(f"Dollarized via CCL: {len(result)} rows, "
                f"using adjusted prices, "
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
    """Apply USD adjustment to Argentine tickers. Fail if CCL missing for AR assets.

    Audit 4: Also dollarizes benchmark ^MERV for regime computation in USD.
    """
    result = {}
    for ticker, df in data.items():
        # Check if argentine by suffix, market info, or benchmark
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


def dollarize_single_benchmark(
    bench_df: pd.DataFrame,
    ccl_series: pd.DataFrame,
) -> pd.DataFrame:
    """Dollarize a single benchmark DataFrame for regime computation in USD (Audit 4)."""
    return adjust_to_usd(bench_df, ccl_series)
