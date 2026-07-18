#!/usr/bin/env python3
"""
run_experiment.py — Statistical Edge Lab CLI

Usage:
    python run_experiment.py --event config/events/exp_001.yaml --universe config/universe.yaml
    python run_experiment.py --list
    python run_experiment.py --show <experiment_id>

Spec §6: Execution flow:
  1. Load data
  2. Validate data quality
  3. Adjust returns for currency
  4. Calculate features
  5. Detect events
  6. Remove overlapping events
  7. Calculate forward returns + MFE/MAE
  8. Compare against baselines
  9. Deduct transaction costs
  10. Split into IS/OOS
  11. Run robustness tests
  12. Generate decision + report
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

# Add src to path
SRC_DIR = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_DIR))

from data_loader import load_data, load_benchmark, load_ccl_series
from data_validator import validate_all
from currency_adjustment import dollarize_dataframe
from feature_engine import compute_all_features
from event_detector import load_event_config, detect_events_all_assets
from forward_returns import calculate_forward_returns, compute_overall_metrics
from regime_detector import compute_all_regimes
from baseline_comparator import compute_all_baselines
from cost_model import load_costs, summarize_costs
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
    """List all experiments that have been run."""
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
    """Show summary for a completed experiment."""
    results_dir = resolve_results_dir(experiment_id)
    summary = results_dir / "summary.md"
    if summary.exists():
        print(summary.read_text())
    else:
        print(f"No results for experiment '{experiment_id}'.")


def run_experiment(event_path: str, universe_path: str, costs_path: str):
    """Run the full experiment pipeline."""
    logger.info(f"Loading event config: {event_path}")
    event_config = load_event_config(event_path)
    exp = event_config.get("experiment", {})
    event = event_config.get("event", {})
    val_config = event_config.get("validation", {})

    experiment_id = exp.get("id", "unnamed")
    logger.info(f"Experiment: {experiment_id}")

    logger.info(f"Loading universe: {universe_path}")
    universe_config = load_config(universe_path)
    tickers = (
        universe_config.get("argentina", {}).get("tickers", [])
        + universe_config.get("reference", {}).get("tickers", [])
    )
    benchmark_ticker = universe_config.get("benchmark", "^MERV")
    date_start = universe_config.get("date_start", "2015-01-01")
    date_end = universe_config.get("date_end", "2026-07-17")

    logger.info(f"Universe: {tickers}")
    logger.info(f"Period: {date_start} → {date_end}")

    # --- STEP 1: Load data ---
    logger.info("=" * 60)
    logger.info("STEP 1: Loading data")
    data = load_data(tickers, date_start, date_end)
    if not data:
        logger.error("No data loaded. Aborting.")
        sys.exit(1)

    bench = load_benchmark(benchmark_ticker, date_start, date_end)

    # --- STEP 2: Validate data ---
    logger.info("=" * 60)
    logger.info("STEP 2: Validating data quality")
    try:
        reports = validate_all(data, date_start, date_end)
    except ValueError as e:
        logger.error(f"Data validation failed: {e}")
        sys.exit(1)

    # --- STEP 3: Currency adjustment ---
    logger.info("=" * 60)
    logger.info("STEP 3: Adjusting for currency")
    ccl = load_ccl_series(date_start, date_end)
    data_usd = dollarize_dataframe(data, ccl)

    # --- STEP 4: Compute features ---
    logger.info("=" * 60)
    logger.info("STEP 4: Computing features")
    for ticker in list(data_usd.keys()):
        data_usd[ticker] = compute_all_features(data_usd[ticker])
        logger.info(f"  {ticker}: {len(data_usd[ticker])} rows with features")

    # --- STEP 5: Market regimes ---
    logger.info("=" * 60)
    logger.info("STEP 5: Classifying market regimes")
    if bench is not None:
        bench_feat = compute_all_features(bench)
        for ticker in data_usd:
            data_usd[ticker] = compute_all_regimes(
                data_usd[ticker], bench_feat["close"]
            )
        logger.info("  Regimes computed from benchmark")

    # --- STEP 6: Detect events ---
    logger.info("=" * 60)
    logger.info("STEP 6: Detecting events")
    conditions = event.get("conditions", {})
    cooldown = event.get("cooldown_days", 10)
    horizons = event.get("forward_horizons", [5])
    events = detect_events_all_assets(data_usd, conditions, cooldown)

    # Flatten events for total count
    all_event_dates = []
    for ticker, dates in events.items():
        for d in dates:
            all_event_dates.append((ticker, d))
    n_total = len(all_event_dates)
    logger.info(f"  Total independent events: {n_total}")

    if n_total == 0:
        logger.warning("No events detected. Aborting.")
        sys.exit(0)

    # --- STEP 7: Forward returns ---
    logger.info("=" * 60)
    logger.info("STEP 7: Calculating forward returns + MFE/MAE")
    raw_returns = {}
    for ticker, dates in events.items():
        raw_returns[ticker] = calculate_forward_returns(
            data_usd[ticker], dates, horizons
        )

    # Combine all events for metrics
    combined_returns = {}
    for h in horizons:
        all_fr = []
        for ticker in raw_returns:
            if h in raw_returns[ticker] and not raw_returns[ticker][h].empty:
                all_fr.append(raw_returns[ticker][h])
        combined_returns[h] = pd.concat(all_fr) if all_fr else pd.DataFrame()

    metrics = compute_overall_metrics(combined_returns)

    # --- STEP 8: Baselines ---
    logger.info("=" * 60)
    logger.info("STEP 8: Computing baselines")
    flat_event_dates = [d for _, d in all_event_dates]

    # Build per-ticker baselines
    all_baselines = {}
    for ticker, dates in events.items():
        if ticker in data_usd and len(dates) > 0:
            ticker_bl = compute_all_baselines(
                data_usd[ticker], dates, horizons,
                bench_feat if bench is not None else None
            )
            all_baselines[ticker] = ticker_bl

    # Aggregate baselines across tickers
    baselines = {}
    for h in horizons:
        unconditional_vals = []
        regime_vals = []
        benchmark_vals = []
        for ticker_bl in all_baselines.values():
            if h in ticker_bl:
                unconditional_vals.append(ticker_bl[h]["unconditional"])
                regime_vals.append(ticker_bl[h]["regime_conditioned"])
                benchmark_vals.append(ticker_bl[h]["benchmark"])
        baselines[h] = {
            "unconditional": float(np.mean(unconditional_vals)) if unconditional_vals else 0.0,
            "regime_conditioned": float(np.mean(regime_vals)) if regime_vals else 0.0,
            "benchmark": float(np.mean(benchmark_vals)) if benchmark_vals else 0.0,
        }

    # --- STEP 9: Costs ---
    logger.info("=" * 60)
    logger.info("STEP 9: Applying transaction costs")
    cost_config = load_costs(costs_path)
    cost_summary = summarize_costs(cost_config)

    # --- STEP 10: Temporal split ---
    logger.info("=" * 60)
    logger.info("STEP 10: Temporal split")
    splitter = TemporalSplit(
        discovery_pct=val_config.get("discovery_pct", 60) / 100,
        validation_pct=val_config.get("validation_pct", 20) / 100,
        holdout_pct=val_config.get("holdout_pct", 20) / 100,
    )
    splitter.fit(data_usd, all_event_dates)

    # --- STEP 11: Robustness ---
    logger.info("=" * 60)
    logger.info("STEP 11: Running robustness tests")
    robustness_results = run_all_robustness(
        data_usd, conditions, cooldown, horizons
    )
    # Add bootstrap if not present
    for h in horizons:
        if f"bootstrap_{h}d" not in robustness_results:
            from robustness import bootstrap_ci
            if h in combined_returns and not combined_returns[h].empty:
                rets = combined_returns[h]["forward_return"].values
                robustness_results[f"bootstrap_{h}d"] = bootstrap_ci(rets)
            else:
                robustness_results[f"bootstrap_{h}d"] = {
                    "mean": 0, "ci_lower": 0, "ci_upper": 0, "std_error": 0
                }

    # --- STEP 12: Decision ---
    logger.info("=" * 60)
    logger.info("STEP 12: Making decision")
    decision, reason = make_decision(metrics, robustness_results, cost_summary, n_total)
    logger.info(f"Decision: {decision}")
    logger.info(f"Reason: {reason}")

    # --- STEP 13: Generate report ---
    logger.info("=" * 60)
    logger.info("STEP 13: Generating report")
    output_dir = resolve_results_dir(experiment_id)
    report_data = {
        "config": event_config,
        "event_data": {
            "raw_returns": {str(k): v for k, v in combined_returns.items()},
        },
        "metrics": metrics,
        "baselines": baselines,
        "cost_summary": cost_summary,
        "robustness_results": robustness_results,
        "decision": decision,
        "decision_reason": reason,
        "output_dir": output_dir,
    }
    summary_path = generate_summary(**report_data)

    # Summary to console
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
                        help="Path to universe YAML (default: config/universe.yaml)")
    parser.add_argument("--costs", default="config/costs.yaml",
                        help="Path to costs YAML (default: config/costs.yaml)")
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
