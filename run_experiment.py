#!/usr/bin/env python3
"""
run_experiment.py — Statistical Edge Lab CLI

Usage:
    python run_experiment.py --event config/events/exp_001.yaml --universe config/universe.yaml
    python run_experiment.py --list
    python run_experiment.py --show <experiment_id>
"""

import argparse
import sys
import logging
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yaml

SRC_DIR = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_DIR))

from data_loader import (
    load_data, load_benchmark, load_ccl_series,
    instrument_info, market_for_ticker, is_argentine,
)
from data_validator import validate_all
from currency_adjustment import dollarize_dataframe
from feature_engine import compute_all_features
from event_detector import load_event_config, detect_events_all_assets
from forward_returns import calculate_forward_returns, compute_overall_metrics
from regime_detector import compute_all_regimes
from baseline_comparator import compute_all_baselines
from cost_model import load_costs, summarize_costs, roundtrip_cost_total
from validator import TemporalSplit
from robustness import run_all_robustness
from report_generator import generate_summary, make_decision

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_experiment")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def resolve_results_dir(experiment_id: str) -> Path:
    return Path(__file__).parent / "results" / experiment_id


def list_experiments():
    results_dir = Path(__file__).parent / "results"
    if not results_dir.exists() or not any(results_dir.iterdir()):
        print("No experiments found.")
        return
    for d in sorted(results_dir.iterdir()):
        if d.is_dir():
            meta = d / "metadata.json"
            if meta.exists():
                with open(meta) as f:
                    md = json.load(f)
                print(f"  {md.get('experiment_id', d.name):20s} → {md.get('decision', '?')} ({md.get('generated_at', '?')})")
            else:
                print(f"  {d.name:20s} → (no metadata)")


def show_experiment(experiment_id: str):
    results_dir = resolve_results_dir(experiment_id)
    summary = results_dir / "summary.md"
    if summary.exists():
        print(summary.read_text())
    else:
        print(f"No results for '{experiment_id}'.")


def run_experiment(event_path: str, universe_path: str, costs_path: str):
    logger.info(f"Loading event config: {event_path}")
    event_config = load_event_config(event_path)
    exp = event_config.get("experiment", {})
    event = event_config.get("event", {})
    val_config = event_config.get("validation", {})

    experiment_id = exp.get("id", "unnamed")
    logger.info(f"Experiment: {experiment_id}")

    logger.info(f"Loading universe: {universe_path}")
    universe_config = load_config(universe_path)

    # ── P0 #10: Separate targets from references ──
    targets_raw = universe_config.get("targets", [])
    if not targets_raw:
        # Fallback for old config format: argentina.tickers are targets
        targets_raw = [{"ticker": t, "market": "argentina"}
                       for t in universe_config.get("argentina", {}).get("tickers", [])]
    target_tickers = [t["ticker"] for t in targets_raw]

    references_raw = universe_config.get("references", [])
    if not references_raw:
        references_raw = [{"ticker": t, "role": "benchmark"}
                          for t in universe_config.get("reference", {}).get("tickers", [])]
    reference_tickers = [r["ticker"] for r in references_raw]

    benchmark_ticker = universe_config.get("benchmark", "^MERV")
    date_start = universe_config.get("date_start", "2015-01-01")
    date_end = universe_config.get("date_end", "2026-07-17")

    all_tickers = list(dict.fromkeys(target_tickers + reference_tickers + [benchmark_ticker]))
    logger.info(f"Targets: {target_tickers}")
    logger.info(f"References: {reference_tickers}")
    logger.info(f"Period: {date_start} → {date_end}")

    # ── STEP 1: Load data ──
    logger.info("=" * 60)
    logger.info("STEP 1: Loading data")
    data = load_data(all_tickers, date_start, date_end)
    if not data:
        logger.error("No data loaded. Aborting.")
        sys.exit(1)

    bench = load_benchmark(benchmark_ticker, date_start, date_end)

    # ── STEP 2: Validate data quality (exclude benchmark indices from volume checks) ──
    logger.info("=" * 60)
    logger.info("STEP 2: Validating data quality")
    # Filter out benchmark indices that don't have volume
    validate_data = {t: d for t, d in data.items() if not t.startswith("^")}
    try:
        reports = validate_all(validate_data, date_start, date_end)
    except ValueError as e:
        logger.error(f"Data validation failed: {e}")
        sys.exit(1)

    # ── STEP 3: Currency adjustment ──
    logger.info("=" * 60)
    logger.info("STEP 3: Adjusting for currency")
    ccl = load_ccl_series(date_start, date_end)
    if ccl is None:
        ar_targets = [t for t in target_tickers if is_argentine(t)]
        if ar_targets:
            logger.error(f"CCL data unavailable but Argentine targets exist: {ar_targets}. Aborting.")
            sys.exit(1)
    data_usd = dollarize_dataframe(data, ccl)

    # ── STEP 4: Compute features in hard currency ──
    logger.info("=" * 60)
    logger.info("STEP 4: Computing features (USD)")
    for ticker in list(data_usd.keys()):
        is_ar = is_argentine(ticker)
        if is_ar:
            data_usd[ticker] = compute_all_features(
                data_usd[ticker],
                price_col="close_usd",
                high_col="high_usd",
                low_col="low_usd",
            )
        else:
            data_usd[ticker] = compute_all_features(data_usd[ticker])
        logger.info(f"  {ticker}: {len(data_usd[ticker])} rows (USD features={is_ar})")

    # ── STEP 5: Market regimes ──
    logger.info("=" * 60)
    logger.info("STEP 5: Classifying market regimes")
    if bench is not None:
        bench_feat = compute_all_features(bench)
        for ticker in data_usd:
            data_usd[ticker] = compute_all_regimes(
                data_usd[ticker], bench_feat["close"]
            )
        logger.info("  Regimes computed from benchmark")

    # ── STEP 6: Detect events (ONLY on targets) ──
    logger.info("=" * 60)
    logger.info("STEP 6: Detecting events")
    conditions = event.get("conditions", {})
    cooldown = event.get("cooldown_sessions", event.get("cooldown_days", 10))
    horizons = event.get("forward_horizons", [5])

    # Only detect on target tickers (P0 #10)
    target_data = {t: data_usd[t] for t in target_tickers if t in data_usd}
    events = detect_events_all_assets(target_data, conditions, cooldown)

    all_event_dates = []
    for ticker, dates in events.items():
        for d in dates:
            all_event_dates.append((ticker, d))
    n_total = len(all_event_dates)
    logger.info(f"  Total independent events: {n_total}")

    if n_total == 0:
        logger.warning("No events detected. Aborting.")
        sys.exit(0)

    # ── STEP 7: Forward returns (entry_mode=next_open per P0 #2) ──
    logger.info("=" * 60)
    logger.info("STEP 7: Calculating forward returns + MFE/MAE")
    raw_returns = {}
    for ticker, dates in events.items():
        raw_returns[ticker] = calculate_forward_returns(
            data_usd[ticker], dates, horizons,
            entry_mode="next_open",
        )

    # Apply transaction costs per event (P0 #7)
    cost_config = load_costs(costs_path)
    for ticker in raw_returns:
        market = market_for_ticker(ticker)
        cost_pct = roundtrip_cost_total(cost_config, market) * 100
        for h in horizons:
            if h in raw_returns[ticker] and not raw_returns[ticker][h].empty:
                df = raw_returns[ticker][h]
                df["transaction_cost_pct"] = cost_pct
                df["net_return_pct"] = df["forward_return"] - cost_pct

    # Combine all events for metrics
    combined_returns = {}
    for h in horizons:
        all_fr = []
        for ticker in raw_returns:
            if h in raw_returns[ticker] and not raw_returns[ticker][h].empty:
                df = raw_returns[ticker][h].copy()
                df["ticker"] = ticker
                all_fr.append(df)
        combined_returns[h] = pd.concat(all_fr) if all_fr else pd.DataFrame()

    metrics = compute_overall_metrics(combined_returns)

    # ── STEP 8: Baselines ──
    logger.info("=" * 60)
    logger.info("STEP 8: Computing baselines")
    all_baselines = {}
    for ticker, dates in events.items():
        if ticker in data_usd and len(dates) > 0:
            ticker_bl = compute_all_baselines(
                data_usd[ticker], dates, horizons,
                bench_feat if bench is not None else None,
                cooldown_sessions=cooldown,
            )
            all_baselines[ticker] = ticker_bl

    # Per-horizon aggregate baselines (event-weighted)
    baselines = {}
    for h in horizons:
        unconditional_vals = []
        regime_vals = []
        benchmark_vals = []
        weights = []
        for ticker, bl in all_baselines.items():
            if h in bl:
                n_events = len(events.get(ticker, []))
                unconditional_vals.append(bl[h]["unconditional"] * n_events)
                regime_vals.append(bl[h]["regime_conditioned"] * n_events)
                benchmark_vals.append(bl[h]["benchmark"] * n_events)
                weights.append(n_events)
        total_w = sum(weights) or 1
        baselines[h] = {
            "unconditional": sum(unconditional_vals) / total_w if unconditional_vals else 0.0,
            "regime_conditioned": sum(regime_vals) / total_w if regime_vals else 0.0,
            "benchmark": sum(benchmark_vals) / total_w if benchmark_vals else 0.0,
        }

    # ── STEP 9: Costs summary ──
    logger.info("=" * 60)
    logger.info("STEP 9: Transaction costs")
    cost_summary = summarize_costs(cost_config)

    # ── STEP 10: Temporal split (P0 #8) ──
    logger.info("=" * 60)
    logger.info("STEP 10: Temporal split")
    splitter = TemporalSplit(
        discovery_pct=val_config.get("discovery_pct", 60) / 100,
        validation_pct=val_config.get("validation_pct", 20) / 100,
        holdout_pct=val_config.get("holdout_pct", 20) / 100,
    )
    flat_dates = [d for _, d in all_event_dates]
    splitter.fit(data_usd, flat_dates)

    # Per-split metrics
    split_metrics = {}
    for split_name in ["discovery", "validation", "holdout"]:
        split_events = {}
        for ticker, dates in events.items():
            filtered = [d for d in dates if splitter.get_period(d) == split_name]
            if filtered:
                split_events[ticker] = filtered
        # Compute forward returns for this split
        split_raw = {}
        for ticker, dates in split_events.items():
            split_raw[ticker] = calculate_forward_returns(
                data_usd[ticker], dates, horizons,
                entry_mode="next_open",
            )
        split_combined = {}
        for h in horizons:
            all_fr = []
            for ticker in split_raw:
                if h in split_raw[ticker] and not split_raw[ticker][h].empty:
                    df = split_raw[ticker][h].copy()
                    df["ticker"] = ticker
                    all_fr.append(df)
            split_combined[h] = pd.concat(all_fr) if all_fr else pd.DataFrame()

        split_metrics[split_name] = compute_overall_metrics(split_combined)

    # ── STEP 11: Robustness ──
    logger.info("=" * 60)
    logger.info("STEP 11: Running robustness tests")
    robustness_results = run_all_robustness(
        target_data, conditions, cooldown, horizons
    )
    from robustness import bootstrap_ci
    for h in horizons:
        key = f"bootstrap_{h}d"
        if key not in robustness_results:
            if h in combined_returns and not combined_returns[h].empty:
                rets = combined_returns[h]["forward_return"].values
                robustness_results[key] = bootstrap_ci(rets)
            else:
                robustness_results[key] = {"mean": 0, "ci_lower": 0, "ci_upper": 0, "std_error": 0}

    # ── STEP 12: Decision ──
    logger.info("=" * 60)
    logger.info("STEP 12: Making decision")
    decision, reason = make_decision(metrics, robustness_results, cost_summary, n_total)
    logger.info(f"Decision: {decision}")
    logger.info(f"Reason: {reason}")

    # ── STEP 13: Generate report ──
    logger.info("=" * 60)
    logger.info("STEP 13: Generating report")
    output_dir = resolve_results_dir(experiment_id)
    report_data = {
        "config": event_config,
        "event_data": {"raw_returns": {str(k): v for k, v in combined_returns.items()}},
        "metrics": metrics,
        "baselines": baselines,
        "cost_summary": cost_summary,
        "robustness_results": robustness_results,
        "decision": decision,
        "decision_reason": reason,
        "output_dir": output_dir,
    }
    summary_path = generate_summary(**report_data)

    print("\n" + "=" * 60)
    print(f"  EXPERIMENT: {experiment_id}")
    print(f"  Events: {n_total}")
    print(f"  Decision: {decision}")
    print(f"  Reason: {reason}")
    print(f"  Report: {summary_path}")
    print("=" * 60)

    return decision


def main():
    parser = argparse.ArgumentParser(
        description="Statistical Edge Lab — Evaluate market event hypotheses"
    )
    parser.add_argument("--event", help="Path to event YAML configuration")
    parser.add_argument("--universe", default="config/universe.yaml",
                        help="Path to universe YAML")
    parser.add_argument("--costs", default="config/costs.yaml",
                        help="Path to costs YAML")
    parser.add_argument("--list", action="store_true",
                        help="List completed experiments")
    parser.add_argument("--show", metavar="EXPERIMENT_ID",
                        help="Show report for a completed experiment")

    args = parser.parse_args()

    if args.list:
        list_experiments()
        return
    if args.show:
        show_experiment(args.show)
        return
    if not args.event:
        parser.print_help()
        sys.exit(1)

    run_experiment(args.event, args.universe, args.costs)


if __name__ == "__main__":
    main()
