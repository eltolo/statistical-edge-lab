"""
report_generator.py — Statistical Edge Lab
Phase 5: Generate standardized Markdown reports for experiments.

Spec §17: Output must include:
  results/<experiment_id>/
    summary.md, metrics.csv, events.csv, robustness.csv, metadata.json, charts/
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def _fmt(val, decimals=4):
    """Format a number for display."""
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _pct(val, decimals=2):
    """Format as percentage."""
    if val is None:
        return "—"
    return f"{val:.{decimals}f}%"


def generate_summary(
    config: dict,
    event_data: dict,
    metrics: dict,
    baselines: dict,
    cost_summary: dict,
    robustness_results: dict,
    decision: str,
    decision_reason: str,
    output_dir: Path,
):
    """
    Generate complete experiment report.

    Writes summary.md, metrics.csv, events.csv, robustness.csv, metadata.json.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    exp_id = config.get("experiment", {}).get("id", "unknown")

    # --- events.csv ---
    all_events = []
    for h, fr_df in event_data.get("raw_returns", {}).items():
        if isinstance(fr_df, pd.DataFrame) and not fr_df.empty:
            df = fr_df.copy()
            df["horizon"] = h
            all_events.append(df)
    if all_events:
        pd.concat(all_events).to_csv(output_dir / "events.csv", index=False)

    # --- metrics.json ---
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str, cls=_Encoder)

    # --- robustness.csv ---
    _write_robustness_csv(robustness_results, output_dir / "robustness.csv")

    # --- metadata.json ---
    metadata = {
        "experiment_id": exp_id,
        "generated_at": datetime.now().isoformat(),
        "decision": decision,
        "decision_reason": decision_reason,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # --- summary.md ---
    summary = _build_summary_md(
        config, metrics, baselines, cost_summary,
        robustness_results, decision, decision_reason
    )
    with open(output_dir / "summary.md", "w") as f:
        f.write(summary)

    logger.info(f"Report written to {output_dir / 'summary.md'}")
    return output_dir / "summary.md"


def _write_robustness_csv(robustness: dict, path: Path):
    """Write robustness results as CSV. Does not mutate input dicts."""
    rows = []
    for key, value in robustness.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    row = dict(item)
                    row["test"] = key
                    rows.append(row)
        elif isinstance(value, dict):
            # For dict values (e.g. profit_concentration per horizon),
            # flatten each sub-item into a separate row
            for sub_key, sub_val in value.items():
                if isinstance(sub_val, dict):
                    row = dict(sub_val)
                    row["test"] = f"{key}_{sub_key}"
                    rows.append(row)
                else:
                    rows.append({"test": f"{key}_{sub_key}", "value": sub_val})
        else:
            rows.append({"test": key, "value": value})
    if rows:
        pd.DataFrame(rows).to_csv(path, index=False)


def _build_summary_md(
    config, metrics, baselines, cost_summary,
    robustness_results, decision, decision_reason,
) -> str:
    """Build the summary.md Markdown content."""
    exp = config.get("experiment", {})
    ev = config.get("event", {})

    lines = [
        f"# Experiment: {exp.get('id', 'unknown')}",
        "",
        f"**Hypothesis:** {exp.get('hypothesis', 'N/A')}",
        f"**Family:** {exp.get('family', 'N/A')}",
        f"**Description:** {exp.get('description', 'N/A')}",
        "",
        "---",
        "## Configuration",
        "",
        f"- **Forward horizons:** {ev.get('forward_horizons', [])}",
        f"- **Cooldown days:** {ev.get('cooldown_days', 10)}",
        f"- **Conditions:** {json.dumps(ev.get('conditions', {}), indent=2)}",
        "",
        "---",
        "## Results by Horizon",
        "",
    ]

    # Results table
    lines.append("| Horizon | N Events | Mean % | Median % | Win Rate | PF | Avg MFE % | Avg MAE % |")
    lines.append("|---------|----------|--------|----------|----------|-----|-----------|-----------|")

    for h_key in sorted([k for k in metrics.keys() if k.startswith("horizon_")]):
        h_data = metrics[h_key]
        horizon = h_key.replace("horizon_", "").replace("d", "")
        lines.append(
            f"| {horizon}d | {h_data.get('n_events', 0)} "
            f"| {_pct(h_data.get('mean_return', 0))} "
            f"| {_pct(h_data.get('median_return', 0))} "
            f"| {_pct(h_data.get('win_rate', 0) * 100)} "
            f"| {_fmt(h_data.get('profit_factor', 0), 2)} "
            f"| {_pct(h_data.get('avg_mfe', 0))} "
            f"| {_pct(h_data.get('avg_mae', 0))} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("## Baseline Comparison")
    lines.append("")

    # Baseline table
    lines.append("| Horizon | Event Mean % | Unconditional % | Exact Match % | Trend-Only % | Benchmark % | Incremental Edge % |")
    lines.append("|---------|-------------|-----------------|---------------|--------------|-------------|---------------------|")

    for h_key in sorted([k for k in metrics.keys() if k.startswith("horizon_")]):
        h_data = metrics[h_key]
        horizon = h_key.replace("horizon_", "").replace("d", "")
        ev_mean = h_data.get("mean_return", 0)
        bl = baselines.get(int(horizon) if horizon.isdigit() else 0, {})
        inc = ev_mean - bl.get("unconditional", 0)
        lines.append(
            f"| {horizon}d | {_pct(ev_mean)} "
            f"| {_pct(bl.get('unconditional', 0))} "
            f"| {_pct(bl.get('exact_matched_mean', 0))} "
            f"| {_pct(bl.get('trend_only_fallback_mean', 0))} "
            f"| {_pct(bl.get('benchmark', 0))} "
            f"| {_pct(inc)} |"
        )

    # Baseline coverage
    if baselines:
        first_h = list(baselines.keys())[0]
        cov = baselines[first_h].get("baseline_coverage", {})
        n_total = cov.get("n_events", 0)
        if n_total:
            n_valid = cov.get("n_valid", 0)
            n_low = cov.get("n_low_confidence", 0)
            n_insuf = cov.get("n_insufficient", 0)
            valid_pct = n_valid / n_total * 100
            valid_or_low_pct = (n_valid + n_low) / n_total * 100
            lines.append("")
            lines.append("### Baseline Coverage (trend+vol matched)")
            lines.append("")
            lines.append(f"- **VALID** (n≥20): {n_valid}/{n_total} ({_pct(valid_pct)})")
            lines.append(f"- **LOW CONFIDENCE** (5≤n<20): {n_low}")
            lines.append(f"- **INSUFFICIENT** (n<5): {n_insuf}")
            lines.append(f"- **Valid or Low Confidence:** {_pct(valid_or_low_pct)}")

    # Costs
    lines.append("")
    lines.append("---")
    lines.append("## Transaction Costs")
    lines.append("")
    if cost_summary:
        lines.append(f"- **Market:** {cost_summary.get('market', 'argentina')}")
        lines.append(f"- **Commission per side:** {cost_summary.get('commission_per_side_pct', 0)}%")
        lines.append(f"- **Fees per side:** {cost_summary.get('market_fees_per_side_pct', 0)}%")
        lines.append(f"- **Slippage per side:** {cost_summary.get('slippage_per_side_pct', 0)}%")
        lines.append(f"- **Total per side:** {cost_summary.get('total_per_side_pct', 0)}%")
        lines.append(f"- **Total round-trip:** {cost_summary.get('total_roundtrip_pct', 0)}%")
        lines.append("")

    # Net of costs table
    lines.append("| Horizon | Gross Mean % | Cost % | Net Mean % |")
    lines.append("|---------|-------------|--------|------------|")
    for h_key in sorted([k for k in metrics.keys() if k.startswith("horizon_")]):
        h_data = metrics[h_key]
        horizon = h_key.replace("horizon_", "").replace("d", "")
        gross = h_data.get("mean_return", 0)
        cost_pct = cost_summary.get("total_roundtrip_pct", 1.96)
        net = gross - cost_pct
        lines.append(f"| {horizon}d | {_pct(gross)} | {_pct(cost_pct)} | {_pct(net)} |")

    # Bootstrap
    lines.append("")
    lines.append("---")
    lines.append("## Bootstrap Confidence Intervals")
    lines.append("")
    lines.append("| Horizon | Mean % | CI 95% Lower | CI 95% Upper | Std Error |")
    lines.append("|---------|--------|--------------|--------------|-----------|")
    for h_key in sorted([k for k in robustness_results.keys() if k.startswith("bootstrap_")]):
        boot = robustness_results[h_key]
        horizon = h_key.replace("bootstrap_h", "").replace("d", "")
        lines.append(
            f"| {horizon}d | {_pct(boot.get('mean', 0))} "
            f"| {_pct(boot.get('ci_lower', 0))} "
            f"| {_pct(boot.get('ci_upper', 0))} "
            f"| {_pct(boot.get('std_error', 0))} |"
        )

    # Profit concentration (per-horizon, Q6)
    if "profit_concentration" in robustness_results:
        pc_all = robustness_results["profit_concentration"]
        lines.append("")
        lines.append("---")
        lines.append("## Profit Concentration (by Horizon)")
        lines.append("")
        lines.append("| Horizon | Best Trade % | Best 3 Trades % | Best Asset | Best Asset % | N Trades |")
        lines.append("|---------|-------------|----------------|------------|--------------|----------|")
        for h in sorted(pc_all.keys()):
            p = pc_all[h]
            lines.append(
                f"| {h}d | {_pct(p.get('best_trade_pct', 0))} "
                f"| {_pct(p.get('best_3_pct', 0))} "
                f"| {p.get('best_asset', '—')} "
                f"| {_pct(p.get('best_asset_pct', 0))} "
                f"| {p.get('n_trades', 0)} |"
            )

    # Decision
    lines.append("")
    lines.append("---")
    lines.append("## Decision")
    lines.append("")
    decision_icon = {"REJECTED": "❌", "RESEARCH": "🔬", "CANDIDATE": "✅", "PAPER_READY": "🏆"}
    icon = decision_icon.get(decision, "❓")
    lines.append(f"### {icon} **{decision}**")
    lines.append("")
    lines.append(f"**Reason:** {decision_reason}")

    lines.append("")
    lines.append("---")
    lines.append(f"*Generated automatically by Statistical Edge Lab on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    return "\n".join(lines)


def make_decision(
    metrics: dict,
    robustness_results: dict,
    cost_summary: dict,
    n_total_events: int,
) -> tuple[str, str]:
    """
    Spec §16: Assign decision based on evidence.

    Returns (decision, reason).
    """
    reasons = []

    # Check minimum events
    if n_total_events < 40:
        reasons.append(f"Fewer than 40 independent events ({n_total_events})")
        return "REJECTED", "; ".join(reasons)

    # Check net median return
    best_horizon = None
    best_net = -999
    for h_key, h_data in metrics.items():
        if h_key.startswith("horizon_"):
            gross = h_data.get("mean_return", 0)
            cost_pct = cost_summary.get("total_roundtrip_pct", 1.96)
            net = gross - cost_pct
            if net > best_net:
                best_net = net
                best_horizon = h_key

    if best_net <= 0:
        reasons.append(f"Best net return <= 0 ({best_net:.2f}%)")
        return "REJECTED", "; ".join(reasons)

    # Check incremental edge
    # (already computed in baseline comparison)

    # Check bootstrap CI does not cross zero
    ci_crosses_zero = False
    for h_key, boot in robustness_results.items():
        if h_key.startswith("bootstrap_"):
            if boot.get("ci_lower", 0) < 0 and boot.get("ci_upper", 0) > 0:
                ci_crosses_zero = True
                break

    # Check profit concentration (per-horizon)
    pc_all = robustness_results.get("profit_concentration", {})
    # Use best_horizon for concentration check
    best_horizon_num = int(best_horizon.replace("horizon_", "").replace("d", "")) if best_horizon else 5
    pc = pc_all.get(best_horizon_num, {})
    best_trade_pct = pc.get("best_trade_pct", 100)
    if best_trade_pct > 20:
        reasons.append(f"Best trade explains {best_trade_pct:.1f}% of profit (>20%)")
        if n_total_events < 60:
            return "RESEARCH", "; ".join(reasons)

    # Check break-even cost
    cost_pct = cost_summary.get("total_roundtrip_pct", 1.96)
    for h_key in [k for k in metrics.keys() if k.startswith("horizon_")]:
        gross = metrics[h_key].get("mean_return", 0)
        if gross > cost_pct * 1.5:
            break
    else:
        reasons.append("Break-even cost insufficient margin over transaction costs")

    # CANDIDATE requirements
    if (n_total_events >= 60
        and best_net > 0
        and best_trade_pct <= 20
        and not ci_crosses_zero):
        if reasons:
            return "CANDIDATE", "; ".join(reasons) + "; Meets minimum CANDIDATE requirements"
        return "CANDIDATE", "Meets all CANDIDATE requirements: sufficient events, positive net return, diversified, CI excludes zero."

    if best_net > 0:
        return "RESEARCH", "Positive but insufficient evidence: " + "; ".join(reasons) if reasons else "Positive signal, needs more data."

    return "REJECTED", "; ".join(reasons) if reasons else "No evidence of edge."


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, pd.Timestamp):
            return str(obj)
        return super().default(obj)
