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
from currency_adjustment import dollarize_dataframe, dollarize_single_benchmark
from feature_engine import compute_all_features
from event_detector import (
    load_event_config, detect_events_all_assets,
    validate_event_conditions,
)
from forward_returns import (
    calculate_forward_returns, compute_overall_metrics,
    build_canonical_table, enrich_canonical_with_baselines,
)
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

    # ── Validate event conditions against schema (Audit 4) ──
    conditions = event.get("conditions", [])
    if isinstance(conditions, list):
        errors = validate_event_conditions(conditions)
        if errors:
            for err in errors:
                logger.error(f"Config error: {err}")
            sys.exit(1)
        logger.info("Config validation: ✅ conditions within known ranges")

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

    # ── STEP 5: Market regimes (Audit 4: benchmark in USD) ──
    logger.info("=" * 60)
    logger.info("STEP 5: Classifying market regimes (benchmark in USD)")
    if bench is not None:
        # Dollarize benchmark if Argentine
        if is_argentine(benchmark_ticker):
            if ccl is not None:
                bench_usd = dollarize_single_benchmark(bench, ccl)
            else:
                logger.warning("CCL not available for benchmark — using nominal ARS")
                bench_usd = bench.copy()
        else:
            bench_usd = bench.copy()
            bench_usd["close_usd"] = bench_usd["close"]

        bench_feat = compute_all_features(
            bench_usd,
            price_col="close_usd",
            high_col="high_usd" if "high_usd" in bench_usd.columns else "high",
            low_col="low_usd" if "low_usd" in bench_usd.columns else "low",
        )
        for ticker in data_usd:
            data_usd[ticker] = compute_all_regimes(
                data_usd[ticker], bench_feat["close_usd"]
            )
        # Also attach regimes to the benchmark df
        data_usd[benchmark_ticker] = compute_all_regimes(
            bench_usd, bench_feat["close_usd"]
        )
        logger.info("  Regimes computed from USD benchmark")

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

    # ── Read primary horizon (Audit 4) ──
    primary_horizon = event_config.get("research", {}).get("primary_horizon", horizons[0])
    logger.info(f"Primary horizon: {primary_horizon}d")

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

    # ── STEP 8: Temporal split + canonical table (Audit 4) ──
    logger.info("=" * 60)
    logger.info("STEP 8: Temporal split + canonical table")
    splitter = TemporalSplit(
        discovery_pct=val_config.get("discovery_pct", 60) / 100,
        validation_pct=val_config.get("validation_pct", 20) / 100,
        holdout_pct=val_config.get("holdout_pct", 20) / 100,
    )
    flat_dates = [d for _, d in all_event_dates]
    splitter.fit(data_usd, flat_dates)

    # Build canonical trade table (enriched with regimes and split)
    canonical = build_canonical_table(raw_returns, data_usd, splitter, horizons)
    n_total = len(canonical)
    n_purged = len(canonical[canonical["temporal_split"] == "boundary_crossing"])
    if n_purged:
        logger.info(f"  Purged {n_purged} boundary-crossing trades from canonical table")

    # Separate by split for formal metrics
    canonical_valid = canonical[canonical["temporal_split"] != "boundary_crossing"].copy()
    canonical_by_split = {
        split: canonical_valid[canonical_valid["temporal_split"] == split].copy()
        for split in ["discovery", "validation", "holdout"]
    }
    # Also include full sample (all valid)
    canonical_by_split["full_sample"] = canonical_valid.copy()

    # ── STEP 9: Baselines ──
    logger.info("=" * 60)
    logger.info("STEP 9: Computing baselines")
    all_baselines = {}
    for ticker, dates in events.items():
        if ticker in data_usd and len(dates) > 0:
            ticker_bl = compute_all_baselines(
                data_usd[ticker], dates, horizons,
                bench_feat if bench is not None else None,
                cooldown_sessions=cooldown,
            )
            all_baselines[ticker] = ticker_bl

    # Enrich canonical table with baselines
    canonical = enrich_canonical_with_baselines(canonical, all_baselines)
    canonical_valid = canonical[canonical["temporal_split"] != "boundary_crossing"].copy()
    canonical_by_split = {
        split: canonical_valid[canonical_valid["temporal_split"] == split].copy()
        for split in ["discovery", "validation", "holdout", "full_sample"]
    }
    # full_sample = all valid
    canonical_by_split["full_sample"] = canonical_valid.copy()

    # Per-horizon aggregate baselines (for report)
    baselines = {}
    baseline_coverage_per_h = {}
    for h in horizons:
        unconditional_vals = []
        matched_vals = []
        trend_only_vals = []
        benchmark_vals = []
        weights = []
        cov_h = {"n_events": 0, "n_valid": 0, "n_low_confidence": 0, "n_insufficient": 0}
        for ticker, bl in all_baselines.items():
            if h in bl:
                n_events = len(events.get(ticker, []))
                unconditional_vals.append(bl[h]["unconditional"] * n_events)
                matched_vals.append(bl[h]["exact_matched_mean"] * n_events)
                trend_only_vals.append(bl[h]["trend_only_fallback_mean"] * n_events)
                benchmark_vals.append(bl[h]["benchmark"] * n_events)
                weights.append(n_events)
                # Per-horizon coverage (Audit 4: fix accumulation across horizons)
                cov = bl[h].get("baseline_coverage", {})
                for k in ("n_events", "n_valid", "n_low_confidence", "n_insufficient"):
                    cov_h[k] += cov.get(k, 0)
        total_w = sum(weights) or 1
        baselines[h] = {
            "unconditional": sum(unconditional_vals) / total_w if unconditional_vals else 0.0,
            "exact_matched_mean": sum(matched_vals) / total_w if matched_vals else 0.0,
            "trend_only_fallback_mean": sum(trend_only_vals) / total_w if trend_only_vals else 0.0,
            "benchmark": sum(benchmark_vals) / total_w if benchmark_vals else 0.0,
            "baseline_coverage": cov_h,
        }
        if cov_h["n_events"]:
            cov_h["valid_pct"] = round(cov_h["n_valid"] / cov_h["n_events"] * 100, 1)
            cov_h["valid_or_low_pct"] = round(
                (cov_h["n_valid"] + cov_h["n_low_confidence"]) / cov_h["n_events"] * 100, 1
            )
        logger.info(f"  h={h}d baseline coverage: {cov_h['n_valid']}/{cov_h['n_events']} VALID "
                    f"({cov_h.get('valid_pct', 0)}%)")

    # ── STEP 10: Costs summary ──
    logger.info("=" * 60)
    logger.info("STEP 10: Transaction costs")
    cost_summary = summarize_costs(cost_config)

    # ── STEP 11: Metrics (net_return_pct is formal, Audit 4) ──
    logger.info("=" * 60)
    logger.info("STEP 11: Computing metrics")

    def split_to_horizons(canonical_split: pd.DataFrame) -> dict:
        """Split canonical df into per-horizon dict for compute_overall_metrics."""
        result = {}
        for h in horizons:
            h_df = canonical_split[canonical_split["horizon"] == h]
            result[h] = h_df
        return result

    # Formal: net_return_pct
    net_metrics_full = compute_overall_metrics(
        split_to_horizons(canonical_valid), return_col="net_return_pct"
    )
    # Diagnostic: gross metrics
    gross_metrics_full = compute_overall_metrics(
        split_to_horizons(canonical_valid), return_col="forward_return"
    )

    # Per-split net metrics
    split_net_metrics = {}
    for split_name in ["discovery", "validation", "holdout"]:
        df_s = canonical_by_split.get(split_name, pd.DataFrame())
        split_net_metrics[split_name] = compute_overall_metrics(
            split_to_horizons(df_s), return_col="net_return_pct"
        )

    # ── STEP 12: Robustness (from canonical table, net returns) ──
    logger.info("=" * 60)
    logger.info("STEP 12: Running robustness tests")
    robustness_results = run_all_robustness(
        target_data, conditions, cooldown, horizons
    )
    from robustness import bootstrap_ci
    for h in horizons:
        key = f"bootstrap_{h}d"
        if key not in robustness_results:
            h_returns = canonical_valid.loc[
                canonical_valid["horizon"] == h, "net_return_pct"
            ].dropna().values
            if len(h_returns):
                robustness_results[key] = bootstrap_ci(h_returns)
            else:
                robustness_results[key] = {"mean": 0, "ci_lower": 0, "ci_upper": 0, "std_error": 0}

    # ── STEP 13: Decision (Audit 4: uses primary_horizon, net, holdout, edge) ──
    logger.info("=" * 60)
    logger.info("STEP 13: Making decision")

    # Build decision inputs from canonical table at primary horizon
    ph_key = f"horizon_{primary_horizon}d"

    # Extract primary horizon net metrics by split
    def ph_metrics(metrics_dict: dict) -> dict:
        return metrics_dict.get(ph_key, {})

    decision, reason = make_decision(
        metrics=net_metrics_full,
        robustness_results=robustness_results,
        cost_summary=cost_summary,
        n_total_events=len(canonical_valid),
        primary_horizon=primary_horizon,
        split_net_metrics=split_net_metrics,
        baselines=baselines,
    )
    logger.info(f"Decision: {decision}")
    logger.info(f"Reason: {reason}")

    # ── STEP 14: Generate report ──
    logger.info("=" * 60)
    logger.info("STEP 14: Generating report")
    output_dir = resolve_results_dir(experiment_id)

    # Store canonical table as CSV
    canonical.to_csv(output_dir / "canonical_trades.csv", index=False)

    report_data = {
        "config": event_config,
        "event_data": {"raw_returns": split_to_horizons(canonical_valid)},
        "metrics": net_metrics_full,
        "gross_metrics": gross_metrics_full,
        "baselines": baselines,
        "cost_summary": cost_summary,
        "robustness_results": robustness_results,
        "decision": decision,
        "decision_reason": reason,
        "output_dir": output_dir,
        "primary_horizon": primary_horizon,
        "split_net_metrics": split_net_metrics,
    }
    summary_path = generate_summary(**report_data)

    print("\n" + "=" * 60)
    print(f"  EXPERIMENT: {experiment_id}")
    print(f"  Primary horizon: {primary_horizon}d")
    print(f"  Events: {n_total} (purged: {n_purged})")
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
