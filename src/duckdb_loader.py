"""
duckdb_loader.py — Statistical Edge Lab
Load equity data from local DuckDB databases instead of yfinance.

Sources:
  - cedears.duckdb → historico_cedears: AAPL, NVDA, MSFT, GOOGL, TSLA, etc. (USD)
  - historico.duckdb → stock_prices: SPY, IWM, TLT, GLD, etc. (USD)
  - historico.duckdb → ccl_diario: CCL rates for ARS→USD conversion

Covers 2010-2026 (16 years) for AAPL and other liquid US tickers.
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DB_PATHS = {
    "cedears": Path.home() / "shared" / "data" / "db" / "duckdb" / "cedears.duckdb",
    "historico": Path.home() / "shared" / "data" / "db" / "duckdb" / "historico.duckdb",
}


def load_from_duckdb(
    tickers: list[str],
    start: str,
    end: str,
    source_db: str = "cedears",
    table: str = "historico_cedears",
) -> dict[str, pd.DataFrame]:
    """
    Load daily OHLCV from local DuckDB.

    Args:
        tickers: List of ticker symbols (e.g. ['AAPL', 'SPY'])
        start: yyyy-MM-dd
        end: yyyy-MM-dd
        source_db: 'cedears' or 'historico'
        table: Table name ('historico_cedears' for cedears, 'stock_prices' for historico)

    Returns:
        dict[ticker -> DataFrame] with columns [date, open, high, low, close, adj_close, volume]
    """
    import duckdb

    db_path = DB_PATHS.get(source_db)
    if db_path is None or not db_path.exists():
        logger.error(f"DB not found: {db_path}")
        return {}

    con = duckdb.connect(str(db_path), read_only=True)

    result = {}
    for ticker in tickers:
        try:
            if table == "historico_cedears":
                df = con.execute(
                    "SELECT Date as date, Open as open, High as high, Low as low, "
                    "Close as close, Adj_Close as adj_close, Volume as volume "
                    "FROM historico_cedears "
                    "WHERE Ticker = ? AND Date >= ? AND Date <= ? "
                    "ORDER BY Date",
                    [ticker, start, end],
                ).fetchdf()
            elif table == "stock_prices":
                df = con.execute(
                    "SELECT date, open, high, low, close, volume "
                    "FROM stock_prices "
                    "WHERE ticker = ? AND date >= ? AND date <= ? "
                    "ORDER BY date",
                    [ticker, start, end],
                ).fetchdf()
                if not df.empty:
                    df["adj_close"] = df["close"]
            else:
                logger.warning(f"Unknown table: {table}")
                continue

            if df.empty:
                logger.warning(f"No data for {ticker} in {source_db}.{table}")
                continue

            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df.index.name = "date"

            # Convert price columns to numeric (DuckDB returns strings)
            for col in ["open", "high", "low", "close", "adj_close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            result[ticker] = df
            logger.info(f"Loaded {ticker}: {len(df)} rows [{df.index.min().date()} → {df.index.max().date()}]")

        except Exception as e:
            logger.error(f"Failed to load {ticker} from {source_db}: {e}")
            continue

    con.close()
    return result


def load_benchmark_duckdb(
    benchmark_ticker: str = "SPY",
    start: str = "2010-01-01",
    end: str = "2026-07-18",
) -> Optional[pd.DataFrame]:
    """Load benchmark (SPY) from stock_prices table."""
    data = load_from_duckdb(
        [benchmark_ticker], start, end,
        source_db="historico",
        table="stock_prices",
    )
    return data.get(benchmark_ticker)


def load_ccl_duckdb(
    start: str = "2010-01-01",
    end: str = "2026-07-18",
) -> Optional[pd.DataFrame]:
    """Load CCL rates from ccl_diario table."""
    import duckdb

    db_path = DB_PATHS["historico"]
    if not db_path.exists():
        return None

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT date, ccl FROM ccl_diario WHERE date >= ? AND date <= ? ORDER BY date",
            [start, end],
        ).fetchdf()

        if df.empty:
            logger.warning("No CCL data loaded")
            return None

        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        logger.info(f"Loaded CCL: {len(df)} rows [{df.index.min().date()} → {df.index.max().date()}]")
        return df
    except Exception as e:
        logger.error(f"Failed to load CCL: {e}")
        return None
    finally:
        con.close()


# ── Supported universe (from DB tables) ──

UNIVERSE_USD = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", 
                 "JPM", "KO", "DIS", "V"]
BENCHMARKS_USD = ["SPY", "IWM", "TLT", "GLD", "QQQ"]
