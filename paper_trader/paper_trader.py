#!/usr/bin/env python3
"""
Extreme Decline Paper Trader — Tom's Plan v2.0

Dual-signal paper trader:
  1. EXP-005: z-score < -2.0, not BEAR, 10d horizon
  2. EXP-503: RSI(14) < 20, not BEAR, 10d horizon

Executes on 11 US large-cap stocks via IOL USA (0.847% RT).
Monitors daily, enters at next open, exits after 10 trading days.
Tracks P&L via trade_registry.db + local state.

Usage:
    python paper_trader.py                    # normal run (scan + manage)
    python paper_trader.py --scan-only        # only scan for new signals
    python paper_trader.py --close-only       # only close expired positions
    python paper_trader.py --status           # show current positions
    python paper_trader.py --daily            # cron: scan at open, close at EOD
"""

import sys, os, json, logging, argparse, yaml
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

import pandas as pd
import numpy as np

# ── Paths ──
STRATEGY_DIR = Path(__file__).parent
CONFIG_PATH = STRATEGY_DIR / "config.yaml"
STATE_PATH = STRATEGY_DIR / "state.json"

# Add lab src for feature engine, etc.
LAB_SRC = Path.home() / "shared" / "proyectos" / "strategies" / "1-laboratorio" / "src"
sys.path.insert(0, str(LAB_SRC))

# Add shared lib for trade registry
SHARED_LIB = Path.home() / "shared" / "lib"
sys.path.insert(0, str(SHARED_LIB))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("extreme_decline_paper")


# ── Load data from DuckDB ──

def load_ticker_data(ticker: str, lookback_days: int = 300) -> pd.DataFrame:
    """Load recent OHLCV from DuckDB + yfinance fallback for recent days."""
    import duckdb
    db_path = Path.home() / "shared" / "data" / "db" / "duckdb" / "cedears.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)

    df = con.execute(
        "SELECT Date as date, Open as open, High as high, Low as low, "
        "Close as close, Adj_Close as adj_close, Volume as volume "
        "FROM historico_cedears WHERE Ticker = ? "
        "ORDER BY Date DESC LIMIT ?",
        [ticker, lookback_days],
    ).fetchdf()
    con.close()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Fallback: fill recent days from yfinance if DB is stale
    last_db_date = df.index.max().date()
    today = date.today()
    if last_db_date < today - timedelta(days=2):
        logger.info(f"DB stale for {ticker} (last={last_db_date}), fetching from Yahoo...")
        try:
            import yfinance as yf
            yf_t = yf.Ticker(ticker)
            yf_df = yf_t.history(start=str(last_db_date + timedelta(days=1)), end=str(today + timedelta(days=1)))
            if not yf_df.empty:
                yf_df = yf_df.rename(columns={
                    "Open": "open", "High": "high", "Low": "low",
                    "Close": "close", "Volume": "volume",
                })
                yf_df.index = pd.to_datetime(yf_df.index)
                if yf_df.index.tz is not None:
                    yf_df.index = yf_df.index.tz_convert(None)
                yf_df.index = yf_df.index.normalize()
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in yf_df.columns:
                        yf_df[col] = pd.to_numeric(yf_df[col], errors="coerce")
                if "adj_close" not in yf_df.columns or yf_df["adj_close"].isna().all():
                    yf_df["adj_close"] = yf_df["close"]
                # Merge: keep DB for history, yfinance for recent
                df = pd.concat([df, yf_df])
                df = df[~df.index.duplicated(keep="last")]
                df = df.sort_index()
                logger.info(f"  Added {len(yf_df)} days from yfinance, range now {df.index.min().date()} → {df.index.max().date()}")
        except Exception as e:
            logger.warning(f"yfinance fallback failed for {ticker}: {e}")

    # USD alias
    for col in ["open", "high", "low", "close"]:
        df[f"{col}_usd"] = df[col]
    return df


def load_benchmark(lookback_days: int = 300) -> pd.DataFrame:
    """Load SPY for regime detection."""
    import duckdb
    db_path = Path.home() / "shared" / "data" / "db" / "duckdb" / "historico.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)

    df = con.execute(
        "SELECT date, open, high, low, close, volume "
        "FROM stock_prices WHERE ticker = 'SPY' "
        "ORDER BY date DESC LIMIT ?",
        [lookback_days],
    ).fetchdf()
    con.close()

    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df["adj_close"] = df["close"]
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        df[f"{col}_usd"] = df[col]
    return df


# ── Signal detection ──

def detect_signals(tickers: list[str], signal_configs: list[dict]) -> list[dict]:
    """
    Scan all tickers for all signal families.
    Returns list of signals: {ticker, date, close, signal_type, ...}
    """
    from feature_engine import compute_all_features
    from regime_detector import compute_all_regimes
    from event_detector import detect_events_all_assets

    bench = load_benchmark()
    if bench.empty:
        logger.error("Cannot load SPY benchmark")
        return []

    bench_feat = compute_all_features(
        bench, price_col="close_usd", high_col="high_usd", low_col="low_usd"
    )

    all_signals = []
    for sig_cfg in signal_configs:
        sig_name = sig_cfg["name"]
        conditions = sig_cfg["conditions"]

        for ticker in tickers:
            # Skip if already have an open position for this ticker (check via caller)
            df = load_ticker_data(ticker)
            if df.empty:
                continue

            feat = compute_all_features(
                df, price_col="close_usd", high_col="high_usd", low_col="low_usd"
            )
            feat = compute_all_regimes(feat, bench_feat["close_usd"])

            events = detect_events_all_assets({ticker: feat}, conditions, cooldown_sessions=20)
            dates = events.get(ticker, [])

            # Only keep the most recent signal (last 7 days)
            today = date.today()
            recent = [d for d in dates if d.date() >= today - timedelta(days=7)]
            for d in recent:
                row = feat.loc[d]
                all_signals.append({
                    "ticker": ticker,
                    "signal_type": sig_name,
                    "signal_date": str(d.date()),
                    "close_usd": float(row.get("close_usd", 0)),
                    "trend_regime": str(row.get("trend_regime", "NEUTRAL")),
                })

    return all_signals


# ── State management ──

def load_state() -> dict:
    """Load paper trading state from JSON."""
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"positions": [], "history": [], "last_scan": None}


def save_state(state: dict):
    """Save paper trading state to JSON."""
    state["last_scan"] = datetime.now().isoformat()
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def is_position_open(state: dict, ticker: str) -> bool:
    """Check if we already have an open position for this ticker."""
    for pos in state["positions"]:
        if pos["ticker"] == ticker and pos["status"] == "open":
            return True
    return False


# ── Trade registry integration ──

def register_entry(ticker: str, quantity: int, price: float, signal_date: str) -> Optional[int]:
    """Register a paper trade entry in trade_registry.db."""
    try:
        from trade_registry import TradeRegistry
        reg = TradeRegistry()
        trade_id = reg.entry(
            strategy="extreme_decline_us",
            ticker=ticker,
            side="BUY",
            quantity=quantity,
            price=price,
            broker="IOL_USA",
            instrument_type="ACCION",
            currency="USD",
            notes=f"zscore_signal={signal_date}",
        )
        return trade_id
    except Exception as e:
        logger.error(f"Trade registry entry failed: {e}")
        return None


def register_exit(trade_id: int, exit_price: float, pnl: float, pnl_pct: float):
    """Register a paper trade exit."""
    try:
        from trade_registry import TradeRegistry
        reg = TradeRegistry()
        reg.close_trade(
            trade_id=trade_id,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            notes=f"horizon_10d",
        )
    except Exception as e:
        logger.error(f"Trade registry exit failed: {e}")


# ── Main operations ──

def scan_and_enter(state: dict, config: dict):
    """Scan for new signals and enter positions."""
    tickers = config["tickers"]
    signal_configs = config["signals"]
    fixed_size = config["position"]["fixed_size_usd"]
    max_concurrent = config["position"]["max_concurrent"]

    open_count = sum(1 for p in state["positions"] if p["status"] == "open")
    if open_count >= max_concurrent:
        logger.info(f"Max positions reached ({open_count}/{max_concurrent})")
        return

    signals = detect_signals(tickers, signal_configs)
    logger.info(f"Scan: {len(signals)} signals found, {open_count} positions open")

    for sig in signals:
        ticker = sig["ticker"]
        if is_position_open(state, ticker):
            continue
        if open_count >= max_concurrent:
            break

        price = sig["close_usd"]
        qty = int(fixed_size / price) if price > 0 else 1
        entry_price = price

        trade_id = register_entry(ticker, qty, entry_price, sig["signal_date"])

        pos = {
            "ticker": ticker,
            "trade_id": trade_id,
            "entry_date": str(date.today()),
            "exit_date": None,
            "entry_price": entry_price,
            "quantity": qty,
            "position_usd": round(qty * entry_price, 2),
            "status": "open",
            "signal_type": sig["signal_type"],
            "signal_date": sig["signal_date"],
        }
        state["positions"].append(pos)
        open_count += 1

        logger.info(f"📈 ENTRY [{sig['signal_type']}] {ticker}: {qty} shares @ ${entry_price:.2f} = ${pos['position_usd']:.0f} "
                     f"[trade_id={trade_id}]")


def close_expired(state: dict, config: dict):
    """Close positions that have reached the holding horizon."""
    horizon = config["execution"]["holding_sessions"]
    commission_pct = config["costs"]["commission_per_side_pct"] / 100
    rt_pct = config["costs"]["roundtrip_pct"] / 100

    today = date.today()

    for pos in state["positions"]:
        if pos["status"] != "open":
            continue

        entry_date = date.fromisoformat(pos["entry_date"])
        days_held = (today - entry_date).days

        if days_held < horizon:
            continue  # Not yet expired

        # Get current price
        ticker = pos["ticker"]
        df = load_ticker_data(ticker, lookback_days=5)
        if df.empty:
            logger.warning(f"Cannot get current price for {ticker}")
            continue

        exit_price = float(df["close"].iloc[-1])
        entry_price = pos["entry_price"]
        qty = pos["quantity"]

        gross_return = (exit_price / entry_price - 1)
        net_return = gross_return - rt_pct  # subtract roundtrip costs
        pnl = qty * entry_price * net_return
        pnl_pct = net_return * 100

        # Register exit
        if pos["trade_id"]:
            register_exit(pos["trade_id"], exit_price, round(pnl, 2), round(pnl_pct, 2))

        pos["status"] = "closed"
        pos["exit_date"] = str(today)
        pos["exit_price"] = exit_price
        pos["pnl_usd"] = round(pnl, 2)
        pos["pnl_pct"] = round(pnl_pct, 2)

        emoji = "🟢" if pnl > 0 else "🔴"
        logger.info(f"{emoji} CLOSE {ticker}: {qty} shares @ ${exit_price:.2f} "
                     f"(entry ${entry_price:.2f}) | PnL: ${pnl:.2f} ({pnl_pct:+.2f}%)")


def show_status(state: dict, config: dict):
    """Display current paper trading status."""
    tickers = config["tickers"]
    rt_pct = config["costs"]["roundtrip_pct"]
    horizon = config["execution"]["holding_sessions"]

    open_positions = [p for p in state["positions"] if p["status"] == "open"]
    closed_positions = [p for p in state["positions"] if p["status"] == "closed"]

    print(f"\n{'='*60}")
    print(f"  EXTREME DECLINE PAPER TRADER — Status")
    print(f"  Tickers: {len(tickers)} | Horizon: {horizon}d | RT cost: {rt_pct}%")
    print(f"  Open positions: {len(open_positions)} | Closed: {len(closed_positions)}")
    print(f"{'='*60}")

    if open_positions:
        total_exposure = sum(p["position_usd"] for p in open_positions)
        print(f"\n  Open positions (${total_exposure:.0f} total):")
        for pos in sorted(open_positions, key=lambda p: p["entry_date"]):
            days_held = (date.today() - date.fromisoformat(pos["entry_date"])).days
            bar = "▓" * min(days_held, horizon) + "░" * max(0, horizon - days_held)
            sig = pos.get("signal_type", "?")[:12]
            print(f"    {pos['ticker']:>6s} [{sig}]: ${pos['position_usd']:.0f} | "
                  f"Day {days_held}/{horizon} {bar} | id={pos['trade_id']}")
    else:
        print("\n  No open positions.")

    if closed_positions:
        total_pnl = sum(p.get("pnl_usd", 0) for p in closed_positions)
        wins = sum(1 for p in closed_positions if p.get("pnl_usd", 0) > 0)
        print(f"\n  Closed trades ({len(closed_positions)}):")
        print(f"    Total PnL: ${total_pnl:+.2f} | Win rate: {wins}/{len(closed_positions)}")
        for pos in sorted(closed_positions, key=lambda p: p.get("exit_date", ""), reverse=True)[:5]:
            pnl = pos.get("pnl_usd", 0)
            emoji = "🟢" if pnl > 0 else "🔴"
            print(f"    {emoji} {pos['ticker']:>6s}: ${pnl:+.2f} ({pos.get('pnl_pct',0):+.2f}%) "
                  f"[{pos.get('entry_date','')} → {pos.get('exit_date','')}]")
    print()


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="Extreme Decline Paper Trader")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--close-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--daily", action="store_true", help="Full daily cycle")
    args = parser.parse_args()

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    state = load_state()

    if args.status:
        show_status(state, config)
        return

    if args.scan_only or args.daily:
        scan_and_enter(state, config)

    if args.close_only or args.daily:
        close_expired(state, config)

    save_state(state)

    if args.daily:
        show_status(state, config)


if __name__ == "__main__":
    main()
