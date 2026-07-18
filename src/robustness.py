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
    cooldown_days: int,
    horizons: list[int],
    price_col: str = "close_usd",
) -> list[dict]:
    """
    Spec §15.2: Recalculate results excluding one ticker at a time.

    Returns list of {excluded_ticker, n_events, metrics_by_horizon}
    """
    from event_detector import detect_events_all_assets
    from forward_returns import calculate_forward_returns, summarize_forward_returns

    tickers = list(data.keys())
    results = []

    for excluded in tickers:
        subset = {t: d for t, d in data.items() if t != excluded}
        events = detect_events_all_assets(subset, conditions, cooldown_days)

        all_events = []
        for ticker, dates in events.items():
            fr = calculate_forward_returns(subset[ticker], dates, horizons, price_col)
            for h in horizons:
                if h in fr and not fr[h].empty:
                    all_events.append(fr[h]["forward_return"])

        if all_events:
            combined = pd.concat(all_events).values
            metrics = {h: {"n_events": len(combined), "mean_return": float(np.mean(combined))}
                       for h in horizons}
        else:
            metrics = {h: {"n_events": 0, "mean_return": 0.0} for h in horizons}

        results.append({
            "excluded_ticker": excluded,
            "metrics": metrics,
        })

    return results


def leave_one_year_out(
    data: dict[str, pd.DataFrame],
    conditions: dict,
    cooldown_days: int,
    horizons: list[int],
    years: Optional[list[int]] = None,
    price_col: str = "close_usd",
) -> list[dict]:
    """
    Spec §15.3: Recalculate results excluding one calendar year at a time.
    """
    from event_detector import detect_events_all_assets
    from forward_returns import calculate_forward_returns

    if years is None:
        all_years = set()
        for df in data.values():
            all_years.update(df.index.year.unique())
        years = sorted(all_years)

    results = []
    for year in years:
        # Remove data for that year
        subset = {}
        for ticker, df in data.items():
            subset[ticker] = df[df.index.year != year]

        events = detect_events_all_assets(subset, conditions, cooldown_days)

        all_returns = []
        for ticker, dates in events.items():
            fr = calculate_forward_returns(subset[ticker], dates, horizons, price_col)
            for h in horizons:
                if h in fr and not fr[h].empty:
                    all_returns.extend(fr[h]["forward_return"].values)

        result = {
            "excluded_year": year,
            "n_events": len(all_returns),
            "mean_return": float(np.mean(all_returns)) if all_returns else 0.0,
        }
        results.append(result)

    return results


def profit_concentration(
    returns_per_asset: dict[str, np.ndarray],
) -> dict:
    """
    Spec §15.4: Measure profit concentration.

    Returns:
        - best_trade_pct: % of total profit from best trade
        - best_3_pct: % from best 3 trades
        - best_asset_pct: % from best-performing asset
        - best_year_pct: % from best-performing year
    """
    all_returns = np.concatenate(list(returns_per_asset.values()))
    total_profit = np.sum(all_returns)

    if total_profit == 0:
        return {
            "best_trade_pct": 0,
            "best_3_pct": 0,
            "best_asset_pct": 0,
        }

    # Best trade
    best_trade_pct = float(np.max(all_returns) / total_profit * 100)

    # Best 3 trades
    sorted_returns = np.sort(all_returns)[::-1]
    best_3_pct = float(np.sum(sorted_returns[:3]) / total_profit * 100)

    # Best asset
    asset_profits = {t: float(np.sum(r)) for t, r in returns_per_asset.items()}
    best_asset = max(asset_profits, key=asset_profits.get)
    best_asset_pct = float(asset_profits[best_asset] / total_profit * 100)

    return {
        "best_trade_pct": best_trade_pct,
        "best_3_pct": best_3_pct,
        "best_asset": best_asset,
        "best_asset_pct": best_asset_pct,
    }


def run_all_robustness(
    data: dict[str, pd.DataFrame],
    conditions: dict,
    cooldown_days: int,
    horizons: list[int],
    price_col: str = "close_usd",
) -> dict:
    """Run all robustness tests and return consolidated results."""
    results = {}

    # Bootstrap (on combined returns)
    from event_detector import detect_events_all_assets
    from forward_returns import calculate_forward_returns
    events = detect_events_all_assets(data, conditions, cooldown_days)

    all_returns_by_asset = {}
    for h in horizons:
        all_returns = []
        for ticker, dates in events.items():
            fr = calculate_forward_returns(data[ticker], dates, [h], price_col)
            if h in fr and not fr[h].empty:
                rets = fr[h]["forward_return"].values
                all_returns.extend(rets)
                if ticker not in all_returns_by_asset:
                    all_returns_by_asset[ticker] = []
                all_returns_by_asset[ticker].append(rets)

        if all_returns:
            results[f"bootstrap_h{h}d"] = bootstrap_ci(np.array(all_returns))

    # Leave-one-asset-out
    results["leave_one_asset_out"] = leave_one_asset_out(
        data, conditions, cooldown_days, horizons, price_col
    )

    # Leave-one-year-out
    results["leave_one_year_out"] = leave_one_year_out(
        data, conditions, cooldown_days, horizons, price_col
    )

    # Profit concentration
    flat_by_asset = {}
    for ticker, ret_lists in all_returns_by_asset.items():
        flat_by_asset[ticker] = np.concatenate(ret_lists) if ret_lists else np.array([])
    results["profit_concentration"] = profit_concentration(flat_by_asset)

    return results
