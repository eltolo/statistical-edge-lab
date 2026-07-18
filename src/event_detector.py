"""
event_detector.py — Statistical Edge Lab
Phase 2: Detect event occurrences based on configurable conditions.

Audit P0 #6: Supports list-of-dicts conditions (multiple rules per feature).
Audit P0 #11: Session-based cooldown (trading days, not calendar days).
"""

import logging
from typing import Optional, Union
from pathlib import Path

import pandas as pd
import numpy as np
import yaml

logger = logging.getLogger(__name__)

OPERATORS = {
    ">": np.greater,
    "<": np.less,
    ">=": np.greater_equal,
    "<=": np.less_equal,
    "==": np.equal,
    "!=": np.not_equal,
}


def load_event_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def evaluate_condition(
    series: pd.Series,
    operator: str,
    value: Union[float, str],
) -> pd.Series:
    """Evaluate a single condition. Supports numeric and string values."""
    op_func = OPERATORS.get(operator)
    if op_func is None:
        raise ValueError(f"Unknown operator: {operator}")
    return op_func(series, value)


def detect_events(
    df: pd.DataFrame,
    conditions: Union[dict, list],
) -> pd.Series:
    """
    Detect dates where ALL conditions are true.

    Args:
        df: DataFrame with computed features
        conditions: Either:
            - list of dicts: [{"feature": "rsi_14", "operator": "<", "value": 30}, ...]
            - dict (legacy): {"rsi_14": {"operator": "<", "value": 30}, ...}

    Returns:
        Boolean Series (indexed by date) where True = event occurred.
    """
    if df.empty:
        return pd.Series(dtype=bool)

    mask = pd.Series(True, index=df.index)

    # Parse conditions into list of rules
    if isinstance(conditions, list):
        rules = conditions
    elif isinstance(conditions, dict):
        # Legacy format: convert
        rules = []
        for feature, rule in conditions.items():
            if isinstance(rule, dict) and "operator" in rule:
                rules.append({"feature": feature, **rule})
            else:
                logger.warning(f"Skipping invalid rule: {feature}={rule}")
    else:
        logger.error(f"Invalid conditions type: {type(conditions)}")
        return pd.Series(False, index=df.index)

    for rule in rules:
        feature = rule.get("feature")
        operator = rule.get("operator")
        value = rule.get("value")

        if feature is None or operator is None:
            logger.warning(f"Invalid rule (missing feature/operator): {rule}")
            mask = pd.Series(False, index=df.index)
            break

        if feature not in df.columns:
            logger.warning(f"Feature column '{feature}' not found in DataFrame")
            mask = pd.Series(False, index=df.index)
            break

        condition_mask = evaluate_condition(df[feature], operator, value)
        mask = mask & condition_mask

    return mask


def apply_cooldown_sessions(
    event_mask: pd.Series,
    df: pd.DataFrame,
    cooldown_sessions: int,
) -> pd.Series:
    """
    Audit P0 #11: Cooldown based on TRADING SESSIONS, not calendar days.

    Keeps the first event in each cluster, then skips cooldown_sessions
    trading days before considering the next event.
    """
    if not event_mask.any():
        return event_mask

    # Get positions of all true events in the DataFrame
    event_positions = np.where(event_mask.values)[0]
    if len(event_positions) == 0:
        return event_mask

    result = pd.Series(False, index=event_mask.index)
    last_kept_pos = -cooldown_sessions - 1

    for pos in event_positions:
        if pos - last_kept_pos > cooldown_sessions:
            result.iloc[pos] = True
            last_kept_pos = pos

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
    conditions: Union[dict, list],
    cooldown_sessions: int = 10,
    min_events: int = 1,
) -> list[pd.Timestamp]:
    """
    Detect events, apply session-based cooldown, return sorted event dates.

    Returns empty list if fewer than min_events found.
    """
    event_mask = detect_events(df, conditions)
    event_mask = apply_cooldown_sessions(event_mask, df, cooldown_sessions)
    event_dates = event_mask[event_mask].index.sort_values().tolist()

    if len(event_dates) < min_events:
        logger.warning(f"Only {len(event_dates)} events found (minimum: {min_events})")
        return []

    return event_dates


def detect_events_all_assets(
    data: dict[str, pd.DataFrame],
    conditions: Union[dict, list],
    cooldown_sessions: int = 10,
) -> dict[str, list[pd.Timestamp]]:
    """Detect events across all assets. Returns dict[ticker -> event dates]."""
    result = {}
    for ticker, df in data.items():
        dates = get_event_dates(df, conditions, cooldown_sessions)
        if dates:
            result[ticker] = dates
            logger.info(f"{ticker}: {len(dates)} independent events")
    return result
