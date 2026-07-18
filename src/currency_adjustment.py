"""
currency_adjustment.py — Statistical Edge Lab
Phase 1: Convert ARS-denominated returns to hard currency (USD).

Spec §1: Main evaluation must be in hard currency.
Spec §7: Requires daily MEP or CCL exchange rate.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def adjust_to_usd(
    df: pd.DataFrame,
    ccl_series: pd.DataFrame,
    price_col: str = "close",
) -> pd.DataFrame:
    """
    Convert ARS prices to USD using CCL/MEP rate.

    Args:
        df: DataFrame with ARS prices, indexed by date
        ccl_series: DataFrame with 'ccl' column, indexed by date
        price_col: Column name to convert

    Returns:
        DataFrame with additional 'close_usd' column
    """
    result = df.copy()

    # Merge CCL rates
    merged = result.join(ccl_series[["ccl"]], how="left")

    # Forward-fill missing CCL rates (CCL may not update daily)
    merged["ccl"] = merged["ccl"].ffill()
    # If still missing at start, backfill
    merged["ccl"] = merged["ccl"].bfill()

    if merged["ccl"].isnull().any():
        n_missing = merged["ccl"].isnull().sum()
        logger.warning(f"{n_missing} rows without CCL rate, filling with 1.0")
        merged["ccl"] = merged["ccl"].fillna(1.0)

    result["close_usd"] = merged[price_col] / merged["ccl"]
    result["ccl"] = merged["ccl"]

    # Also convert OHLC if available
    for col in ["open", "high", "low"]:
        if col in result.columns:
            result[f"{col}_usd"] = result[col] / merged["ccl"]

    return result


def return_in_usd(
    df: pd.DataFrame,
    forward_window: int,
    ccl_series: Optional[pd.DataFrame] = None,
) -> pd.Series:
    """
    Calculate forward returns in USD.

    If ccl_series is provided, converts ARS->USD first.
    Otherwise assumes prices are already in USD.
    """
    if ccl_series is not None and "close_usd" not in df.columns:
        df = adjust_to_usd(df, ccl_series)

    price_col = "close_usd" if "close_usd" in df.columns else "close"
    forward_return = df[price_col].pct_change(periods=-forward_window).shift(-forward_window) * 100

    return forward_return


def dollarize_dataframe(
    data: dict[str, pd.DataFrame],
    ccl_series: Optional[pd.DataFrame] = None,
) -> dict[str, pd.DataFrame]:
    """Apply USD adjustment to all tickers that have CCL data."""
    result = {}
    for ticker, df in data.items():
        if ticker.endswith(".BA") and ccl_series is not None:
            result[ticker] = adjust_to_usd(df, ccl_series)
            logger.info(f"Dollarized {ticker} via CCL")
        else:
            # US tickers are already in USD
            df["close_usd"] = df["close"]
            logger.info(f"{ticker} already in USD")
            result[ticker] = df
    return result
