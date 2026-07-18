"""
futures_execution.py — Statistical Edge Lab
Fill model for ROFEX futures using real bid/ask data.

Key decisions (Tom, Q5):
  - Entry for long: best ask at or after signal time
  - Exit for long: best bid at exit time
  - Costs: ROFEX 0.46% RT (commission 0.15%/side + fees 0.03% + slippage 0.05%)
  - Contract multiplier: GGAL = 100 shares
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def fill_at_best_ask(
    bid_ask_series: pd.DataFrame,
    timestamp: pd.Timestamp,
    lookahead_tolerance: str = "1h",
) -> Optional[float]:
    """
    Get fill price at best ask for a long entry.
    Searches forward from timestamp within tolerance window.

    Args:
        bid_ask_series: DataFrame with columns [timestamp, bid, ask, last], index=timestamp
        timestamp: Desired fill time
        lookahead_tolerance: Max time to search forward

    Returns:
        Fill price (best ask) or None if no data in window.
    """
    window_end = timestamp + pd.Timedelta(lookahead_tolerance)
    window = bid_ask_series.loc[timestamp:window_end]

    # Filter to rows with ask
    valid = window[window["ask"].notna() & (window["ask"] > 0)]
    if valid.empty:
        return None

    return float(valid["ask"].iloc[0])


def fill_at_best_bid(
    bid_ask_series: pd.DataFrame,
    timestamp: pd.Timestamp,
    lookahead_tolerance: str = "1h",
) -> Optional[float]:
    """
    Get fill price at best bid for a long exit.
    Searches forward from timestamp within tolerance window.

    Args:
        bid_ask_series: DataFrame with columns [timestamp, bid, ask, last], index=timestamp
        timestamp: Desired fill time
        lookahead_tolerance: Max time to search forward

    Returns:
        Fill price (best bid) or None if no data in window.
    """
    window_end = timestamp + pd.Timedelta(lookahead_tolerance)
    window = bid_ask_series.loc[timestamp:window_end]

    valid = window[window["bid"].notna() & (window["bid"] > 0)]
    if valid.empty:
        return None

    return float(valid["bid"].iloc[0])


def execute_long_trade(
    bid_ask_df: pd.DataFrame,
    signal_timestamp: pd.Timestamp,
    holding_sessions: int,
    lookahead_tolerance: str = "1h",
) -> Optional[dict]:
    """
    Simulate a long futures trade using real bid/ask.

    Entry: best ask after signal_time
    Exit: best bid after entry_time + holding_sessions business days

    Returns:
        dict with {
            signal_ts, entry_ts, entry_price, exit_ts, exit_price,
            gross_return_pct, spread_cost_pct, status
        }
    """
    if bid_ask_df.empty:
        return None

    # Entry
    entry_price = fill_at_best_ask(bid_ask_df, signal_timestamp, lookahead_tolerance)
    if entry_price is None or entry_price <= 0:
        return None

    # Find the row index for entry
    window_end = signal_timestamp + pd.Timedelta(lookahead_tolerance)
    window = bid_ask_df[signal_timestamp:window_end]
    valid = window[window["ask"].notna() & (window["ask"] > 0)]
    if valid.empty:
        return None
    entry_ts = valid.index[0]

    # Exit (holding_sessions trading days after entry)
    exit_target = entry_ts + pd.Timedelta(days=holding_sessions)
    exit_price = fill_at_best_bid(bid_ask_df, exit_target, lookahead_tolerance)

    if exit_price is None or exit_price <= 0:
        return None

    # Find exit timestamp
    exit_window = bid_ask_df[exit_target:exit_target + pd.Timedelta(lookahead_tolerance)]
    valid_exit = exit_window[exit_window["bid"].notna() & (exit_window["bid"] > 0)]
    if valid_exit.empty:
        return None
    exit_ts = valid_exit.index[0]

    gross_return = (exit_price / entry_price - 1) * 100
    spread_cost = abs(entry_price - exit_price) / entry_price * 100  # bid-ask spread impact

    return {
        "signal_ts": signal_timestamp,
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "exit_ts": exit_ts,
        "exit_price": exit_price,
        "gross_return_pct": gross_return,
        "spread_cost_pct": spread_cost,
        "holding_sessions": holding_sessions,
        "status": "filled",
    }


class FuturesCostModel:
    """ROFEX futures cost model."""

    def __init__(self, costs_path: Optional[str] = None):
        if costs_path:
            import yaml
            with open(costs_path) as f:
                costs = yaml.safe_load(f)
            self.total_rt_pct = costs.get("futures_rofex", {}).get("minimum_total_roundtrip", 0.0046) * 100
        else:
            # Default ROFEX costs
            self.total_rt_pct = 0.46  # 0.46% round trip

    def net_return(self, gross_return_pct: float) -> float:
        """Apply futures transaction costs."""
        return gross_return_pct - self.total_rt_pct


def build_daily_ohlcv_from_stream(
    stream_df: pd.DataFrame,
    symbol: str,
) -> pd.DataFrame:
    """
    Convert tick-level stream data to daily OHLCV.

    Uses 'last' price for OHLC, aggregates bid/ask for daily VWAP.

    Args:
        stream_df: Stream data filtered to one symbol
        symbol: Symbol name (for logging)

    Returns:
        DataFrame with columns [date, open, high, low, close, vwap_bid, vwap_ask, volume]
    """
    if stream_df.empty:
        return pd.DataFrame()

    # Ensure timestamp is datetime
    df = stream_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date
    df = df.dropna(subset=["last"])

    if df.empty:
        logger.warning(f"No 'last' prices in stream for {symbol}")
        return pd.DataFrame()

    # Daily OHLC from last price
    daily = df.groupby("date").agg(
        open=("last", "first"),
        high=("last", "max"),
        low=("last", "min"),
        close=("last", "last"),
        vwap_bid=("bid", "mean"),
        vwap_ask=("ask", "mean"),
        n_ticks=("last", "count"),
    ).reset_index()

    daily["symbol"] = symbol
    daily["date"] = pd.to_datetime(daily["date"])

    logger.info(f"Built daily OHLCV for {symbol}: {len(daily)} days, "
                f"avg {daily['n_ticks'].mean():.0f} ticks/day")
    return daily
