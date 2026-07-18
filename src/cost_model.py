"""
cost_model.py — Statistical Edge Lab
Phase 3: Apply transaction costs and compute break-even cost.

Spec §13:
  Argentina: 0.7% commission + 0.08% market fees + 0.2% slippage per side
  Core metric: incremental_edge = event_return - baseline_return - costs
  break_even_cost = maximum cost that would eliminate the edge
"""

import logging
from typing import Optional

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_COSTS_PATH = Path(__file__).parent.parent / "config" / "costs.yaml"


def load_costs(path: Optional[str] = None) -> dict:
    """Load cost configuration from YAML."""
    if path is None:
        path = DEFAULT_COSTS_PATH
    with open(path) as f:
        return yaml.safe_load(f)


def roundtrip_cost_per_side(cost_config: dict, market: str = "argentina") -> float:
    """
    Total cost per side (commission + fees + slippage).

    Returns decimal (e.g., 0.0098 = 0.98%).
    """
    cfg = cost_config.get(market, cost_config.get("argentina", {}))
    return (
        cfg.get("commission_per_side", 0.007)
        + cfg.get("market_fees_per_side", 0.0008)
        + cfg.get("estimated_slippage_per_side", 0.002)
    )


def roundtrip_cost_total(cost_config: dict, market: str = "argentina") -> float:
    """
    Total round-trip cost (entry + exit).

    Returns decimal (e.g., 0.0196 = 1.96%).
    """
    per_side = roundtrip_cost_per_side(cost_config, market)
    # Minimum floor
    minimum = cost_config.get(market, {}).get("minimum_total_roundtrip", 0.015)
    total = per_side * 2
    return max(total, minimum)


def apply_costs_to_return(
    gross_return_pct: float,
    cost_config: dict,
    market: str = "argentina",
) -> float:
    """
    Deduct round-trip transaction costs from a return.

    Args:
        gross_return_pct: Return in percent (e.g., 2.5 for 2.5%)
        cost_config: Cost configuration dict
        market: Market identifier

    Returns:
        Net return in percent.
    """
    cost_pct = roundtrip_cost_total(cost_config, market) * 100  # convert to %
    return gross_return_pct - cost_pct


def apply_costs_to_df(
    returns_df: "pd.DataFrame",
    cost_config: dict,
    market: str = "argentina",
    return_col: str = "forward_return",
) -> "pd.DataFrame":
    """Apply costs to a DataFrame column (in-place)."""
    cost_pct = roundtrip_cost_total(cost_config, market) * 100
    result = returns_df.copy()
    result[f"{return_col}_net"] = result[return_col] - cost_pct
    return result


def break_even_cost(
    event_gross_return_pct: float,
    baseline_return_pct: float,
) -> float:
    """
    Maximum round-trip cost (as %) that would completely eliminate the edge.

    Spec §13: A candidate must have sufficient margin between gross edge
    and estimated execution cost.

    Returns percentage points (e.g., 1.5 = 1.5%).
    """
    edge = event_gross_return_pct - baseline_return_pct
    return max(0.0, edge)


def summarize_costs(cost_config: dict, market: str = "argentina") -> dict:
    """Human-readable summary of cost assumptions."""
    per_side = roundtrip_cost_per_side(cost_config, market)
    total = roundtrip_cost_total(cost_config, market)
    return {
        "market": market,
        "commission_per_side_pct": round(cost_config.get(market, {}).get("commission_per_side", 0) * 100, 2),
        "market_fees_per_side_pct": round(cost_config.get(market, {}).get("market_fees_per_side", 0) * 100, 2),
        "slippage_per_side_pct": round(cost_config.get(market, {}).get("estimated_slippage_per_side", 0) * 100, 2),
        "total_per_side_pct": round(per_side * 100, 2),
        "total_roundtrip_pct": round(total * 100, 2),
    }
