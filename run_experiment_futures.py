#!/usr/bin/env python3
"""
run_experiment_futures.py — Statistical Edge Lab en ROFEX

Señal desde equity (GGAL.BA), ejecución en futuros (GGAL/AGO26)
con bid/ask reales y costos ROFEX (0.46% RT).

Uso:
    python run_experiment_futures.py \\
        --event config/events/exp_005.yaml \\
        --universe config/universe.yaml \\
        --futures-symbol GGAL/AGO26
"""

import argparse
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

SRC_DIR = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_DIR))

from data_loader import (
    load_data, load_ccl_series, load_benchmark,
    is_argentine, market_for_ticker, instrument_info,
)
from currency_adjustment import dollarize_dataframe, dollarize_single_benchmark
from feature_engine import compute_all_features
from regime_detector import compute_all_regimes
from event_detector import load_event_config, detect_events_all_assets
from forward_returns import calculate_forward_returns
from futures_execution import (
    FuturesCostModel, execute_long_trade,
    fill_at_best_ask, fill_at_best_bid,
)
from futures_loader import get_stream_ticks, snapshot_stream_to_daily

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_exp_futures")


def make_snapshot():
    """Create a fresh snapshot of the ROFEX DB for analysis."""
    import os, signal, time

    collector_pid = None
    for pid_str in os.listdir("/proc"):
        try:
            with open(f"/proc/{pid_str}/cmdline", "rb") as f:
                cmdline = f.read().decode()
                if "colector_rofex" in cmdline:
                    collector_pid = int(pid_str)
                    break
        except (OSError, ValueError):
            continue

    if collector_pid is None:
        logger.warning("Collector not running — using existing DB (may be locked)")
        return Path.home() / "shared" / "data" / "db" / "duckdb" / "rofex.duckdb"

    src = Path.home() / "shared" / "data" / "db" / "duckdb" / "rofex.duckdb"
    dst = Path("/tmp/rofex_snapshot.duckdb")

    # Brief pause to get clean snapshot
    os.kill(collector_pid, signal.SIGSTOP)
    time.sleep(0.5)
    import shutil
    shutil.copy2(str(src), str(dst))
    os.kill(collector_pid, signal.SIGCONT)
    logger.info(f"Snapshot: {dst} ({dst.stat().st_size / 1024 / 1024:.0f}MB)")
    return dst


def run_experiment_futures(
    event_path: str,
    universe_path: str,
    futures_symbol: str = "GGAL/AGO26",
    snapshot_path: str = None,
):
    """Run experiment: equity signal → futures execution."""

    # ── Load config ──
    logger.info(f"Loading event: {event_path}")
    event_config = load_event_config(event_path)
    exp = event_config.get("experiment", {})
    event = event_config.get("event", {})
    conditions = event.get("conditions", [])
    cooldown = event.get("cooldown_sessions", 20)
    horizons = event.get("forward_horizons", [3, 5, 10])
    primary_h = event_config.get("research", {}).get("primary_horizon", 5)

    logger.info(f"Experiment: {exp.get('id')} | Primary horizon: {primary_h}d")
    logger.info(f"Futures symbol: {futures_symbol}")

    # ── Load equity data (for signal) ──
    import yaml
    with open(universe_path) as f:
        universe_cfg = yaml.safe_load(f)

    # Signal from GGAL.BA
    signal_ticker = "GGAL.BA"
    date_start = universe_cfg.get("date_start", "2015-01-01")
    date_end = universe_cfg.get("date_end")

    # For futures data, we only have ~2 months. Align equity dates.
    equity = load_data([signal_ticker], date_start, date_end)
    if signal_ticker not in equity:
        logger.error(f"No equity data for {signal_ticker}")
        sys.exit(1)

    equity_df = equity[signal_ticker]

    # CCL and USD adjustment
    ccl = load_ccl_series(date_start, date_end)
    equity_usd = dollarize_dataframe(
        {signal_ticker: equity_df}, ccl
    )[signal_ticker]

    # Features in USD
    equity_feat = compute_all_features(
        equity_usd, price_col="close_usd",
        high_col="high_usd", low_col="low_usd",
    )

    # ── Regimes from dollarized benchmark (Audit 4) ──
    benchmark_ticker = universe_cfg.get("benchmark", "^MERV")
    bench = load_benchmark(benchmark_ticker, date_start, date_end)
    if bench is not None and is_argentine(benchmark_ticker) and ccl is not None:
        bench_usd = dollarize_single_benchmark(bench, ccl)
        bench_feat = compute_all_features(
            bench_usd, price_col="close_usd",
            high_col="high_usd", low_col="low_usd",
        )
        equity_feat = compute_all_regimes(equity_feat, bench_feat["close_usd"])
        logger.info("  Regimes computed from USD benchmark")
    else:
        logger.warning("  Regimes not available — may affect event detection")

    # ── Detect events ──
    logger.info("Detecting events on GGAL.BA...")
    events = detect_events_all_assets(
        {signal_ticker: equity_feat}, conditions, cooldown
    )

    signal_dates = events.get(signal_ticker, [])
    logger.info(f"  {len(signal_dates)} independent events on {signal_ticker} (full history)")

    if not signal_dates:
        logger.warning("No events detected.")
        return

    # ── Load futures data ──
    logger.info(f"Loading futures data: {futures_symbol}")
    if snapshot_path is None:
        snapshot_path = str(make_snapshot())

    stream_ticks = get_stream_ticks(futures_symbol, snapshot_path)
    if stream_ticks is None or stream_ticks.empty:
        logger.error("No futures data available.")
        return

    # Set timestamp as index for time-based lookups
    stream_ticks = stream_ticks.set_index("timestamp").sort_index()

    f_min = stream_ticks.index.min()
    f_max = stream_ticks.index.max()
    logger.info(f"  Futures data: {len(stream_ticks)} ticks [{f_min.date()} → {f_max.date()}]")

    # Filter signal dates to futures range
    signal_dates_in_range = [
        d for d in signal_dates
        if pd.Timestamp(d.date()) >= f_min.normalize() and pd.Timestamp(d.date()) <= f_max.normalize()
    ]
    logger.info(f"  Events in futures range: {len(signal_dates_in_range)} (filtered from {len(signal_dates)})")

    # ── Execute trades ──
    logger.info(f"Executing trades on {futures_symbol}...")
    cost_model = FuturesCostModel()

    trades = []
    skipped_no_futures = 0
    skipped_no_liquidity = 0
    for signal_date in signal_dates_in_range:
        # Signal at close of equity T → enter at open of T+1
        # Look for futures data on T+1 (with time component)
        entry_target = pd.Timestamp(signal_date.date()) + pd.Timedelta(days=1)

        # Skip if no futures data around this date
        for h in horizons:
            trade = execute_long_trade(
                stream_ticks, entry_target, h,
                lookahead_tolerance="48h",
            )
            if trade:
                net_ret = cost_model.net_return(trade["gross_return_pct"])
                trades.append({
                    "signal_date": signal_date.date(),
                    "entry_date": trade["entry_ts"].date() if pd.notna(trade["entry_ts"]) else None,
                    "exit_date": trade["exit_ts"].date() if pd.notna(trade["exit_ts"]) else None,
                    "horizon": h,
                    "entry_price": trade["entry_price"],
                    "exit_price": trade["exit_price"],
                    "gross_return_pct": trade["gross_return_pct"],
                    "spread_cost_pct": trade["spread_cost_pct"],
                    "net_return_pct": net_ret,
                })
            else:
                skipped_no_liquidity += 1

    logger.info(f"  Executed: {len(trades)} trades | Skipped (no liquidity): {skipped_no_liquidity}")

    if not trades:
        logger.warning("No trades executed.")
        return

    # ── Results ──
    results_df = pd.DataFrame(trades)
    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)

    for h in horizons:
        h_df = results_df[results_df["horizon"] == h]
        if h_df.empty:
            continue
        logger.info(f"\n  Horizon {h}d ({len(h_df)} trades):")
        logger.info(f"    Gross  mean: {h_df['gross_return_pct'].mean():+.2f}% | median: {h_df['gross_return_pct'].median():+.2f}%")
        logger.info(f"    Net    mean: {h_df['net_return_pct'].mean():+.2f}% | median: {h_df['net_return_pct'].median():+.2f}%")
        logger.info(f"    Win rate: {h_df['net_return_pct'].gt(0).mean()*100:.0f}%")
        logger.info(f"    Avg spread: {h_df['spread_cost_pct'].mean():.2f}%")

    logger.info(f"\n  Cost model: {cost_model.total_rt_pct}% RT")
    logger.info(f"  Futures range: {f_min.date()} → {f_max.date()}")
    logger.info(f"  Equity events (total): {len(signal_dates)}")

    return results_df


def main():
    parser = argparse.ArgumentParser(
        description="Statistical Edge Lab — ROFEX Futures"
    )
    parser.add_argument("--event", required=True, help="Event YAML config")
    parser.add_argument("--universe", default="config/universe.yaml")
    parser.add_argument("--futures-symbol", default="GGAL/AGO26",
                        help="Futures contract symbol")
    parser.add_argument("--snapshot", help="Path to duckdb snapshot")
    args = parser.parse_args()

    run_experiment_futures(
        args.event, args.universe,
        futures_symbol=args.futures_symbol,
        snapshot_path=args.snapshot,
    )


if __name__ == "__main__":
    main()
