"""
data_loader.py — Statistical Edge Lab
Phase 1: Load and cache market data from yfinance or DuckDB.

Audit P0 #4: Instrument metadata for explicit ticker resolution.
Audit P0 #4: Correct ADR ratio formula (local * ratio / adr).
Audit P0 #16: Adjusted prices for OHLC.
"""

import json
import logging
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "raw"
CACHE_SCHEMA_VERSION = "1.0"

# ── Instrument registry (Audit P0 #4) ──
# Explicit metadata per ticker. No symbol guessing.
INSTRUMENTS = {
    # Argentine equities
    "GGAL.BA":  {"yahoo": "GGAL.BA",  "market": "argentina", "currency": "ARS"},
    "YPFD.BA":  {"yahoo": "YPFD.BA",  "market": "argentina", "currency": "ARS"},
    "PAMP.BA":  {"yahoo": "PAMP.BA",  "market": "argentina", "currency": "ARS"},
    "BBAR.BA":  {"yahoo": "BBAR.BA",  "market": "argentina", "currency": "ARS"},
    "BMA.BA":   {"yahoo": "BMA.BA",   "market": "argentina", "currency": "ARS"},
    "TGSU2.BA": {"yahoo": "TGSU2.BA", "market": "argentina", "currency": "ARS"},
    "CEPU.BA":  {"yahoo": "CEPU.BA",  "market": "argentina", "currency": "ARS"},
    "TXAR.BA":  {"yahoo": "TXAR.BA",  "market": "argentina", "currency": "ARS"},
    # US ETFs
    "SPY":  {"yahoo": "SPY",  "market": "usa", "currency": "USD"},
    "QQQ":  {"yahoo": "QQQ",  "market": "usa", "currency": "USD"},
    "EWZ":  {"yahoo": "EWZ",  "market": "usa", "currency": "USD"},
    "ARGT": {"yahoo": "ARGT", "market": "usa", "currency": "USD"},
    # ADRs (explicit — never route to .BA)
    "GGAL": {"yahoo": "GGAL", "market": "usa", "currency": "USD", "instrument_type": "adr"},
    # Benchmarks
    "^MERV": {"yahoo": "^MERV", "market": "argentina", "currency": "ARS"},
}

# ADR ratios (Audit P0 #4): local shares represented by 1 ADR
ADR_RATIOS = {
    "GGAL": 10,
}


# ── Cache metadata helpers (Q7) ──


def _cache_meta_path(csv_path: Path) -> Path:
    """Return companion .meta.json path for a cache CSV."""
    return csv_path.with_suffix(".meta.json")


def _compute_content_hash(df: pd.DataFrame) -> str:
    """Compute SHA256 of the CSV content for integrity."""
    content = df.to_csv().encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _write_cache_with_metadata(
    df: pd.DataFrame,
    csv_path: Path,
    ticker: str,
    yahoo_ticker: str,
    source: str,
    requested_start: str,
    requested_end: str,
    auto_adjust: bool = False,
):
    """Write CSV + companion metadata file."""
    df.to_csv(csv_path)
    content_hash = _compute_content_hash(df)
    first_date = str(df.index.min().date()) if len(df) else None
    last_date = str(df.index.max().date()) if len(df) else None

    meta = {
        "ticker": ticker,
        "yahoo_ticker": yahoo_ticker,
        "source": source,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "first_available_date": first_date,
        "last_available_date": last_date,
        "n_rows": len(df),
        "auto_adjust": auto_adjust,
        "schema_version": CACHE_SCHEMA_VERSION,
        "content_sha256": content_hash,
    }
    meta_path = _cache_meta_path(csv_path)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"Cache metadata written to {meta_path}")


def _validate_cache_metadata(
    csv_path: Path,
    ticker: str,
    requested_start: str,
    requested_end: str,
    source: str,
) -> Optional[dict]:
    """
    Validate cache metadata against requested params.

    Returns metadata dict if valid, None if cache should be skipped.
    """
    meta_path = _cache_meta_path(csv_path)
    if not meta_path.exists():
        logger.info(f"No metadata for {csv_path.name} — skipping cache")
        return None

    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except Exception as e:
        logger.warning(f"Cannot read metadata {meta_path}: {e}")
        return None

    # Schema version check
    if meta.get("schema_version") != CACHE_SCHEMA_VERSION:
        logger.info(f"Cache schema mismatch for {ticker}: {meta.get('schema_version')} != {CACHE_SCHEMA_VERSION}")
        return None

    # Source check
    if meta.get("source") != source:
        logger.info(f"Cache source mismatch for {ticker}: {meta.get('source')} != {source}")
        return None

    # Coverage check: requested range must be within cached range
    # yfinance uses exclusive end, so a cached range starting <= requested_start
    # and ending >= requested_end means we have at least as much data as needed.
    meta_req_start = meta.get("requested_start")
    meta_req_end = meta.get("requested_end")
    if meta_req_start and meta_req_end:
        if requested_start < meta_req_start or requested_end > meta_req_end:
            logger.info(f"Cache coverage insufficient for {ticker}: "
                        f"cached request [{meta_req_start}, {meta_req_end}], "
                        f"needs [{requested_start}, {requested_end}]")
            return None
        logger.info(f"  Cached range [{meta_req_start}, {meta_req_end}] covers request")

    # Content integrity (verify hash)
    try:
        df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        current_hash = _compute_content_hash(df)
        if current_hash != meta.get("content_sha256"):
            logger.warning(f"Content hash mismatch for {ticker} — cache corrupted")
            return None
    except Exception as e:
        logger.warning(f"Cannot verify cache integrity for {ticker}: {e}")
        return None

    logger.info(f"Cache valid for {ticker}: req=[{meta_req_start}, {meta_req_end}], "
                f"actual=[{meta.get('first_available_date')}, {meta.get('last_available_date')}], "
                f"rows={meta.get('n_rows', '?')}")
    return meta


def instrument_info(ticker: str) -> dict:
    """Get instrument metadata. Raises KeyError if unknown."""
    t = ticker.strip()
    if t in INSTRUMENTS:
        return INSTRUMENTS[t]
    # Fallback: if ends with .BA, assume argentina
    if t.endswith(".BA"):
        return {"yahoo": t, "market": "argentina", "currency": "ARS"}
    # Fallback: assume US stock
    return {"yahoo": t, "market": "usa", "currency": "USD"}


def market_for_ticker(ticker: str) -> str:
    """Return 'argentina' or 'usa'."""
    return instrument_info(ticker).get("market", "usa")


def is_argentine(ticker: str) -> bool:
    return market_for_ticker(ticker) == "argentina"


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
    Also adds 'open_adj', 'high_adj', 'low_adj' from adjustment factor.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    result = {}
    for raw_ticker in tickers:
        info = instrument_info(raw_ticker)
        yahoo_ticker = info["yahoo"]
        cache_path = CACHE_DIR / f"{yahoo_ticker.replace('^', '_')}.csv"

        # Try cache first (with metadata validation)
        cache_valid = False
        if use_cache and cache_path.exists() and not force_download:
            meta = _validate_cache_metadata(
                cache_path, raw_ticker, start, end, source
            )
            if meta is not None:
                try:
                    df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                    logger.info(f"Loaded {raw_ticker} from cache ({len(df)} rows)")
                    result[raw_ticker] = df
                    cache_valid = True
                except Exception as e:
                    logger.warning(f"Cache read failed for {raw_ticker}: {e}")

        if cache_valid:
            continue

        logger.info(f"Downloading {raw_ticker} (-> {yahoo_ticker}) from {start} to {end}")
        try:
            yf_ticker = yf.Ticker(yahoo_ticker)
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
            if df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            # Normalize to midnight for cross-market date matching
            df.index = df.index.normalize()
            df.index.name = "date"

            # Ensure adj_close exists
            if "adj_close" not in df.columns:
                df["adj_close"] = df["close"]

            # Build adjusted OHLC (Audit P0 #16)
            if "adj_close" in df.columns and "close" in df.columns:
                adj_factor = df["adj_close"] / df["close"].replace(0, float("nan"))
                df["open_adj"] = df["open"] * adj_factor
                df["high_adj"] = df["high"] * adj_factor
                df["low_adj"] = df["low"] * adj_factor
            else:
                df["open_adj"] = df["open"]
                df["high_adj"] = df["high"]
                df["low_adj"] = df["low"]

            # Keep required columns
            keep = ["open", "high", "low", "close", "adj_close",
                    "open_adj", "high_adj", "low_adj", "volume"]
            df = df[[c for c in keep if c in df.columns]]

            if use_cache:
                _write_cache_with_metadata(
                    df, cache_path, raw_ticker, yahoo_ticker,
                    source, start, end, auto_adjust=False,
                )

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
    data = load_data([ticker], start, end, source)
    return data.get(ticker)


def load_ccl_series(start: str, end: str) -> Optional[pd.DataFrame]:
    """
    Load daily CCL implied rate for ARS->USD conversion.

    Audit P0 #4: Correct ADR formula, explicit ticker resolution,
    no backfill of future values, fail if missing for AR assets.
    """
    # Try DuckDB first
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

    # Fallback: build CCL proxy from GGAL.BA / GGAL ADR
    try:
        local = load_data(["GGAL.BA"], start, end, use_cache=True)
        if "GGAL.BA" not in local:
            logger.error("CCL: Cannot load GGAL.BA")
            return None
        local_df = local["GGAL.BA"]

        # Load GGAL ADR — correct: 'GGAL' resolves to US ADR via instrument_info
        adr = load_data(["GGAL"], start, end, use_cache=True)
        if "GGAL" not in adr:
            logger.error("CCL: Cannot load GGAL ADR")
            return None
        adr_df = adr["GGAL"]

        # Normalize indices for joining
        local_df.index = local_df.index.normalize()
        adr_df.index = adr_df.index.normalize()

        # Merge
        merged = local_df[["close"]].rename(columns={"close": "local_ars"})
        adr_close = adr_df[["close"]].rename(columns={"close": "adr_usd"})
        merged = merged.join(adr_close, how="inner")

        if merged.empty:
            logger.error("CCL: No overlapping dates between GGAL.BA and GGAL ADR")
            return None

        # Correct formula: CCL = local_ars * ratio / adr_usd  (Audit P0 #4)
        ratio = ADR_RATIOS.get("GGAL", 10)
        merged["ccl"] = merged["local_ars"] * ratio / merged["adr_usd"]

        # Validate CCL range (Audit P0 #4)
        merged = merged[(merged["ccl"] > 10) & (merged["ccl"] < 5000)]
        if merged.empty:
            logger.error("CCL: All values outside valid range [10, 5000]")
            return None

        # Forward-fill only within reasonable gap (5 sessions)
        merged["ccl"] = merged["ccl"].ffill(limit=5)
        merged = merged.dropna(subset=["ccl"])

        # Remove rows before first valid CCL
        first_valid = merged["ccl"].first_valid_index()
        if first_valid:
            merged = merged.loc[first_valid:]

        result = merged[["ccl"]]
        cache_path = CACHE_DIR / "ccl_proxy.csv"
        _write_cache_with_metadata(
            result, cache_path, "ccl_proxy", "ccl_proxy",
            "yahoo_ggal_dual", start, end,
        )
        logger.info(f"Built CCL proxy from GGAL dual ({len(result)} rows), ratio={ratio}")
        return result

    except Exception as e:
        logger.error(f"CCL proxy failed: {e}")
        return None
