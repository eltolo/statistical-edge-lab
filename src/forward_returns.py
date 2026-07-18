"""
forward_returns.py — Statistical Edge Lab
Phase 1: Calculate forward returns, MFE, and MAE for event occurrences.

Spec §10: Required metrics per forward horizon:
  Number of events, mean return, median return, std dev, percentiles,
  win rate, avg gain, avg loss, profit factor, expected value,
  MFE, MAE, worst result, best result.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def calculate_forward_returns(
    df: pd.DataFrame,
    event_dates: list[pd.Timestamp],
    horizons: list[int],
    price_col: str = "close_usd",
) -> dict[int, pd.DataFrame]:
    """
    Calculate forward returns for each event date and horizon.

    Args:
        df: Price DataFrame indexed by date
        event_dates: List of dates when the event occurred
        horizons: List of forward windows in trading days
        price_col: Column with prices to use

    Returns:
        dict[horizon -> DataFrame with columns:
            event_date, forward_return, mfe, mae
        ]
    """
    # Ensure index is sorted
    df = df.sort_index()
    prices = df[price_col]

    results = {}
    for h in horizons:
        rows = []
        for ed in event_dates:
            try:
                idx = df.index.get_loc(ed)
            except (KeyError, TypeError):
                # Date not in index, skip
                continue

            if idx + h >= len(df):
                # Not enough future data
                continue

            entry_price = float(prices.iloc[idx])
            if entry_price == 0:
                continue

            # Forward slice: ALL prices during the period INCLUDING exit
            forward_idx = slice(idx + 1, idx + h + 1)
            forward_prices = prices.iloc[forward_idx]

            if len(forward_prices) < h:
                continue

            exit_price = float(prices.iloc[idx + h])
            forward_return = (exit_price / entry_price - 1) * 100

            # MFE: Maximum Favorable Excursion (max price / entry - 1)
            # Includes exit price per standard definition
            max_price = float(forward_prices.max())
            mfe = (max_price / entry_price - 1) * 100

            # MAE: Maximum Adverse Excursion (min price / entry - 1)
            min_price = float(forward_prices.min())
            mae = (min_price / entry_price - 1) * 100

            rows.append({
                "event_date": ed,
                "forward_return": forward_return,
                "mfe": mfe,
                "mae": mae,
                "entry_price": entry_price,
                "exit_price": exit_price,
            })

        results[h] = pd.DataFrame(rows)

    return results


def summarize_forward_returns(
    fr_df: pd.DataFrame,
    horizon: int,
) -> dict:
    """
    Compute summary statistics for a set of forward returns.

    Spec §10: mandatory metrics.
    """
    if fr_df.empty:
        return {"horizon": horizon, "n_events": 0}

    returns = fr_df["forward_return"].values
    n = len(returns)

    summary = {
        "horizon": horizon,
        "n_events": n,
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "std_return": float(np.std(returns, ddof=1)),
        "p25": float(np.percentile(returns, 25)),
        "p75": float(np.percentile(returns, 75)),
        "win_rate": float(np.mean(returns > 0)),
        "avg_gain": float(np.mean(returns[returns > 0])) if np.any(returns > 0) else 0.0,
        "avg_loss": float(np.mean(returns[returns <= 0])) if np.any(returns <= 0) else 0.0,
        "worst": float(np.min(returns)),
        "best": float(np.max(returns)),
        "total_return": float(np.sum(returns)),
    }

    # Profit factor
    total_gain = np.sum(returns[returns > 0]) if np.any(returns > 0) else 0
    total_loss = abs(np.sum(returns[returns < 0])) if np.any(returns < 0) else 1e-10
    summary["profit_factor"] = float(total_gain / total_loss)

    # Expected value = mean return per event
    summary["expected_value"] = summary["mean_return"]

    # MFE/MAE averages
    if "mfe" in fr_df.columns:
        summary["avg_mfe"] = float(np.mean(fr_df["mfe"].values))
    if "mae" in fr_df.columns:
        summary["avg_mae"] = float(np.mean(fr_df["mae"].values))

    return summary


def compute_overall_metrics(
    event_returns: dict[int, pd.DataFrame],
    control_returns: Optional[dict[int, pd.DataFrame]] = None,
) -> dict:
    """
    Compute complete metrics across all horizons.

    Returns dict with per-horizon summaries and aggregate metrics.
    """
    result = {}
    for h, fr_df in event_returns.items():
        summary = summarize_forward_returns(fr_df, h)
        result[f"horizon_{h}d"] = summary

        if control_returns and h in control_returns:
            ctrl = summarize_forward_returns(control_returns[h], h)
            result[f"horizon_{h}d"]["control"] = ctrl
            result[f"horizon_{h}d"]["incremental_edge"] = (
                summary["mean_return"] - ctrl["mean_return"]
            )

    return result
