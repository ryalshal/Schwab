"""
Portfolio orchestrator — loads positions, pulls market data, computes
valuations, persists snapshots, and returns results.

Importable by later layers:

    from src.portfolio import run_portfolio
    results = run_portfolio(as_of="2026-06-20")
"""
from __future__ import annotations
import json
import sys
from typing import Any

import config
from src.models import (
    OptionPosition,
    SharePosition,
    OptionValuation,
    ShareValuation,
    Valuation,
)
from src.fetcher import fetch_option_market_data, fetch_spot, fetch_full_chain
from src.valuation import value_option, value_shares
from src import snapshot as snap


# ---------------------------------------------------------------------------
# Position loading
# ---------------------------------------------------------------------------

def load_positions(path: str = config.POSITIONS_FILE) -> list[OptionPosition | SharePosition]:
    with open(path) as fh:
        raw: list[dict] = json.load(fh)

    positions = []
    for item in raw:
        atype = item.get("asset_type", "").lower()
        if atype == "option":
            positions.append(OptionPosition(**item))
        elif atype == "shares":
            positions.append(SharePosition(**item))
        else:
            print(f"[warn] Unknown asset_type '{atype}' — skipping", file=sys.stderr)

    return positions


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run_portfolio(
    as_of: str,
    positions_file: str = config.POSITIONS_FILE,
    risk_free_rate: float = config.RISK_FREE_RATE,
    verbose: bool = True,
) -> list[Valuation]:
    """
    Run a full portfolio valuation cycle.

    1. Load positions from JSON.
    2. For each unique underlying, fetch + snapshot the full option chain.
    3. Fetch the specific contract quote for each option position.
    4. Fetch spot for each share position.
    5. Compute greeks + valuations.
    6. Persist everything to SQLite.
    7. Return list of Valuation objects.
    """
    positions = load_positions(positions_file)
    conn = snap.get_connection()
    valuations: list[Valuation] = []

    # Collect unique tickers that have options so we can snapshot full chains once
    option_tickers = {
        p.ticker for p in positions if isinstance(p, OptionPosition)
    }
    share_tickers = {
        p.ticker for p in positions if isinstance(p, SharePosition)
    }

    # --- Snapshot full chains for option underlyings ---
    chain_cache: dict[str, dict] = {}
    spot_cache: dict[str, float] = {}

    for ticker in option_tickers | share_tickers:
        if verbose:
            print(f"  Fetching spot for {ticker}…")
        try:
            spot_data = fetch_spot(ticker)
            spot_cache[ticker] = spot_data.mark
        except Exception as exc:
            print(f"  [warn] spot fetch failed for {ticker}: {exc}", file=sys.stderr)
            spot_cache[ticker] = 0.0

    for ticker in option_tickers:
        if verbose:
            print(f"  Fetching full chain for {ticker}…")
        try:
            chain = fetch_full_chain(ticker)
            chain_cache[ticker] = chain
            json_path = snap.save_chain_snapshot(ticker, chain, as_of)
            snap.upsert_chain(conn, ticker, chain, as_of)
            if verbose:
                print(f"    Snapshot saved -> {json_path}")
        except Exception as exc:
            print(f"  [warn] chain fetch failed for {ticker}: {exc}", file=sys.stderr)
            chain_cache[ticker] = {}

    # --- Value each position ---
    for pos in positions:
        try:
            if isinstance(pos, OptionPosition):
                if verbose:
                    print(f"  Valuing {pos.id}…")
                mkt = fetch_option_market_data(
                    pos.ticker, pos.expiry, pos.strike, pos.option_type
                )
                spot = spot_cache.get(pos.ticker, 0.0)
                val = value_option(pos, mkt, spot, as_of, risk_free_rate)

            else:  # SharePosition
                if verbose:
                    print(f"  Valuing {pos.id}…")
                from src.models import SpotMarketData
                mark = spot_cache.get(pos.ticker, 0.0)
                mkt = SpotMarketData(last=mark, mark=mark)
                val = value_shares(pos, mkt)

            valuations.append(val)
            snap.upsert_valuation(conn, val, as_of)

        except Exception as exc:
            pos_id = getattr(pos, "id", str(pos))
            print(f"  [error] valuation failed for {pos_id}: {exc}", file=sys.stderr)

    conn.close()
    return valuations
