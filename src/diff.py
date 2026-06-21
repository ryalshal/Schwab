"""
Chain diff — Layer 4a.

Compares today's option chain snapshot against the most recent prior run.
Reports new expiries and new strikes that fall within a configurable band of
any held strike (so you see fresh LEAP expiries / nearby strikes without
scanning the whole chain).

Usage:
    from src.diff import compute_chain_diffs
    diffs = compute_chain_diffs(conn, valuations, as_of)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.models import OptionValuation
from src import snapshot as snap
import config


@dataclass
class NewStrike:
    expiry: str
    option_type: str
    strike: float
    bid: float | None
    ask: float | None
    iv: float | None
    volume: int | None
    oi: int | None


@dataclass
class ChainDiff:
    ticker: str
    as_of: str
    new_expiries: list[str]
    new_strikes: list[NewStrike]


def compute_chain_diffs(
    conn: sqlite3.Connection,
    valuations: list,
    as_of: str,
    band: float = config.CHAIN_DIFF_STRIKE_BAND,
) -> list[ChainDiff]:
    """Return one ChainDiff per option-underlying ticker."""
    option_tickers = {
        v.ticker for v in valuations if isinstance(v, OptionValuation)
    }

    diffs: list[ChainDiff] = []
    for ticker in sorted(option_tickers):
        held = [
            (v.option_type, v.strike)
            for v in valuations
            if isinstance(v, OptionValuation) and v.ticker == ticker
        ]
        diffs.append(_diff_one(conn, ticker, as_of, held, band))
    return diffs


def _diff_one(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: str,
    held: list[tuple[str, float]],
    band: float,
) -> ChainDiff:
    today_rows = conn.execute(
        "SELECT * FROM option_chains WHERE ticker = ? AND as_of_date = ?",
        (ticker, as_of),
    ).fetchall()

    prior_rows = snap.load_prior_chain(ticker, as_of, conn)

    today_expiries = {r["expiry"] for r in today_rows}
    prior_expiries = {r["expiry"] for r in prior_rows}
    new_expiries = sorted(today_expiries - prior_expiries)

    prior_keys = {
        (r["expiry"], r["option_type"], r["strike"]) for r in prior_rows
    }

    new_strikes: list[NewStrike] = []
    for row in today_rows:
        key = (row["expiry"], row["option_type"], row["strike"])
        if key in prior_keys:
            continue
        # Check if within band of any held strike of the same option_type
        for (h_type, h_strike) in held:
            if row["option_type"] == h_type and h_strike > 0:
                if abs(row["strike"] - h_strike) / h_strike <= band:
                    iv = row["iv"]
                    new_strikes.append(NewStrike(
                        expiry=row["expiry"],
                        option_type=row["option_type"],
                        strike=row["strike"],
                        bid=row["bid"],
                        ask=row["ask"],
                        iv=float(iv) if iv is not None else None,
                        volume=row["volume"],
                        oi=row["open_interest"],
                    ))
                    break  # don't double-count across held positions

    return ChainDiff(ticker=ticker, as_of=as_of,
                     new_expiries=new_expiries, new_strikes=new_strikes)
