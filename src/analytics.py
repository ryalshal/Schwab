"""
Portfolio analytics layer — Layer 2.

Importable entry point:
    from src.analytics import compute_analytics, PortfolioAnalytics
    result = compute_analytics(valuations, as_of, conn)
"""
from __future__ import annotations
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import config
from src.models import OptionValuation, ShareValuation, Valuation
from src.sector import get_sector


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AllocationEntry:
    ticker: str
    sector: str
    value: float
    pct: float          # fraction of total portfolio value, 0-100


@dataclass
class SectorAllocation:
    sector: str
    value: float
    pct: float


@dataclass
class ConcentrationFlag:
    kind: str           # "ticker" | "sector"
    name: str
    pct: float
    cap: float


@dataclass
class AggregateGreeks:
    net_delta_shares: float   # sum of delta * 100 * contracts (options) + contracts (shares)
    total_theta_daily: float  # sum of theta * 100 * contracts, in dollars per day
    net_vega_per_pp: float    # sum of vega * 100 * contracts, per 1 pp IV move


@dataclass
class IVStats:
    position_id: str
    ticker: str
    expiry: str
    option_type: str
    strike: float
    dte: int
    current_iv: float
    history_days: int
    iv_rank: Optional[float]        # (current - min) / (max - min) * 100
    iv_percentile: Optional[float]  # fraction of history days where iv < current * 100
    status: str                     # "building history" | "cheap" | "rich" | "normal"


@dataclass
class DTEFlag:
    position_id: str
    ticker: str
    option_type: str
    strike: float
    expiry: str
    dte: int
    threshold: int


@dataclass
class PortfolioAnalytics:
    as_of_date: str
    total_value: float
    allocations_by_ticker: list[AllocationEntry]
    allocations_by_sector: list[SectorAllocation]
    concentration_flags: list[ConcentrationFlag]
    aggregate_greeks: AggregateGreeks
    iv_stats: list[IVStats]
    dte_flags: list[DTEFlag]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_analytics(
    valuations: list[Valuation],
    as_of: str,
    conn: sqlite3.Connection,
    ticker_cap: float = config.TICKER_CONCENTRATION_CAP,
    sector_cap: float = config.SECTOR_CONCENTRATION_CAP,
    iv_lookback: int = config.IV_LOOKBACK_DAYS,
    iv_min_history: int = config.IV_MIN_HISTORY_DAYS,
    iv_rich: float = config.IV_RICH_THRESHOLD,
    iv_cheap: float = config.IV_CHEAP_THRESHOLD,
    dte_warn: int = config.DTE_WARNING_THRESHOLD,
) -> PortfolioAnalytics:
    total_value = sum(v.current_value for v in valuations)

    alloc_ticker = _allocation_by_ticker(valuations, total_value)
    alloc_sector = _allocation_by_sector(alloc_ticker)
    flags = _concentration_flags(alloc_ticker, alloc_sector, ticker_cap, sector_cap)
    greeks = _aggregate_greeks(valuations)
    iv_stats = _iv_stats(valuations, as_of, conn, iv_lookback, iv_min_history, iv_rich, iv_cheap)
    dte_flags = _dte_flags(valuations, dte_warn)

    return PortfolioAnalytics(
        as_of_date=as_of,
        total_value=total_value,
        allocations_by_ticker=alloc_ticker,
        allocations_by_sector=alloc_sector,
        concentration_flags=flags,
        aggregate_greeks=greeks,
        iv_stats=iv_stats,
        dte_flags=dte_flags,
    )


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def _allocation_by_ticker(
    valuations: list[Valuation], total: float
) -> list[AllocationEntry]:
    by_ticker: dict[str, float] = defaultdict(float)
    for v in valuations:
        by_ticker[v.ticker] += v.current_value

    entries = []
    for ticker, value in sorted(by_ticker.items(), key=lambda x: -x[1]):
        entries.append(AllocationEntry(
            ticker=ticker,
            sector=get_sector(ticker),
            value=value,
            pct=(value / total * 100) if total else 0.0,
        ))
    return entries


def _allocation_by_sector(
    ticker_allocs: list[AllocationEntry],
) -> list[SectorAllocation]:
    by_sector: dict[str, float] = defaultdict(float)
    for a in ticker_allocs:
        by_sector[a.sector] += a.value

    total = sum(by_sector.values())
    return sorted(
        [
            SectorAllocation(sector=s, value=v, pct=(v / total * 100) if total else 0.0)
            for s, v in by_sector.items()
        ],
        key=lambda x: -x.value,
    )


def _concentration_flags(
    ticker_allocs: list[AllocationEntry],
    sector_allocs: list[SectorAllocation],
    ticker_cap: float,
    sector_cap: float,
) -> list[ConcentrationFlag]:
    flags = []
    ticker_cap_pct = ticker_cap * 100
    sector_cap_pct = sector_cap * 100

    for a in ticker_allocs:
        if a.pct > ticker_cap_pct:
            flags.append(ConcentrationFlag(
                kind="ticker", name=a.ticker, pct=a.pct, cap=ticker_cap_pct
            ))
    for s in sector_allocs:
        if s.pct > sector_cap_pct:
            flags.append(ConcentrationFlag(
                kind="sector", name=s.sector, pct=s.pct, cap=sector_cap_pct
            ))
    return flags


# ---------------------------------------------------------------------------
# Aggregate greeks
# ---------------------------------------------------------------------------

def _aggregate_greeks(valuations: list[Valuation]) -> AggregateGreeks:
    net_delta = 0.0
    total_theta = 0.0
    net_vega = 0.0

    for v in valuations:
        if isinstance(v, OptionValuation):
            mult = config.CONTRACTS_PER_OPTION * v.contracts
            net_delta += v.greeks.delta * mult
            total_theta += v.greeks.theta * mult   # $/day for this position
            net_vega += v.greeks.vega * mult        # $ per 1pp IV for this position
        else:
            # Shares: delta = 1 per share, no theta/vega
            net_delta += v.contracts

    return AggregateGreeks(
        net_delta_shares=net_delta,
        total_theta_daily=total_theta,
        net_vega_per_pp=net_vega,
    )


# ---------------------------------------------------------------------------
# IV stats (rank + percentile from stored snapshots)
# ---------------------------------------------------------------------------

def _iv_stats(
    valuations: list[Valuation],
    as_of: str,
    conn: sqlite3.Connection,
    lookback: int,
    min_history: int,
    rich_threshold: float,
    cheap_threshold: float,
) -> list[IVStats]:
    start_date = (
        date.fromisoformat(as_of) - timedelta(days=lookback)
    ).isoformat()

    stats = []
    for v in valuations:
        if not isinstance(v, OptionValuation):
            continue

        rows = conn.execute(
            """
            SELECT iv FROM option_chains
            WHERE ticker     = ?
              AND expiry      = ?
              AND option_type = ?
              AND strike      = ?
              AND as_of_date >= ?
              AND as_of_date <= ?
              AND iv IS NOT NULL
            ORDER BY as_of_date
            """,
            (v.ticker, v.expiry, v.option_type, v.strike, start_date, as_of),
        ).fetchall()

        history = [r["iv"] for r in rows]
        n = len(history)
        current_iv = v.iv

        if n < min_history:
            stats.append(IVStats(
                position_id=v.position_id,
                ticker=v.ticker,
                expiry=v.expiry,
                option_type=v.option_type,
                strike=v.strike,
                dte=v.dte,
                current_iv=current_iv,
                history_days=n,
                iv_rank=None,
                iv_percentile=None,
                status="building history",
            ))
            continue

        lo, hi = min(history), max(history)
        iv_rank = (
            (current_iv - lo) / (hi - lo) * 100.0
            if hi > lo else 50.0
        )
        iv_pct = sum(1 for iv in history if iv < current_iv) / n * 100.0

        # Use rank for the rich/cheap label (consistent single signal)
        if iv_rank >= rich_threshold:
            status = "rich"
        elif iv_rank <= cheap_threshold:
            status = "cheap"
        else:
            status = "normal"

        stats.append(IVStats(
            position_id=v.position_id,
            ticker=v.ticker,
            expiry=v.expiry,
            option_type=v.option_type,
            strike=v.strike,
            dte=v.dte,
            current_iv=current_iv,
            history_days=n,
            iv_rank=iv_rank,
            iv_percentile=iv_pct,
            status=status,
        ))

    return stats


# ---------------------------------------------------------------------------
# DTE flags
# ---------------------------------------------------------------------------

def _dte_flags(valuations: list[Valuation], threshold: int) -> list[DTEFlag]:
    flags = []
    for v in valuations:
        if isinstance(v, OptionValuation) and v.dte <= threshold:
            flags.append(DTEFlag(
                position_id=v.position_id,
                ticker=v.ticker,
                option_type=v.option_type,
                strike=v.strike,
                expiry=v.expiry,
                dte=v.dte,
                threshold=threshold,
            ))
    return flags
