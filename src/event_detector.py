"""
event_detector.py — Statistical Edge Lab
Phase 2: Detect event occurrences based on configurable conditions.

Spec §8: Event definition via YAML (conditions with operator/value).
Spec §9: Cooldown period to remove overlapping events.
"""

import logging
from typing import Optional
from pathlib import Path

import pandas as pd
import numpy as np
import yaml

logger = logging.getLogger(__name__)


# Operator mapping: maps string operators to comparison functions
OPERATORS = {
    ">": np.greater,
    "<": np.less,
    ">=": np.greater_equal,
    "<=": np.less_equal,
    "==": np.equal,
    "!=": np.not_equal,
}


def load_event_config(path: str) -> dict:
    """Load event configuration from YAML file."""
    with open(path) as f:
        config = yaml.safe_load(f)
    return config


def evaluate_condition(
    series: pd.Series,
    operator: str,
    value: float,
) -> pd.Series:
    """
    Evaluate a single condition against a data series.

    Example:
        evaluate_condition(df['return_3d'], '<', -0.03)
    """
    op_func = OPERATORS.get(operator)
    if op_func is None:
        raise ValueError(f"Unknown operator: {operator}")
    return op_func(series, value)


def detect_events(
    df: pd.DataFrame,
    conditions: dict,
    feature_prefix: str = "",
) -> pd.Series:
    """
    Detect dates where ALL conditions are true.

    Args:
        df: DataFrame with computed features
        conditions: dict of {feature_name: {operator: ..., value: ...}}
        feature_prefix: optional prefix for condition keys (e.g., 'close_')

    Returns:
        Boolean Series (indexed by date) where True = event occurred.
    """
    if df.empty:
        return pd.Series(dtype=bool)

    mask = pd.Series(True, index=df.index)

    for feature, rule in conditions.items():
        if not isinstance(rule, dict) or "operator" not in rule:
            logger.warning(f"Invalid rule for {feature}: {rule}")
            continue

        # Build column name
        col = feature_prefix + feature

        if col not in df.columns:
            logger.warning(f"Feature column '{col}' not found in DataFrame")
            mask = pd.Series(False, index=df.index)
            break

        operator = rule["operator"]
        value = rule["value"]
        condition_mask = evaluate_condition(df[col], operator, value)
        mask = mask & condition_mask

    return mask


def apply_cooldown(
    event_mask: pd.Series,
    cooldown_days: int,
) -> pd.Series:
    """
    Remove overlapping events within cooldown_days.
    Keeps the FIRST event in each cluster.

    Spec §9: Events that occur close together must not be treated
    as independent observations.
    """
    if not event_mask.any():
        return event_mask

    result = pd.Series(False, index=event_mask.index)
    event_dates = pd.DatetimeIndex(event_mask[event_mask].index).sort_values()

    last_kept = None
    for d in event_dates:
        if last_kept is None or (pd.Timestamp(d) - pd.Timestamp(last_kept)).days >= cooldown_days:
            result[d] = True
            last_kept = d

    n_raw = event_mask.sum()
    n_kept = result.sum()
    if n_kept < n_raw:
        logger.info(
            f"Cooldown: {n_raw} raw signals → {n_kept} independent events "
            f"({(1 - n_kept/n_raw)*100:.1f}% removed)"
        )

    return result


def get_event_dates(
    df: pd.DataFrame,
    conditions: dict,
    cooldown_days: int = 10,
    min_events: int = 1,
) -> list[pd.Timestamp]:
    """
    Detect events, apply cooldown, and return sorted list of event dates.

    Returns empty list if fewer than min_events found.
    """
    event_mask = detect_events(df, conditions)
    event_mask = apply_cooldown(event_mask, cooldown_days)
    event_dates = event_mask[event_mask].index.sort_values().tolist()

    if len(event_dates) < min_events:
        logger.warning(f"Only {len(event_dates)} events found (minimum: {min_events})")
        return []

    return event_dates


def detect_events_all_assets(
    data: dict[str, pd.DataFrame],
    conditions: dict,
    cooldown_days: int = 10,
) -> dict[str, list[pd.Timestamp]]:
    """
    Detect events across all assets in the universe.

    Returns dict[ticker -> list of event dates].
    """
    result = {}
    for ticker, df in data.items():
        dates = get_event_dates(df, conditions, cooldown_days)
        if dates:
            result[ticker] = dates
            logger.info(f"{ticker}: {len(dates)} independent events")
    return result
