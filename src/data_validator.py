"""
data_validator.py — Statistical Edge Lab
Phase 1: Validate data quality before analysis.

Spec §7 mandatory checks:
  - Duplicate dates
  - Missing values
  - Zero or negative prices
  - Abnormal price jumps (>20% daily)
  - Periods with no volume
  - Invalid OHLC relationships (H < L, C outside [L, H], etc.)
  - Unadjusted corporate actions (detected via large gaps)
  - Missing observations (expected vs actual trading days)
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class DataQualityReport:
    """Collects validation results for one ticker."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.issues: list[dict] = []
        self.critical: bool = False
        self.n_expected_days: int = 0
        self.n_actual_days: int = 0

    def add_issue(self, severity: str, check: str, detail: str, count: int = 1):
        self.issues.append({
            "severity": severity,
            "check": check,
            "detail": detail,
            "count": count,
        })
        if severity == "CRITICAL":
            self.critical = True

    @property
    def summary(self) -> str:
        ret = f"\n[{self.ticker}] Data Quality Report"
        ret += f"\n  Days: {self.n_actual_days}/{self.n_expected_days} ({100*self.n_actual_days/max(self.n_expected_days,1):.1f}%)"
        if not self.issues:
            ret += "\n  ✅ No issues"
            return ret
        for iss in self.issues:
            icon = "🔴" if iss["severity"] == "CRITICAL" else "🟡"
            label = f" ({iss['count']}x)" if iss["count"] > 1 else ""
            ret += f"\n  {icon} [{iss['check']}] {iss['detail']}{label}"
        if self.critical:
            ret += "\n  ❌ CRITICAL: experiment should stop"
        return ret

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "n_expected_days": self.n_expected_days,
            "n_actual_days": self.n_actual_days,
            "critical": self.critical,
            "issues": self.issues,
        }


def _expected_trading_days(start: str, end: str) -> int:
    """Estimate expected trading days between two dates (AR market ≈ 252/year)."""
    from datetime import datetime
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    delta_days = (e - s).days
    return max(int(delta_days * 252 / 365), 1)


def validate_ticker_data(
    df: pd.DataFrame,
    ticker: str,
    start: str,
    end: str,
    max_daily_jump_pct: float = 20.0,
) -> DataQualityReport:
    """
    Validate a single ticker's DataFrame.

    Returns a DataQualityReport. If report.critical is True, the experiment
    should not proceed with this ticker.
    """
    report = DataQualityReport(ticker)
    report.n_expected_days = _expected_trading_days(start, end)
    report.n_actual_days = len(df)

    if df.empty:
        report.add_issue("CRITICAL", "EMPTY", "No data for this ticker")
        return report

    # 1. Duplicate dates
    if df.index.duplicated().any():
        n_dup = df.index.duplicated().sum()
        report.add_issue("WARNING", "DUPLICATE_DATES",
                         f"{n_dup} duplicate index entries", n_dup)
        # Remove duplicates for further checks
        df = df[~df.index.duplicated(keep="first")]

    # 2. Missing values
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            n_null = df[col].isnull().sum()
            if n_null > 0:
                sev = "CRITICAL" if n_null > len(df) * 0.1 else "WARNING"
                report.add_issue(sev, "MISSING_VALUES",
                                 f"{col}: {n_null} null values ({100*n_null/len(df):.1f}%)", n_null)

    # 3. Zero or negative prices
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            n_bad = (df[col] <= 0).sum()
            if n_bad > 0:
                report.add_issue("CRITICAL", "BAD_PRICES",
                                 f"{col}: {n_bad} zero/negative values", n_bad)

    # 4. Invalid OHLC relationships
    if all(c in df.columns for c in ["high", "low", "open", "close"]):
        # High < Low
        n_bad = (df["high"] < df["low"]).sum()
        if n_bad > 0:
            report.add_issue("CRITICAL", "OHLC_INVALID",
                             f"high < low on {n_bad} rows", n_bad)
        # Close outside [Low, High]
        n_bad = ((df["close"] < df["low"]) | (df["close"] > df["high"])).sum()
        if n_bad > 0:
            report.add_issue("WARNING", "OHLC_INVALID",
                             f"close outside [low, high] on {n_bad} rows", n_bad)

    # 5. Abnormal price jumps (> max_daily_jump_pct)
    if "close" in df.columns:
        pct_chg = df["close"].pct_change().abs() * 100
        n_jumps = (pct_chg > max_daily_jump_pct).sum()
        if n_jumps > 0:
            report.add_issue("WARNING", "ABNORMAL_JUMP",
                             f"{n_jumps} daily moves > {max_daily_jump_pct}% "
                             f"(potential corporate action)", n_jumps)

    # 6. Zero volume periods
    if "volume" in df.columns:
        n_zero_vol = (df["volume"] == 0).sum()
        if n_zero_vol > 0:
            sev = "CRITICAL" if n_zero_vol > len(df) * 0.1 else "WARNING"
            report.add_issue(sev, "ZERO_VOLUME",
                             f"{n_zero_vol} days with zero volume", n_zero_vol)

    # 7. Coverage ratio
    coverage = len(df) / max(report.n_expected_days, 1)
    if coverage < 0.5:
        report.add_issue("CRITICAL", "LOW_COVERAGE",
                         f"Only {len(df)}/{report.n_expected_days} days ({100*coverage:.1f}%)")

    return report


def validate_all(
    data: dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> dict[str, DataQualityReport]:
    """
    Validate all tickers in the dataset.

    Returns dict[ticker -> DataQualityReport].
    Raises ValueError if ANY ticker has critical issues.
    """
    reports = {}
    any_critical = False
    for ticker, df in data.items():
        report = validate_ticker_data(df, ticker, start, end)
        reports[ticker] = report
        logger.info(report.summary)
        if report.critical:
            any_critical = True

    if any_critical:
        critical_tickers = [t for t, r in reports.items() if r.critical]
        raise ValueError(
            f"Critical data quality issues in: {', '.join(critical_tickers)}. "
            "Fix data sources before proceeding."
        )

    return reports
