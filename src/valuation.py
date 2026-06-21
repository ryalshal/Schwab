"""
Valuation engine — combines market data + greeks into per-position results.
"""
from __future__ import annotations
from datetime import date

import config
from src.models import (
    Greeks,
    OptionMarketData,
    OptionPosition,
    OptionValuation,
    SharePosition,
    ShareValuation,
    SpotMarketData,
)
from src.greeks import compute_greeks


def _dte(expiry: str, as_of: str) -> int:
    exp = date.fromisoformat(expiry)
    ref = date.fromisoformat(as_of)
    return max(0, (exp - ref).days)


def _progress(current: float, entry: float, target: float) -> float | None:
    """
    Percentage of the way from entry to target.

    Positive = moving in the right direction.
    Can exceed 100 (target passed) or go negative (moved the wrong way).
    """
    span = target - entry
    if span == 0:
        return None
    return (current - entry) / span * 100.0


def value_option(
    pos: OptionPosition,
    mkt: OptionMarketData,
    spot: float,
    as_of: str,
    risk_free_rate: float = config.RISK_FREE_RATE,
) -> OptionValuation:
    dte = _dte(pos.expiry, as_of)
    mark = mkt.mark
    multiplier = config.CONTRACTS_PER_OPTION * pos.contracts

    current_value = mark * multiplier
    entry_value = pos.entry_price * multiplier
    unrealized_pnl = current_value - entry_value
    unrealized_pnl_pct = (unrealized_pnl / entry_value * 100.0) if entry_value else 0.0

    greeks = compute_greeks(
        spot=spot,
        strike=pos.strike,
        dte=dte,
        iv=mkt.iv,
        option_type=pos.option_type,
        risk_free_rate=risk_free_rate,
    )

    progress_to_target = (
        _progress(mark, pos.entry_price, pos.target_price)
        if pos.target_price is not None
        else None
    )
    # Progress toward stop: how far we've moved from entry in the stop direction
    progress_to_stop = (
        _progress(mark, pos.entry_price, pos.stop_price)
        if pos.stop_price is not None
        else None
    )

    return OptionValuation(
        position_id=pos.id,
        ticker=pos.ticker,
        option_type=pos.option_type,
        strike=pos.strike,
        expiry=pos.expiry,
        contracts=pos.contracts,
        mark=mark,
        current_value=current_value,
        entry_value=entry_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        dte=dte,
        greeks=greeks,
        iv=mkt.iv,
        progress_to_target=progress_to_target,
        progress_to_stop=progress_to_stop,
        market_data=mkt,
    )


def value_shares(
    pos: SharePosition,
    mkt: SpotMarketData,
) -> ShareValuation:
    mark = mkt.mark
    current_value = mark * pos.contracts
    entry_value = pos.entry_price * pos.contracts
    unrealized_pnl = current_value - entry_value
    unrealized_pnl_pct = (unrealized_pnl / entry_value * 100.0) if entry_value else 0.0

    progress_to_target = (
        _progress(mark, pos.entry_price, pos.target_price)
        if pos.target_price is not None
        else None
    )
    progress_to_stop = (
        _progress(mark, pos.entry_price, pos.stop_price)
        if pos.stop_price is not None
        else None
    )

    return ShareValuation(
        position_id=pos.id,
        ticker=pos.ticker,
        contracts=pos.contracts,
        mark=mark,
        current_value=current_value,
        entry_value=entry_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        progress_to_target=progress_to_target,
        progress_to_stop=progress_to_stop,
        market_data=mkt,
    )
