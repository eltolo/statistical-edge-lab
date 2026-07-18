"""
futures_loader.py — Statistical Edge Lab
Load ROFEX futures data from duckdb or pyRofex API.

Two sources:
  1. rofex.duckdb — real-time streaming data (when collector is running)
  2. pyRofex REST API — historical trade backfill

Contract naming:
  GGAL/AGO26  (GGAL, expiry AGO26)
  DLR/AGO26  (USD futures)
  RFX20/AGO26 (index futures)

Backfill via:
  pyRofex.get_trade_history(ticker, start_date, end_date)
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# DuckDB path (matches colector_rofex_v2.py default)
DUCKDB_PATH = Path(os.environ.get(
    "ROFEX_DUCKDB_PATH",
    str(Path.home() / "shared" / "data" / "db" / "duckdb" / "rofex.duckdb"),
))

# ⚠️ DuckDB lock strategy:
# The collector holds an exclusive lock on rofex.duckdb.
# For reads, we use a separate in-memory DuckDB that attaches
# the live DB in read-only mode.
# If that fails, fall back to pyRofex REST API.

# pyRofex credentials (same source as collector)
REMARKET_USER = os.environ.get("PYROFEX_USER", "sandbox")
REMARKET_PASS = os.environ.get("PYROFEX_PASS", "sandbox")
REMARKET_ACCT = os.environ.get("PYROFEX_ACCT", REMARKET_USER)


def _get_duckdb_conn(read_only: bool = True):
    """
    Get a DuckDB connection to rofex.duckdb.
    Uses READ_ONLY attach to avoid lock conflicts with the collector.
    """
    import duckdb

    if read_only:
        # Create in-memory session and attach the live DB read-only
        con = duckdb.connect(":memory:")
        try:
            con.execute(f"ATTACH '{DUCKDB_PATH}' AS rofex (READ_ONLY)")
            return con
        except Exception as e:
            logger.warning(f"Cannot attach rofex.duckdb read-only: {e}")
            con.close()
            return None
    else:
        # Direct connection (only works if collector is not running)
        try:
            con = duckdb.connect(str(DUCKDB_PATH), read_only=False)
            return con
        except Exception as e:
            logger.warning(f"Cannot connect to rofex.duckdb: {e}")
            return None


def list_instruments() -> pd.DataFrame:
    """List all ROFEX instruments from the database."""
    con = _get_duckdb_conn()
    if con is None:
        logger.error("Cannot access rofex.duckdb — is the collector running?")
        return pd.DataFrame()

    try:
        df = con.execute("SELECT * FROM rofex.rofex_instrumentos").fetchdf()
        return df
    except Exception as e:
        logger.error(f"Error reading instruments: {e}")
        return pd.DataFrame()
    finally:
        con.close()


def get_market_data(symbol: str, limit: int = 100) -> pd.DataFrame:
    """Get market data snapshots for a symbol."""
    con = _get_duckdb_conn()
    if con is None:
        return pd.DataFrame()

    try:
        df = con.execute(
            f"SELECT * FROM rofex.rofex_market_data WHERE symbol = ? ORDER BY timestamp DESC LIMIT {limit}",
            [symbol],
        ).fetchdf()
        return df
    except Exception as e:
        logger.error(f"Error reading market data for {symbol}: {e}")
        return pd.DataFrame()
    finally:
        con.close()


def get_trades(symbol: str, limit: int = 1000) -> pd.DataFrame:
    """Get trade history for a symbol from the database."""
    con = _get_duckdb_conn()
    if con is None:
        return pd.DataFrame()

    try:
        df = con.execute(
            f"SELECT * FROM rofex.rofex_trades WHERE symbol = ? ORDER BY trade_date DESC LIMIT {limit}",
            [symbol],
        ).fetchdf()
        return df
    except Exception as e:
        logger.error(f"Error reading trades for {symbol}: {e}")
        return pd.DataFrame()
    finally:
        con.close()


def get_stream_ticks(
    symbol: str,
    snapshot_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Get all stream ticks for a symbol from the snapshot.

    Args:
        symbol: e.g. 'GGAL/AGO26'
        snapshot_path: Path to snapshot duckdb

    Returns:
        DataFrame with [symbol, timestamp, bid, ask, last, last_size]
    """
    db_path = snapshot_path or "/tmp/rofex_snapshot.duckdb"

    try:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
        df = con.execute(
            "SELECT symbol, timestamp, bid, ask, last, last_size "
            "FROM rofex_stream WHERE symbol = ? "
            "AND (bid IS NOT NULL OR ask IS NOT NULL OR last IS NOT NULL) "
            "ORDER BY timestamp",
            [symbol],
        ).fetchdf()
        con.close()
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"])
            # Convert price columns to numeric
            for col in ["bid", "ask", "last", "last_size"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        logger.error(f"Error reading stream for {symbol}: {e}")
        return pd.DataFrame()


def snapshot_stream_to_daily(
    symbol: str,
    snapshot_path: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load stream data from snapshot and convert to daily OHLCV.
    """
    from futures_execution import build_daily_ohlcv_from_stream

    ticks = get_stream_ticks(symbol, snapshot_path)
    if ticks.empty:
        logger.warning(f"No stream data for {symbol}")
        return pd.DataFrame()

    return build_daily_ohlcv_from_stream(ticks, symbol)


# ── Backfill (pyRofex historical) ──

def backfill_trades(
    ticker: str,
    start_date: str,
    end_date: str,
    environment: str = "REMARKET",
) -> pd.DataFrame:
    """
    Backfill historical trades from pyRofex API.

    Args:
        ticker: Instrument symbol (e.g. 'GGAL/AGO26')
        start_date: yyyy-MM-dd
        end_date: yyyy-MM-dd
        environment: 'REMARKET' (sandbox) or 'LIVE'

    Returns:
        DataFrame of trades, or empty if failed.
    """
    import pyRofex

    # Map environment string to pyRofex enum
    env = pyRofex.Environment.REMARKET if environment == "REMARKET" else pyRofex.Environment.LIVE

    try:
        pyRofex.initialize(
            user=REMARKET_USER,
            password=REMARKET_PASS,
            account=REMARKET_ACCT,
            environment=env,
        )
    except Exception as e:
        logger.warning(f"pyRofex init failed: {e}")
        # Already initialized? Try anyway

    try:
        result = pyRofex.get_trade_history(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
        )
        trades = result.get("trades", [])
        if not trades:
            logger.info(f"No trades found for {ticker} [{start_date} → {end_date}]")
            return pd.DataFrame()

        rows = []
        for t in trades:
            rows.append({
                "symbol": ticker,
                "trade_date": t.get("datetime"),
                "price": t.get("price"),
                "volume": t.get("size"),
                "buy_or_sell": t.get("buyOrSell"),
            })

        df = pd.DataFrame(rows)
        logger.info(f"Backfill {ticker}: {len(df)} trades [{start_date} → {end_date}]")
        return df

    except Exception as e:
        logger.error(f"Backfill failed for {ticker}: {e}")
        return pd.DataFrame()


# ── Contract utils ──

def resolve_contract(symbol: str, target_date: Optional[str] = None) -> Optional[str]:
    """
    Resolve which contract to use for a given date.
    e.g. GGAL → GGAL/AGO26 (nearest active contract)

    Args:
        symbol: Base symbol (e.g. 'GGAL')
        target_date: Date string yyyy-MM-dd (default: today)

    Returns:
        Full contract symbol (e.g. 'GGAL/AGO26'), or None if not found.
    """
    con = _get_duckdb_conn()
    if con is None:
        logger.error("Cannot resolve contract: no DB access")
        return None

    try:
        # Get all instruments matching the base symbol
        instruments = con.execute(
            "SELECT symbol FROM rofex.rofex_instrumentos WHERE symbol LIKE ?",
            [f"{symbol}/%"],
        ).fetchdf()

        if instruments.empty:
            logger.warning(f"No contracts found for {symbol}")
            return None

        # Return the most recent one (heuristic: lexicographic sort)
        contracts = sorted(instruments["symbol"].tolist())
        return contracts[-1]

    except Exception as e:
        logger.error(f"Error resolving contract for {symbol}: {e}")
        return None
    finally:
        con.close()


def list_ggal_contracts() -> pd.DataFrame:
    """List all available GGAL futures contracts."""
    con = _get_duckdb_conn()
    if con is None:
        return pd.DataFrame()

    try:
        df = con.execute(
            "SELECT symbol, description, ultima_actualizacion FROM rofex.rofex_instrumentos WHERE symbol LIKE 'GGAL/%' ORDER BY symbol"
        ).fetchdf()
        return df
    except Exception as e:
        logger.error(f"Error listing GGAL contracts: {e}")
        return pd.DataFrame()
    finally:
        con.close()
