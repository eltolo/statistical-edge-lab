"""
robustness.py — Statistical Edge Lab
Phase 4: Robustness tests for candidate events.

Spec §15:
  15.1 Parameter neighborhood
  15.2 Leave-one-asset-out
  15.3 Leave-one-year-out
  15.4 Profit concentration
  15.5 Bootstrap confidence intervals
"""

import logging
from typing import Optional, Callable
from itertools import combinations

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def bootstrap_ci(
    returns: np.ndarray,
    n_iterations: int = 10000,
    ci: float = 0.95,
    seed: int = 42,
) -> dict:
    """
    Bootstrap confidence interval for the mean return.

    Spec §15.5: Calculate confidence intervals by resampling independent events.

    Returns dict with:
      - mean: original mean
      - ci_lower, ci_upper: confidence interval bounds
      - std_error: bootstrap standard error
    """
    rng = np.random.default_rng(seed)
    n = len(returns)
    if n == 0:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "std_error": 0.0, "n_iterations": n_iterations}

    boot_means = np.zeros(n_iterations)
    for i in range(n_iterations):
        sample = rng.choice(returns, size=n, replace=True)
        boot_means[i] = np.mean(sample)

    alpha = (1 - ci) / 2
    ci_lower = float(np.percentile(boot_means, alpha * 100))
    ci_upper = float(np.percentile(boot_means, (1 - alpha) * 100))

    return {
        "mean": float(np.mean(returns)),
        "median": float(np.median(returns)),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "std_error": float(np.std(boot_means, ddof=1)),
        "ci": ci,
        "n_iterations": n_iterations,
    }


def parameter_neighborhood(
    base_conditions: dict,
    param_variations: dict[str, list],
    detect_fn: Callable,
    df: pd.DataFrame,
    metric_fn: Callable,
) -> list[dict]:
    """
    Spec §15.1: Test nearby parameter values.

    Args:
        base_conditions: Original event conditions dict
        param_variations: dict of {param_name: [list of values to test]}
        detect_fn: Function that takes (df, conditions) -> event_mask
        df: DataFrame with features
        metric_fn: Function that takes (event_returns) -> metric (e.g., mean return)

    Returns:
        list of dicts: {param: value, metric_result, n_events}
    """
    results = []
    for param_name, values in param_variations.items():
        for val in values:
            # Create modified conditions
            conditions = {}
            for k, v in base_conditions.items():
                if isinstance(v, dict):
                    conditions[k] = dict(v)
                else:
                    conditions[k] = v

            if param_name in conditions:
                conditions[param_name]["value"] = val

            # Detect events
            from event_detector import detect_events, apply_cooldown
            mask = detect_events(df, conditions)
            mask = apply_cooldown(mask, 10)

            event_returns = _get_forward_returns(df, mask, 5)
            metric = metric_fn(event_returns) if len(event_returns) > 0 else None

            results.append({
                "parameter": param_name,
                "value": val,
                "metric": metric,
                "n_events": int(mask.sum()),
            })

    return results


def _get_forward_returns(
    df: pd.DataFrame,
    event_mask: pd.Series,
    horizon: int,
    price_col: str = "close_usd",
) -> np.ndarray:
    """Extract forward returns for event dates using shared function."""
    from forward_returns import forward_return_series
    fr = forward_return_series(df[price_col], horizon)
    return fr[event_mask].dropna().values


def leave_one_asset_out(
    data: dict[str, pd.DataFrame],
    conditions: dict,
    cooldown_sessions: int,
    horizons: list[int],
    price_col: str = "close_usd",
) -> list[dict]:
    """
    Spec §15.2: Recalculate results excluding one ticker at a time.
    Per-horizon metrics. Does not mix horizons.

    Returns list of {excluded_ticker, horizon, n_events, mean_return}
    """
    from event_detector import detect_events_all_assets
    from forward_returns import calculate_forward_returns

    tickers = list(data.keys())
    results = []

    for excluded in tickers:
        subset = {t: d for t, d in data.items() if t != excluded}
        events = detect_events_all_assets(subset, conditions, cooldown_sessions)

        for h in horizons:
            all_rets = []
            for ticker, dates in events.items():
                fr = calculate_forward_returns(subset[ticker], dates, [h], price_col)
                if h in fr and not fr[h].empty:
                    all_rets.extend(fr[h]["forward_return"].values)

            results.append({
                "excluded_ticker": excluded,
                "horizon": h,
                "n_events": len(all_rets),
                "mean_return": float(np.mean(all_rets)) if all_rets else 0.0,
            })

    return results


def leave_one_year_out(
    data: dict[str, pd.DataFrame],
    conditions: dict,
    cooldown_sessions: int,
    horizons: list[int],
    years: Optional[list[int]] = None,
    price_col: str = "close_usd",
) -> list[dict]:
    """
    Spec §15.3: Recalculate results excluding one calendar year at a time.
    Per-horizon metrics. Does not mix horizons.

    Does NOT remove data from DataFrame (avoids creating artificial
    adjacency across the gap). Instead filters events by signal_date.
    """
    from event_detector import detect_events_all_assets
    from forward_returns import calculate_forward_returns

    if years is None:
        all_years = set()
        for df in data.values():
            all_years.update(df.index.year.unique())
        years = sorted(all_years)

    # Detect events on full data
    events = detect_events_all_assets(data, conditions, cooldown_sessions)

    results = []
    for year in years:
        for h in horizons:
            all_rets = []
            for ticker, dates in events.items():
                # Filter events whose signal_date is NOT in the excluded year
                filtered_dates = [d for d in dates if d.year != year]
                if not filtered_dates:
                    continue
                fr = calculate_forward_returns(data[ticker], filtered_dates, [h], price_col)
                if h in fr and not fr[h].empty:
                    all_rets.extend(fr[h]["forward_return"].values)

            results.append({
                "excluded_year": year,
                "horizon": h,
                "n_events": len(all_rets),
                "mean_return": float(np.mean(all_rets)) if all_rets else 0.0,
            })

    return results


def profit_concentration_per_horizon(
    returns_by_asset_horizon: dict[str, dict[int, np.ndarray]],
) -> dict[int, dict]:
    """
    Spec §15.4: Measure profit concentration PER HORIZON.

    Args:
        returns_by_asset_horizon: {ticker: {horizon: np.ndarray}}

    Returns:
        dict[horizon -> {
            best_trade_pct, best_3_pct, best_asset, best_asset_pct
        }]
    """
    # Collect all horizons
    all_horizons = set()
    for asset_rets in returns_by_asset_horizon.values():
        all_horizons.update(asset_rets.keys())

    results = {}
    for h in sorted(all_horizons):
        # Gather returns for this horizon
        asset_rets = {}
        for ticker, by_h in returns_by_asset_horizon.items():
            if h in by_h:
                asset_rets[ticker] = by_h[h]

        all_returns = np.concatenate(list(asset_rets.values())) if asset_rets else np.array([])
        total_profit = np.sum(all_returns)

        if total_profit == 0 or len(all_returns) == 0:
            results[h] = {
                "best_trade_pct": 0,
                "best_3_pct": 0,
                "best_asset": "—",
                "best_asset_pct": 0,
                "n_trades": 0,
                "n_assets": len(asset_rets),
            }
            continue

        # Best trade
        best_trade_pct = float(np.max(all_returns) / total_profit * 100)

        # Best 3 trades
        sorted_rets = np.sort(all_returns)[::-1]
        best_3_pct = float(np.sum(sorted_rets[:3]) / total_profit * 100)

        # Best asset
        asset_profits = {t: float(np.sum(r)) for t, r in asset_rets.items()}
        best_asset = max(asset_profits, key=asset_profits.get)
        best_asset_pct = float(asset_profits[best_asset] / total_profit * 100)

        results[h] = {
            "horizon": h,
            "best_trade_pct": best_trade_pct,
            "best_3_pct": best_3_pct,
            "best_asset": best_asset,
            "best_asset_pct": best_asset_pct,
            "n_trades": len(all_returns),
            "n_assets": len(asset_rets),
        }

    return results


def run_all_robustness(
    data: dict[str, pd.DataFrame],
    conditions: dict,
    cooldown_sessions: int,
    horizons: list[int],
    price_col: str = "close_usd",
) -> dict:
    """Run all robustness tests (per-horizon) and return consolidated results."""
    results = {}

    from event_detector import detect_events_all_assets
    from forward_returns import calculate_forward_returns
    events = detect_events_all_assets(data, conditions, cooldown_sessions)

    # Per-horizon: bootstrap, collect returns for profit concentration
    returns_by_asset_horizon: dict[str, dict[int, np.ndarray]] = {}
    for h in horizons:
        all_returns = []
        for ticker, dates in events.items():
            fr = calculate_forward_returns(data[ticker], dates, [h], price_col)
            if h in fr and not fr[h].empty:
                rets = fr[h]["forward_return"].values
                if len(rets):
                    all_returns.extend(rets)
                    if ticker not in returns_by_asset_horizon:
                        returns_by_asset_horizon[ticker] = {}
                    returns_by_asset_horizon[ticker][h] = rets

        if all_returns:
            results[f"bootstrap_h{h}d"] = bootstrap_ci(np.array(all_returns))
        else:
            results[f"bootstrap_h{h}d"] = {"mean": 0, "ci_lower": 0, "ci_upper": 0, "std_error": 0}

    # Leave-one-asset-out (per-horizon inside)
    results["leave_one_asset_out"] = leave_one_asset_out(
        data, conditions, cooldown_sessions, horizons, price_col
    )

    # Leave-one-year-out (per-horizon inside)
    results["leave_one_year_out"] = leave_one_year_out(
        data, conditions, cooldown_sessions, horizons, price_col
    )

    # Profit concentration (per-horizon)
    results["profit_concentration"] = profit_concentration_per_horizon(returns_by_asset_horizon)

    return results
