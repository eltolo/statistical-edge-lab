"""
data_loader.py — Statistical Edge Lab
Phase 1: Load and cache market data from yfinance or DuckDB.

Spec §7: Required data fields per asset:
  date, open, high, low, close, adjusted_close, volume
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "raw"


def _ticker_to_yahoo(ticker: str) -> str:
    """Normalize ticker for yfinance. Local AR tickers keep .BA suffix."""
    t = ticker.strip().upper()
    if t == "^MERV":
        return "^MERV"
    if not t.endswith(".BA") and not t.startswith("^"):
        # Check if it's a US ticker (SPY, QQQ, etc.)
        us_tickers = {"SPY", "QQQ", "EWZ", "ARGT", "DIA", "IWM", "EFA", "EEM"}
        if t not in us_tickers:
            return t + ".BA"
    return t


def _ticker_from_yahoo(ticker: str) -> str:
    """Reverse normalization."""
    return ticker.replace(".BA", "")


def load_data(
    tickers: list[str],
    start: str,
    end: str,
    source: str = "yahoo",
    use_cache: bool = True,
    force_download: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    Load OHLCV data for a list of tickers.

    Returns dict[ticker -> DataFrame with columns:
        date, open, high, low, close, adj_close, volume
    ]
    Date is the index (datetime).
    Uses CSV for caching (no pyarrow dependency).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    result = {}
    for raw_ticker in tickers:
        ticker = _ticker_to_yahoo(raw_ticker)
        cache_path = CACHE_DIR / f"{ticker.replace('^', '_')}.csv"

        # Try cache first
        if use_cache and cache_path.exists() and not force_download:
            try:
                df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                logger.info(f"Loaded {raw_ticker} from cache ({len(df)} rows)")
                result[raw_ticker] = df
                continue
            except Exception as e:
                logger.warning(f"Cache read failed for {raw_ticker}: {e}")

        logger.info(f"Downloading {raw_ticker} (-> {ticker}) from {start} to {end}")
        try:
            yf_ticker = yf.Ticker(ticker)
            df = yf_ticker.history(start=start, end=end, auto_adjust=False)

            if df.empty:
                logger.warning(f"No data for {raw_ticker}")
                continue

            # Standardize columns
            df = df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
                "Adj Close": "adj_close",
            })
            df.index = pd.to_datetime(df.index)
            # Normalize to timezone-naive (yfinance returns NY timezone)
            if df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            df.index.name = "date"

            # Ensure adj_close exists
            if "adj_close" not in df.columns:
                df["adj_close"] = df["close"]

            # Keep only required columns
            cols = ["open", "high", "low", "close", "adj_close", "volume"]
            df = df[[c for c in cols if c in df.columns]]

            # Cache as CSV
            if use_cache:
                df.to_csv(cache_path)
                logger.info(f"Cached {raw_ticker} ({len(df)} rows)")

            result[raw_ticker] = df

        except Exception as e:
            logger.error(f"Failed to load {raw_ticker}: {e}")
            continue

    return result


def load_benchmark(
    ticker: str,
    start: str,
    end: str,
    source: str = "yahoo",
) -> Optional[pd.DataFrame]:
    """Load benchmark data (e.g., ^MERV)."""
    data = load_data([ticker], start, end, source)
    return data.get(ticker)


def load_ccl_series(start: str, end: str) -> Optional[pd.DataFrame]:
    """
    Load daily CCL implied rate for ARS->USD conversion.

    For MVP, uses ARGT/GGAL CCL proxy from yfinance.
    Falls back to loading pre-computed CCL from DuckDB if available.
    """
    # Try DuckDB first (ecosystem source of truth)
    duckdb_path = Path.home() / "shared" / "data" / "db" / "duckdb"
    try:
        import duckdb
        con = duckdb.connect(str(duckdb_path / "matriz.duckdb"))
        ccl = con.execute("""
            SELECT fecha, ccl_implícito as ccl
            FROM cotizaciones
            WHERE ticker = 'GGAL'
            AND fecha BETWEEN ? AND ?
            ORDER BY fecha
        """, [start, end]).fetchdf()
        con.close()
        if not ccl.empty:
            ccl["date"] = pd.to_datetime(ccl["fecha"])
            ccl = ccl.set_index("date")[["ccl"]]
            logger.info(f"Loaded CCL from DuckDB ({len(ccl)} rows)")
            return ccl
    except Exception:
        logger.info("DuckDB CCL not available, using yfinance proxy")

    # Fallback: build CCL proxy from GGAL.BA / GGAL (ADR)
    try:
        # Load local GGAL.BA in ARS
        local = load_data(["GGAL.BA"], start, end, use_cache=True)
        if "GGAL.BA" not in local:
            return None
        local_df = local["GGAL.BA"]

        # Load GGAL ADR in USD
        adr = load_data(["GGAL"], start, end, use_cache=True)
        if "GGAL" not in adr:
            return None
        adr_df = adr["GGAL"]

        # Merge and calculate CCL
        merged = local_df[["close"]].rename(columns={"close": "ars"})
        merged = merged.join(adr_df[["close"]].rename(columns={"close": "usd"}), how="inner")
        # GGAL ADR ratio = 10 (1 ADR = 10 local shares)
        merged["ccl"] = merged["ars"] / (merged["usd"] * 10)
        merged = merged[["ccl"]]

        # Cache as CSV
        cache_path = CACHE_DIR / "ccl_proxy.csv"
        merged.to_csv(cache_path)

        logger.info(f"Built CCL proxy from GGAL dual ({len(merged)} rows)")
        return merged
    except Exception as e:
        logger.warning(f"Could not build CCL proxy: {e}")

    return None
