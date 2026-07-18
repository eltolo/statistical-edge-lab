"""
forward_returns.py — Statistical Edge Lab
Phase 1: Shared forward-return calculation, MFE, MAE.

Audit P0 #1: Shared function for ALL forward-return calculations.
Audit P0 #3: MFE/MAE uses adjusted high/low, not close.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ── Canonical trade table columns (Audit 4) ──
CANONICAL_COLUMNS = [
    "ticker", "market",
    "signal_date", "entry_date", "exit_date",
    "horizon",
    "signal_price", "entry_price", "exit_price",
    "forward_return", "transaction_cost_pct", "net_return_pct",
    "mfe", "mae",
    "trend_regime", "vol_regime",
    "temporal_split",
    "matched_baseline_return", "matched_baseline_n", "matched_baseline_status",
    "incremental_edge_net",
]


# ──────────────────────────────────────────────
# Shared forward-return function (Audit P0 #1)
# ──────────────────────────────────────────────

def forward_return_series(
    prices: pd.Series,
    horizon: int,
) -> pd.Series:
    """
    Calculate forward returns over N periods.

    Formula: price[t + horizon] / price[t] - 1
    Returns percentages (e.g., 5.0 = 5%).

    >>> prices = pd.Series([100.0, 110.0, 121.0, 133.1])
    >>> forward_return_series(prices, 1)
    0    10.0
    1    10.0
    2    10.0
    3     NaN
    dtype: float64
    >>> forward_return_series(prices, 2)
    0    21.0
    1    21.0
    2     NaN
    3     NaN
    dtype: float64
    """
    return (
        prices.shift(-horizon)
        .div(prices)
        .sub(1.0)
        .mul(100.0)
    )


def event_forward_return(
    entry_price: float,
    exit_price: float,
) -> float:
    """Return for a single event: (exit/entry - 1) * 100."""
    if entry_price == 0:
        return 0.0
    return (exit_price / entry_price - 1.0) * 100.0


# ──────────────────────────────────────────────
# MFE and MAE (Audit P0 #3)
# ──────────────────────────────────────────────

def mfe_from_high(
    entry_price: float,
    high_prices: pd.Series,
) -> float:
    """
    Maximum Favorable Excursion for a long trade.
    Uses adjusted high prices during the holding period.

    MFE = (max_high / entry - 1) * 100
    """
    if entry_price == 0 or high_prices.empty:
        return 0.0
    return (float(high_prices.max()) / entry_price - 1.0) * 100.0


def mae_from_low(
    entry_price: float,
    low_prices: pd.Series,
) -> float:
    """
    Maximum Adverse Excursion for a long trade.
    Uses adjusted low prices during the holding period.

    MAE = (min_low / entry - 1) * 100
    """
    if entry_price == 0 or low_prices.empty:
        return 0.0
    return (float(low_prices.min()) / entry_price - 1.0) * 100.0


# ──────────────────────────────────────────────
# Event-aware forward returns (Audit P0 #2, #3)
# ──────────────────────────────────────────────

def calculate_forward_returns(
    df: pd.DataFrame,
    event_dates: list[pd.Timestamp],
    horizons: list[int],
    price_col: str = "close_usd",
    high_col: str = "high_usd",
    low_col: str = "low_usd",
    entry_mode: str = "next_open",
) -> dict[int, pd.DataFrame]:
    """
    Calculate forward returns, MFE, and MAE for each event.

    Audit P0 #2: Default entry_mode='next_open'.
    Audit P0 #3: MFE/MAE from high/low, not close.

    Args:
        df: DataFrame indexed by date with OHLCUSD columns
        event_dates: Signal dates (event confirmed at close of this day)
        horizons: Forward windows in trading sessions
        price_col: Column for exit price
        high_col: Column for MFE (adjusted high)
        low_col: Column for MAE (adjusted low)
        entry_mode: 'next_open' (default) or 'signal_close'

    Returns:
        dict[horizon -> DataFrame with columns:
            ticker, signal_date, entry_date, exit_date,
            signal_price, entry_price, exit_price,
            forward_return, mfe, mae, horizon
        ]
    """
    df = df.sort_index()

    results = {}
    for h in horizons:
        rows = []
        for signal_date in event_dates:
            try:
                signal_idx = df.index.get_loc(signal_date)
            except (KeyError, TypeError):
                continue

            # Signal price = close of signal day
            signal_price = float(df[price_col].iloc[signal_idx])

            # Entry: next open (default) or signal close
            if entry_mode == "next_open":
                entry_idx = signal_idx + 1
                if entry_idx >= len(df):
                    continue
                entry_date = df.index[entry_idx]
                entry_price = float(df["open_usd"].iloc[entry_idx]
                                    if "open_usd" in df.columns
                                    else df[price_col].iloc[entry_idx])
            else:  # signal_close
                entry_idx = signal_idx
                entry_date = signal_date
                entry_price = signal_price

            if entry_price == 0:
                continue

            # Check enough future data
            if entry_mode == "next_open":
                # h=1: exit at close of same session as entry (open→close of T+1)
                if signal_idx + h + 1 > len(df):
                    continue
            else:
                if signal_idx + h + 1 > len(df):
                    continue

            # Exit at horizon
            if entry_mode == "next_open":
                # h=1 → close of entry session (same index, close price)
                exit_idx = entry_idx + h - 1
            else:  # signal_close
                # h=1 → close of next session
                exit_idx = entry_idx + h
            if exit_idx >= len(df):
                continue
            exit_date = df.index[exit_idx]
            exit_price = float(df[price_col].iloc[exit_idx])

            forward_ret = event_forward_return(entry_price, exit_price)

            # MFE/MAE from adjusted high/low during holding period
            if entry_mode == "next_open":
                # Entered at open: this session's high/low count
                hold_start = entry_idx
            else:
                # Entered at close: next session's high/low count
                hold_start = entry_idx + 1
            hold_end = exit_idx
            if hold_start <= hold_end:
                high_slice = df[high_col].iloc[hold_start:hold_end + 1]
                low_slice = df[low_col].iloc[hold_start:hold_end + 1]
                mfe_val = mfe_from_high(entry_price, high_slice)
                mae_val = mae_from_low(entry_price, low_slice)
                mfe_date = high_slice.idxmax() if not high_slice.empty else exit_date
                mae_date = low_slice.idxmin() if not low_slice.empty else exit_date
            else:
                mfe_val = 0.0
                mae_val = 0.0
                mfe_date = exit_date
                mae_date = exit_date

            rows.append({
                "signal_date": signal_date,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "horizon": h,
                "signal_price": signal_price,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "forward_return": forward_ret,
                "mfe": mfe_val,
                "mae": mae_val,
                "mfe_date": mfe_date,
                "mae_date": mae_date,
            })

        results[h] = pd.DataFrame(rows)
        if not results[h].empty:
            results[h] = results[h].reset_index(drop=True)

    return results


# ──────────────────────────────────────────────
# Summary statistics (per Spec §10)
# ──────────────────────────────────────────────

def summarize_forward_returns(
    fr_df: pd.DataFrame,
    horizon: int,
    return_col: str = "forward_return",
) -> dict:
    """
    Compute summary statistics for a set of forward returns.

    Audit 4: Uses configurable return_col (forward_return or net_return_pct).
    """
    if fr_df.empty or return_col not in fr_df.columns:
        return {"horizon": horizon, "n_events": 0}

    returns = fr_df[return_col].dropna().values
    n = len(returns)
    if n == 0:
        return {"horizon": horizon, "n_events": 0}

    summary = {
        "horizon": horizon,
        "n_events": n,
        "return_col": return_col,
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

    total_gain = np.sum(returns[returns > 0]) if np.any(returns > 0) else 0
    total_loss = abs(np.sum(returns[returns < 0])) if np.any(returns < 0) else 1e-10
    summary["profit_factor"] = float(total_gain / total_loss) if total_loss > 0 else float("inf")
    summary["expected_value"] = summary["mean_return"]

    if "mfe" in fr_df.columns:
        summary["avg_mfe"] = float(np.mean(fr_df["mfe"].values))
    if "mae" in fr_df.columns:
        summary["avg_mae"] = float(np.mean(fr_df["mae"].values))

    return summary


def build_canonical_table(
    raw_returns: dict[str, dict[int, pd.DataFrame]],
    data_usd: dict[str, pd.DataFrame],
    splitter: Optional["TemporalSplit"] = None,
    horizons: Optional[list[int]] = None,
) -> pd.DataFrame:
    """
    Build a single canonical trade table enriched with regime and split info.

    Audit 4: Central table from which all metrics, baselines, and decisions derive.

    Args:
        raw_returns: {ticker: {horizon: DataFrame}} from calculate_forward_returns
        data_usd: USD-priced data with regime columns
        splitter: TemporalSplit instance for boundary classification
        horizons: list of horizons to include (None = all)

    Returns:
        DataFrame CANONICAL_COLUMNS, one row per (ticker, horizon, event)
    """
    rows = []
    for ticker, fr_by_h in raw_returns.items():
        for h, fr_df in fr_by_h.items():
            if horizons is not None and h not in horizons:
                continue
            if fr_df.empty:
                continue
            for _, trade in fr_df.iterrows():
                r = {
                    "ticker": ticker,
                    "horizon": h,
                    "signal_date": trade.get("signal_date"),
                    "entry_date": trade.get("entry_date"),
                    "exit_date": trade.get("exit_date"),
                    "signal_price": trade.get("signal_price"),
                    "entry_price": trade.get("entry_price"),
                    "exit_price": trade.get("exit_price"),
                    "forward_return": trade.get("forward_return"),
                    "transaction_cost_pct": trade.get("transaction_cost_pct", 0.0),
                    "net_return_pct": trade.get("net_return_pct"),
                    "mfe": trade.get("mfe"),
                    "mae": trade.get("mae"),
                }

                # Regime from data_usd at signal_date
                sd = r["signal_date"]
                if ticker in data_usd and sd in data_usd[ticker].index:
                    asset_row = data_usd[ticker].loc[sd]
                    r["trend_regime"] = asset_row.get("trend_regime", "NEUTRAL")
                    r["vol_regime"] = asset_row.get("vol_regime", "NORMAL_VOL")
                else:
                    r["trend_regime"] = "NEUTRAL"
                    r["vol_regime"] = "NORMAL_VOL"

                # Temporal split (needs all 3 dates)
                if splitter is not None:
                    r["temporal_split"] = splitter.assign_trade_split(
                        {k: r[k] for k in ("signal_date", "entry_date", "exit_date")}
                    )
                else:
                    r["temporal_split"] = "full_sample"

                # Baseline fields (filled later by enrich_canonical_with_baselines)
                r["matched_baseline_return"] = None
                r["matched_baseline_n"] = 0
                r["matched_baseline_status"] = "PENDING"
                r["incremental_edge_net"] = None

                rows.append(r)

    if not rows:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    result = pd.DataFrame(rows)
    # Ensure all canonical columns exist
    for col in CANONICAL_COLUMNS:
        if col not in result.columns:
            result[col] = None
    return result[CANONICAL_COLUMNS]


def enrich_canonical_with_baselines(
    canonical: pd.DataFrame,
    all_baselines: dict[str, dict[int, dict]],
) -> pd.DataFrame:
    """
    Add matched baseline info to canonical table from per-ticker baseline results.

    Matches each event to its per-event baseline details.
    Computes incremental_edge_net = net_return_pct - matched_baseline_return.
    """
    result = canonical.copy()

    for idx, row in result.iterrows():
        ticker = row["ticker"]
        h = row["horizon"]
        sd = row["signal_date"]

        if ticker not in all_baselines or h not in all_baselines[ticker]:
            continue

        per_event = all_baselines[ticker][h].get("per_event_details", [])
        for ed in per_event:
            if ed.get("event_date") == sd:
                result.at[idx, "matched_baseline_return"] = ed.get("matched_return")
                result.at[idx, "matched_baseline_n"] = ed.get("n_controls", 0)
                result.at[idx, "matched_baseline_status"] = ed.get("status", "INSUFFICIENT")

                net = row.get("net_return_pct")
                if net is not None and ed.get("matched_return") is not None:
                    result.at[idx, "incremental_edge_net"] = net - ed["matched_return"]
                break

    return result


def compute_overall_metrics(
    event_returns: dict[int, pd.DataFrame],
    return_col: str = "forward_return",
) -> dict:
    """Compute complete metrics across all horizons using specified return column."""
    result = {}
    for h, fr_df in event_returns.items():
        summary = summarize_forward_returns(fr_df, h, return_col)
        result[f"horizon_{h}d"] = summary
    return result
