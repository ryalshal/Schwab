"""Ticker-to-sector lookup: config map first, yfinance info as fallback."""
from __future__ import annotations
import yfinance as yf
import config

_yf_cache: dict[str, str] = {}


def get_sector(ticker: str) -> str:
    if ticker in config.SECTOR_MAP:
        return config.SECTOR_MAP[ticker]
    if ticker in _yf_cache:
        return _yf_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        sector = (
            info.get("sector")
            or info.get("category")
            or info.get("fundFamily")
            or "Unknown"
        )
    except Exception:
        sector = "Unknown"
    _yf_cache[ticker] = sector
    return sector
