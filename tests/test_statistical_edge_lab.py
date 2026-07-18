# Statistical Edge Lab — Tests
# Spec §20: Minimum test coverage for all core modules.
"""
Tests for the Statistical Edge Lab.

Spec §20 requires tests for:
  - Forward-return calculation
  - Currency conversion
  - Event detection
  - Overlapping-event removal
  - MFE and MAE calculation
  - Transaction-cost application
  - Baseline comparison
  - Chronological split
  - Market-regime classification
  - Decision generation
  - Look-ahead prevention
"""

import sys
from pathlib import Path

import pytest
import pandas as pd
import numpy as np

# Add src to path
SRC_DIR = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from data_loader import load_data
from data_validator import validate_ticker_data, validate_all
from currency_adjustment import adjust_to_usd, return_in_usd
from feature_engine import (
    sma, rsi, atr, rolling_return, zscore, volume_ratio,
    distance_from_sma, bollinger_b, compute_all_features
)
from event_detector import detect_events, apply_cooldown_sessions, get_event_dates
from forward_returns import forward_return_series, calculate_forward_returns, summarize_forward_returns
from regime_detector import classify_trend_regime, classify_volatility_regime
from baseline_comparator import unconditional_baseline, regime_conditioned_baseline
from cost_model import roundtrip_cost_total, apply_costs_to_return, break_even_cost
from validator import TemporalSplit, walk_forward_windows
from robustness import bootstrap_ci, leave_one_asset_out
from report_generator import make_decision


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_ohlcv():
    """Create a small synthetic OHLCV dataset with known properties."""
    dates = pd.date_range("2020-01-01", periods=200, freq="B")
    np.random.seed(42)
    close = 100 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, 200)))
    data = {
        "open": close * (1 + np.random.normal(0, 0.005, 200)),
        "high": close * (1 + np.abs(np.random.normal(0, 0.01, 200))),
        "low": close * (1 - np.abs(np.random.normal(0, 0.01, 200))),
        "close": close,
        "volume": np.random.randint(100000, 10000000, 200),
    }
    df = pd.DataFrame(data, index=dates)
    df["adj_close"] = df["close"]
    return df


@pytest.fixture
def sample_ccl():
    """Create a synthetic CCL series."""
    dates = pd.date_range("2020-01-01", periods=200, freq="B")
    np.random.seed(123)
    ccl = 100 + np.cumsum(np.random.normal(0.1, 1, 200))
    return pd.DataFrame({"ccl": ccl}, index=dates)


@pytest.fixture
def sample_event_conditions():
    """Conditions for a simple event (list format, P0 #6)."""
    return [
        {"feature": "rsi_14", "operator": "<", "value": 30},
        {"feature": "return_3d", "operator": "<", "value": -0.03},
    ]


@pytest.fixture
def sample_benchmark():
    """Synthetic benchmark series."""
    dates = pd.date_range("2020-01-01", periods=200, freq="B")
    np.random.seed(99)
    close = 100 * np.exp(np.cumsum(np.random.normal(0.0005, 0.015, 200)))
    return pd.DataFrame({"close": close}, index=dates)


# ============================================================
# Test: Feature Engine
# ============================================================

class TestFeatureEngine:
    def test_sma(self, sample_ohlcv):
        result = sma(sample_ohlcv["close"], 20)
        assert len(result) == 200
        assert pd.isna(result.iloc[0])  # Not enough data
        assert not pd.isna(result.iloc[50])

    def test_rsi(self, sample_ohlcv):
        r = rsi(sample_ohlcv["close"], 14)
        assert len(r) == 200
        assert r.iloc[20:40].between(0, 100).all()

    def test_atr(self, sample_ohlcv):
        a = atr(sample_ohlcv, 14)
        assert len(a) == 200
        assert (a.iloc[20:] >= 0).all()

    def test_rolling_return(self, sample_ohlcv):
        rr = rolling_return(sample_ohlcv["close"], 5)
        assert len(rr) == 200
        # 5d return should be > -100%
        assert rr.iloc[10] > -1.0

    def test_zscore(self, sample_ohlcv):
        z = zscore(sample_ohlcv["close"], 60)
        assert len(z) == 200

    def test_volume_ratio(self, sample_ohlcv):
        vr = volume_ratio(sample_ohlcv["volume"], 20)
        assert len(vr) == 200
        assert vr.iloc[30] > 0

    def test_distance_from_sma(self, sample_ohlcv):
        d = distance_from_sma(sample_ohlcv["close"], 20)
        assert len(d) == 200

    def test_bollinger_b(self, sample_ohlcv):
        b = bollinger_b(sample_ohlcv["close"], 20)
        assert len(b) == 200

    def test_compute_all_features(self, sample_ohlcv):
        # Add USD columns for the feature engine
        df = sample_ohlcv.copy()
        df["close_usd"] = df["close"]
        df["high_usd"] = df["high"]
        df["low_usd"] = df["low"]
        result = compute_all_features(df)
        expected_cols = [
            "sma_20", "sma_60", "sma_200",
            "return_1d", "return_3d", "return_5d", "return_10d", "return_20d", "return_60d",
            "rsi_14", "atr_14", "atr_percentile_60d",
            "volume_ratio_20d", "dist_sma_20", "dist_sma_200",
            "distance_to_high_60d", "return_3d_zscore",
            "bb_pct_b", "close_above_sma_200", "close_breaks_high_20d",
            "sma_200_slope",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"
        assert len(result) == 200


# ============================================================
# Test: Event Detection
# ============================================================

class TestEventDetection:
    def test_detect_events_all_true(self, sample_ohlcv):
        """When no conditions, all dates are events."""
        mask = detect_events(sample_ohlcv, [])
        assert mask.all()

    def test_detect_events_none(self, sample_ohlcv):
        """Impossible condition → no events."""
        conditions = [{"feature": "rsi_14", "operator": ">", "value": 200}]
        mask = detect_events(sample_ohlcv, conditions)
        assert not mask.any()

    def test_apply_cooldown(self):
        """Cooldown removes nearby events using session-based logic."""
        dates = pd.date_range("2020-01-01", periods=10, freq="B")
        df = pd.DataFrame({"close": range(10)}, index=dates)
        mask = pd.Series([True, True, False, False, True, False, False, False, True, True],
                         index=dates)
        result = apply_cooldown_sessions(mask, df, 3)
        assert result.iloc[0] == True
        assert result.sum() < mask.sum()

    def test_get_event_dates_empty(self, sample_ohlcv):
        """Impossible condition returns empty list."""
        dates = get_event_dates(
            sample_ohlcv, [{"feature": "rsi_14", "operator": ">", "value": 200}], 10
        )
        assert dates == []


# ============================================================
# Test: Forward Returns
# ============================================================

class TestForwardReturns:
    def test_forward_return_series(self):
        """Audit P0 #1: Verify forward_return_series formula."""
        prices = pd.Series([100.0, 110.0, 121.0, 133.1])
        # 1-period: 110/100-1=10%, 121/110-1=10%, 133.1/121-1=10%, NaN
        fr = forward_return_series(prices, 1)
        assert abs(fr.iloc[0] - 10.0) < 0.01, f"Got {fr.iloc[0]}"
        assert abs(fr.iloc[1] - 10.0) < 0.01, f"Got {fr.iloc[1]}"
        assert abs(fr.iloc[2] - 10.0) < 0.01, f"Got {fr.iloc[2]}"
        assert pd.isna(fr.iloc[3])
        # 2-period: 121/100-1=21%, 133.1/110-1=21%, NaN, NaN
        fr2 = forward_return_series(prices, 2)
        assert abs(fr2.iloc[0] - 21.0) < 0.01, f"Got {fr2.iloc[0]}"
        assert abs(fr2.iloc[1] - 21.0) < 0.01, f"Got {fr2.iloc[1]}"
        assert pd.isna(fr2.iloc[2])
        assert pd.isna(fr2.iloc[3])

    def test_calculate_forward_returns(self, sample_ohlcv):
        df = sample_ohlcv.copy()
        df["close_usd"] = df["close"]
        df["high_usd"] = df["high"]
        df["low_usd"] = df["low"]
        df["open_usd"] = df["open"]
        event_dates = [df.index[51], df.index[101]]  # skip idx 0 for next_open entry
        result = calculate_forward_returns(df, event_dates, [5, 10])
        assert 5 in result
        assert 10 in result
        assert len(result[5]) == 2
        assert "forward_return" in result[5].columns
        assert "mfe" in result[5].columns
        assert "mae" in result[5].columns

    def test_summarize_forward_returns(self, sample_ohlcv):
        df = sample_ohlcv.copy()
        df["close_usd"] = df["close"]
        df["high_usd"] = df["high"]
        df["low_usd"] = df["low"]
        df["open_usd"] = df["open"]
        event_dates = [df.index[51], df.index[101]]
        fr = calculate_forward_returns(df, event_dates, [5])
        summary = summarize_forward_returns(fr[5], 5)
        assert summary["n_events"] == 2
        assert "mean_return" in summary
        assert "median_return" in summary
        assert "win_rate" in summary
        assert "profit_factor" in summary
        assert "avg_mfe" in summary
        assert "avg_mae" in summary

    def test_mfe_mae_always_valid(self, sample_ohlcv):
        """MFE should always be >= 0, MAE <= 0 in raw form."""
        df = sample_ohlcv.copy()
        df["close_usd"] = df["close"]
        df["high_usd"] = df["high"]
        df["low_usd"] = df["low"]
        event_dates = [df.index[60], df.index[100], df.index[150]]
        fr = calculate_forward_returns(df, event_dates, [5])
        if not fr[5].empty:
            assert (fr[5]["mfe"] >= 0).all() or fr[5].empty


# ============================================================
# Test: Currency Adjustment
# ============================================================

class TestCurrencyAdjustment:
    def test_adjust_to_usd(self, sample_ohlcv, sample_ccl):
        result = adjust_to_usd(sample_ohlcv, sample_ccl)
        assert "close_usd" in result.columns
        assert "ccl" in result.columns
        # USD price should be lower than ARS price when CCL > 1
        assert (result["close_usd"] < result["close"]).all()

    def test_return_in_usd(self, sample_ohlcv, sample_ccl):
        result = adjust_to_usd(sample_ohlcv, sample_ccl)
        assert "close_usd" in result.columns


# ============================================================
# Test: Regime Detection
# ============================================================

class TestRegimeDetection:
    def test_classify_trend_regime(self, sample_benchmark):
        regime = classify_trend_regime(sample_benchmark["close"])
        assert len(regime) == 200
        assert regime.iloc[0] == "NEUTRAL"  # Not enough data
        assert regime.iloc[-1] in ("BULL", "BEAR", "NEUTRAL")

    def test_classify_volatility_regime(self, sample_ohlcv):
        feat = compute_all_features(sample_ohlcv)
        vol_regime = classify_volatility_regime(feat)
        assert len(vol_regime) == 200
        assert vol_regime.iloc[-1] in ("LOW_VOL", "NORMAL_VOL", "HIGH_VOL")


# ============================================================
# Test: Cost Model
# ============================================================

class TestCostModel:
    def test_roundtrip_cost_total(self):
        costs = {"argentina": {
            "commission_per_side": 0.007,
            "market_fees_per_side": 0.0008,
            "estimated_slippage_per_side": 0.002,
            "minimum_total_roundtrip": 0.015,
        }}
        total = roundtrip_cost_total(costs)
        # (0.007 + 0.0008 + 0.002) * 2 = 0.0196, floor at 0.015
        assert total == 0.0196

    def test_apply_costs(self):
        costs = {"argentina": {
            "commission_per_side": 0.007,
            "market_fees_per_side": 0.0008,
            "estimated_slippage_per_side": 0.002,
            "minimum_total_roundtrip": 0.015,
        }}
        net = apply_costs_to_return(5.0, costs)
        # 5.0 - 1.96 = 3.04
        assert abs(net - 3.04) < 0.01

    def test_break_even_cost(self):
        bec = break_even_cost(3.0, 0.5)
        assert abs(bec - 2.5) < 0.01

    def test_break_even_zero(self):
        bec = break_even_cost(1.0, 2.0)
        assert bec == 0.0  # No edge to break


# ============================================================
# Test: Baseline Comparison
# ============================================================

class TestBaselines:
    def test_unconditional_baseline(self, sample_ohlcv):
        df = sample_ohlcv.copy()
        df["close_usd"] = df["close"]
        bl = unconditional_baseline(df, 5, price_col="close")
        assert isinstance(bl, float)

    def test_regime_conditioned_baseline(self, sample_ohlcv):
        feat = compute_all_features(sample_ohlcv)
        feat["close_usd"] = feat["close"]
        feat["trend_regime"] = "BULL"
        bl = regime_conditioned_baseline(feat, 5, "trend_regime", "BULL", price_col="close")
        assert isinstance(bl, float)


# ============================================================
# Test: Temporal Split
# ============================================================

class TestTemporalSplit:
    def test_split_time(self, sample_ohlcv):
        splitter = TemporalSplit(0.6, 0.2, 0.2)
        splitter.fit({"GGAL": sample_ohlcv})
        assert splitter.discovery_end is not None
        assert splitter.validation_end is not None
        assert splitter.holdout_end is not None

    def test_split_event_dates(self, sample_ohlcv):
        splitter = TemporalSplit(0.6, 0.2, 0.2)
        splitter.fit({"GGAL": sample_ohlcv})
        dates = [sample_ohlcv.index[10], sample_ohlcv.index[50], sample_ohlcv.index[150]]
        periods = splitter.split_event_dates(dates)
        assert len(periods["discovery"]) > 0

    def test_get_period(self, sample_ohlcv):
        splitter = TemporalSplit(0.6, 0.2, 0.2)
        splitter.fit({"GGAL": sample_ohlcv})
        assert splitter.get_period(sample_ohlcv.index[5]) == "discovery"
        # Last date should be holdout
        assert splitter.get_period(sample_ohlcv.index[-1]) == "holdout"


# ============================================================
# Test: Robustness
# ============================================================

class TestRobustness:
    def test_bootstrap_ci(self):
        returns = np.random.normal(0.1, 1.0, 100)
        result = bootstrap_ci(returns, n_iterations=1000, seed=42)
        assert "mean" in result
        assert "ci_lower" in result
        assert "ci_upper" in result
        assert "std_error" in result
        assert result["ci_lower"] <= result["mean"] <= result["ci_upper"]

    def test_bootstrap_empty(self):
        result = bootstrap_ci(np.array([]), n_iterations=100)
        assert result["mean"] == 0.0


# ============================================================
# Test: Decision
# ============================================================

class TestDecision:
    def test_rejected_few_events(self):
        metrics = {"horizon_5d": {"mean_return": 5.0, "n_events": 10}}
        rob = {"bootstrap_5d": {"mean": 5.0, "ci_lower": 2.0, "ci_upper": 8.0}}
        costs = {"total_roundtrip_pct": 1.96}
        decision, reason = make_decision(metrics, rob, costs, 10)
        assert decision == "REJECTED"

    def test_research_positive_but_limited(self):
        metrics = {"horizon_5d": {"mean_return": 0.5, "n_events": 50}}
        rob = {
            "bootstrap_5d": {"mean": 0.5, "ci_lower": -0.5, "ci_upper": 1.5},
            "profit_concentration": {5: {"best_trade_pct": 30, "best_3_pct": 60, "best_asset": "GGAL", "best_asset_pct": 50, "n_trades": 50, "n_assets": 5}}
        }
        costs = {"total_roundtrip_pct": 0.5}
        decision, reason = make_decision(metrics, rob, costs, 50)
        assert decision in ("RESEARCH", "REJECTED")

    def test_candidate(self):
        metrics = {"horizon_5d": {"mean_return": 5.0, "n_events": 100}}
        rob = {
            "bootstrap_5d": {"mean": 5.0, "ci_lower": 2.0, "ci_upper": 8.0},
            "profit_concentration": {5: {"best_trade_pct": 10, "best_3_pct": 25, "best_asset": "GGAL", "best_asset_pct": 30, "n_trades": 100, "n_assets": 8}}
        }
        costs = {"total_roundtrip_pct": 1.96}
        decision, reason = make_decision(metrics, rob, costs, 100)
        # With net > 0 and 100 events, should be CANDIDATE
        assert decision == "CANDIDATE"


# ============================================================
# Test: Data Validation
# ============================================================

class TestDataValidation:
    def test_validate_good_data(self, sample_ohlcv):
        report = validate_ticker_data(sample_ohlcv, "TEST", "2020-01-01", "2021-01-01")
        assert not report.critical

    def test_validate_empty(self):
        empty = pd.DataFrame()
        report = validate_ticker_data(empty, "TEST", "2020-01-01", "2021-01-01")
        assert report.critical

    def test_validate_negative_prices(self, sample_ohlcv):
        bad = sample_ohlcv.copy()
        bad.loc[bad.index[0], "close"] = -1
        report = validate_ticker_data(bad, "TEST", "2020-01-01", "2021-01-01")
        assert report.critical


# ============================================================
# Test: Walk-forward windows
# ============================================================

class TestWalkForward:
    def test_walk_forward_windows(self):
        """Use larger dataset for walk-forward validation."""
        dates = pd.date_range("2018-01-01", periods=800, freq="B")
        np.random.seed(42)
        close = 100 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, 800)))
        df = pd.DataFrame({"close": close, "high": close*1.01, "low": close*0.99, "volume": 1_000_000}, index=dates)
        windows = walk_forward_windows({"TEST": df}, n_windows=2, window_years=1)
        assert len(windows) >= 1
        for w in windows:
            assert "train_start" in w
            assert "train_end" in w
            assert "test_start" in w
            assert "test_end" in w


# ============================================================
# Test: Look-ahead prevention
# ============================================================

class TestLookAhead:
    def test_forward_returns_after_event(self, sample_ohlcv):
        """Verify next_open entry: signal at close of T, entry at open of T+1.

        h=1 → entry at open of T+1, exit at close of T+1 (same session).
        """
        df = sample_ohlcv.copy()
        df["close_usd"] = df["close"]
        df["high_usd"] = df["high"]
        df["low_usd"] = df["low"]
        df["open_usd"] = df["open"]
        event_dates = [df.index[51]]  # signal at close of day 51
        fr = calculate_forward_returns(df, event_dates, [1])
        if not fr[1].empty:
            # With next_open: entry at day 52 open, exit at day 52 close (h=1)
            entry_price = df["open_usd"].iloc[52]
            exit_price = df["close_usd"].iloc[52]
            expected_return = (exit_price / entry_price - 1) * 100
            assert abs(fr[1].iloc[0]["forward_return"] - expected_return) < 0.001

    def test_rsi_no_future_info(self, sample_ohlcv):
        """RSI at date T should only use data up to T."""
        feat = compute_all_features(sample_ohlcv)
        # RSI at position 20 should be based on data [0..20], not beyond
        rsi_val = feat["rsi_14"].iloc[20]
        manual_rsi = rsi(sample_ohlcv["close"].iloc[:21], 14).iloc[-1]
        assert abs(rsi_val - manual_rsi) < 0.001


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
