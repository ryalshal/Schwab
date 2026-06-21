"""
Market data fetcher — wraps yfinance.

Returns:
  fetch_option_market_data  → OptionMarketData for a specific contract
  fetch_full_chain          → raw dict of the entire option chain for a ticker
  fetch_spot                → SpotMarketData for an equity ticker
"""
from __future__ import annotations
from typing import Optional
import yfinance as yf

from src.models import OptionMarketData, SpotMarketData


def _mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return None


def fetch_spot(ticker: str) -> SpotMarketData:
    t = yf.Ticker(ticker)
    info = t.fast_info
    last = float(info.last_price)
    return SpotMarketData(last=last, mark=last)


def fetch_option_market_data(
    ticker: str,
    expiry: str,       # YYYY-MM-DD
    strike: float,
    option_type: str,  # "call" | "put"
) -> OptionMarketData:
    """Fetch live quote for a single option contract."""
    t = yf.Ticker(ticker)
    chain = t.option_chain(expiry)
    df = chain.calls if option_type == "call" else chain.puts

    row = df[df["strike"] == strike]
    if row.empty:
        # Fall back to nearest available strike
        nearest_idx = (df["strike"] - strike).abs().idxmin()
        row = df.loc[[nearest_idx]]

    r = row.iloc[0]
    bid = float(r["bid"]) if r["bid"] > 0 else None
    ask = float(r["ask"]) if r["ask"] > 0 else None
    last = float(r["lastPrice"])
    mark = _mid(bid, ask) if _mid(bid, ask) is not None else last
    iv = float(r["impliedVolatility"])
    volume = int(r["volume"]) if not _is_nan(r["volume"]) else 0
    oi = int(r["openInterest"]) if not _is_nan(r["openInterest"]) else 0

    return OptionMarketData(
        bid=bid,
        ask=ask,
        last=last,
        iv=iv,
        volume=volume,
        open_interest=oi,
        mark=mark,
    )


def fetch_full_chain(ticker: str) -> dict:
    """
    Return a JSON-serialisable dict of the complete option chain for *ticker*
    (all available expiries, calls + puts) for snapshot storage.
    """
    t = yf.Ticker(ticker)
    expiries = t.options
    chain_data: dict[str, dict] = {}

    for exp in expiries:
        try:
            chain = t.option_chain(exp)
        except Exception:
            continue
        chain_data[exp] = {
            "calls": _df_to_records(chain.calls),
            "puts": _df_to_records(chain.puts),
        }

    return {"ticker": ticker, "expiries": chain_data}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_nan(v) -> bool:
    try:
        import math
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


def _df_to_records(df) -> list[dict]:
    """Convert a yfinance chain DataFrame to a list of plain dicts."""
    records = []
    for _, row in df.iterrows():
        records.append({
            "contractSymbol": str(row.get("contractSymbol", "")),
            "strike": float(row["strike"]),
            "bid": float(row["bid"]) if not _is_nan(row["bid"]) else None,
            "ask": float(row["ask"]) if not _is_nan(row["ask"]) else None,
            "lastPrice": float(row["lastPrice"]) if not _is_nan(row["lastPrice"]) else None,
            "mark": (
                _mid(
                    float(row["bid"]) if not _is_nan(row["bid"]) else None,
                    float(row["ask"]) if not _is_nan(row["ask"]) else None,
                )
                or (float(row["lastPrice"]) if not _is_nan(row["lastPrice"]) else None)
            ),
            "impliedVolatility": float(row["impliedVolatility"]) if not _is_nan(row["impliedVolatility"]) else None,
            "volume": int(row["volume"]) if not _is_nan(row["volume"]) else 0,
            "openInterest": int(row["openInterest"]) if not _is_nan(row["openInterest"]) else 0,
            "inTheMoney": bool(row.get("inTheMoney", False)),
        })
    return records
