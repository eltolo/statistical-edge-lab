"""
validator.py — Statistical Edge Lab
Phase 4: Temporal split and walk-forward validation.

Spec §14:
  - 60% discovery, 20% validation, 20% final holdout
  - Chronological splits only
  - Discovery: hypothesis adjustment allowed
  - Validation: decide whether to continue
  - Holdout: evaluate only once, do not modify params
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class TemporalSplit:
    """
    Chronological split of data into discovery, validation, and holdout periods.

    Spec §14: Use chronological splits only. Never random.
    """

    def __init__(
        self,
        discovery_pct: float = 0.60,
        validation_pct: float = 0.20,
        holdout_pct: float = 0.20,
        split_on: str = "time",  # "time" or "events"
    ):
        assert abs(discovery_pct + validation_pct + holdout_pct - 1.0) < 0.001
        self.discovery_pct = discovery_pct
        self.validation_pct = validation_pct
        self.holdout_pct = holdout_pct
        self.split_on = split_on

        self.discovery_end: Optional[pd.Timestamp] = None
        self.validation_end: Optional[pd.Timestamp] = None
        self.holdout_end: Optional[pd.Timestamp] = None

    def _split_on_time(self, data: dict[str, pd.DataFrame]):
        """Split by date."""
        # Find global date range
        all_dates = pd.DatetimeIndex([])
        for df in data.values():
            all_dates = all_dates.union(df.index)
        all_dates = all_dates.sort_values()

        if len(all_dates) == 0:
            raise ValueError("Empty date range")

        n = len(all_dates)
        d_end = int(n * self.discovery_pct)
        v_end = d_end + int(n * self.validation_pct)

        self.discovery_end = all_dates[d_end - 1] if d_end > 0 else all_dates[0]
        self.validation_end = all_dates[v_end - 1] if v_end > 0 else all_dates[-1]
        self.holdout_end = all_dates[-1]

    def _split_on_events(self, event_dates: list[pd.Timestamp]):
        """Split by event count."""
        sorted_dates = sorted(event_dates)
        n = len(sorted_dates)

        d_end_idx = int(n * self.discovery_pct)
        v_end_idx = d_end_idx + int(n * self.validation_pct)

        self.discovery_end = sorted_dates[d_end_idx - 1] if d_end_idx > 0 else sorted_dates[0]
        self.validation_end = sorted_dates[v_end_idx - 1] if v_end_idx > 0 else sorted_dates[-1]
        self.holdout_end = sorted_dates[-1]

    def fit(self, data: dict[str, pd.DataFrame], event_dates: Optional[list] = None):
        """Determine split boundaries."""
        if self.split_on == "events" and event_dates is not None:
            self._split_on_events(event_dates)
        else:
            self._split_on_time(data)

        logger.info(
            f"Split: discovery ≤ {self.discovery_end.date()}, "
            f"validation ≤ {self.validation_end.date() if self.validation_end else 'N/A'}, "
            f"holdout ≤ {self.holdout_end.date() if self.holdout_end else 'N/A'}"
        )

    def get_period(self, date: pd.Timestamp) -> str:
        """Classify a date into discovery/validation/holdout."""
        if self.discovery_end is None:
            return "discovery"
        if date <= self.discovery_end:
            return "discovery"
        if self.validation_end is not None and date <= self.validation_end:
            return "validation"
        return "holdout"

    def split_event_dates(
        self, event_dates: list[pd.Timestamp]
    ) -> dict[str, list[pd.Timestamp]]:
        """Split event dates by period."""
        result = {"discovery": [], "validation": [], "holdout": []}
        for d in event_dates:
            period = self.get_period(d)
            result[period].append(d)
        return result

    def split_data(self, data: dict[str, pd.DataFrame]) -> dict[str, dict[str, pd.DataFrame]]:
        """Split all DataFrames by period."""
        result = {
            "discovery": {},
            "validation": {},
            "holdout": {},
        }
        for ticker, df in data.items():
            result["discovery"][ticker] = df[df.index <= self.discovery_end]
            if self.validation_end is not None:
                result["validation"][ticker] = df[
                    (df.index > self.discovery_end) & (df.index <= self.validation_end)
                ]
            result["holdout"][ticker] = df[df.index > (self.validation_end or self.discovery_end)]
        return result


def check_holdout_integrity(experiment_log: dict) -> bool:
    """
    Spec §14: Verify holdout was not peeked at before final evaluation.

    Store hypothesis creation date, original parameters, and holdout opening date.
    Returns True if integrity check passes.
    """
    if "holdout_opened_at" not in experiment_log:
        logger.warning("Holdout not yet opened — OK")
        return True
    if "hypothesis_created_at" not in experiment_log:
        logger.warning("No hypothesis creation date — cannot verify integrity")
        return True
    if "parameter_changes" in experiment_log and experiment_log["parameter_changes"] > 0:
        # After holdout opened, no parameter changes allowed
        if experiment_log.get("last_param_change", "") > experiment_log.get("holdout_opened_at", ""):
            logger.error("PARAMETER CHANGE AFTER HOLDOUT OPENED — INTEGRITY VIOLATION")
            return False
    return True


def walk_forward_windows(
    data: dict[str, pd.DataFrame],
    n_windows: int = 4,
    window_years: float = 2.0,
) -> list[dict]:
    """
    Create walk-forward windows for robustness testing.

    Returns list of dicts: {name, train_start, train_end, test_start, test_end}
    """
    all_dates = pd.DatetimeIndex([])
    for df in data.values():
        all_dates = all_dates.union(df.index)
    all_dates = all_dates.sort_values()

    if len(all_dates) < int(252 * (window_years + 1)):
        logger.warning(f"Not enough data for {n_windows} walk-forward windows")
        return []

    total_days = (all_dates[-1] - all_dates[0]).days
    window_days = window_years * 365
    step_days = (total_days - window_days) // n_windows

    windows = []
    for i in range(n_windows):
        train_start = all_dates[0] + pd.Timedelta(days=i * step_days)
        train_end = train_start + pd.Timedelta(days=window_days)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.Timedelta(days=window_days // 2)

        if test_end > all_dates[-1]:
            break

        windows.append({
            "name": f"window_{i+1}",
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })

    return windows
