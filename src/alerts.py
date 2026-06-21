"""
Condition alerts — Layer 4b.

Generates alerts from valuations, chain diffs, and news results.
Surfaces facts only — never buy/sell recommendations.

Kinds and severities:
  target_hit   (high)  — mark crossed target_price
  stop_hit     (high)  — mark crossed stop_price
  target_near  (info)  — within ALERT_TARGET_NEAR_PCT of target
  iv_change    (warn)  — IV moved >= ALERT_IV_CHANGE_PCT vs prior snapshot
  new_strikes  (info)  — new strike listed within band of a held strike
  new_expiry   (info)  — new expiry listed on chain
  news_flag    (warn)  — Claude flagged news as contrarian to position

Usage:
    from src.alerts import generate_alerts, load_prior_iv
    prior_iv = load_prior_iv(conn, as_of)
    alerts = generate_alerts(valuations, pos_map, chain_diffs, news_results, prior_iv, as_of)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from src.models import OptionValuation, ShareValuation
from src.diff import ChainDiff
import config


@dataclass
class Alert:
    kind: str        # see module docstring
    severity: str    # "high" | "warn" | "info"
    position_id: str
    ticker: str
    message: str
    detail: Optional[str]
    as_of: str


def generate_alerts(
    valuations: list,
    pos_map: dict,      # position_id → Position (OptionPosition | SharePosition)
    chain_diffs: list[ChainDiff],
    news_results: list,
    prior_iv_map: dict[str, float],   # position_id → prior IV
    as_of: str,
) -> list[Alert]:
    alerts: list[Alert] = []

    for v in valuations:
        pos = pos_map.get(v.position_id)

        if isinstance(v, OptionValuation):
            flag = v.option_type.upper()
            desc = f"{v.ticker} {flag}s ${v.strike:.0f} {v.expiry}"
            pnl_detail = f"P&L {v.unrealized_pnl:+,.2f} ({v.unrealized_pnl_pct:+.1f}%)"

            if pos and pos.target_price is not None and v.mark >= pos.target_price:
                alerts.append(Alert(
                    kind="target_hit", severity="high",
                    position_id=v.position_id, ticker=v.ticker,
                    message=f"{desc} hit your target level — mark {v.mark:.2f} ≥ target {pos.target_price:.2f}",
                    detail=pnl_detail, as_of=as_of,
                ))
            elif pos and pos.stop_price is not None and v.mark <= pos.stop_price:
                alerts.append(Alert(
                    kind="stop_hit", severity="high",
                    position_id=v.position_id, ticker=v.ticker,
                    message=f"{desc} hit your stop level — mark {v.mark:.2f} ≤ stop {pos.stop_price:.2f}",
                    detail=pnl_detail, as_of=as_of,
                ))
            elif (v.progress_to_target is not None
                  and v.progress_to_target >= config.ALERT_TARGET_NEAR_PCT * 100
                  and v.progress_to_target < 100):
                alerts.append(Alert(
                    kind="target_near", severity="info",
                    position_id=v.position_id, ticker=v.ticker,
                    message=f"{desc} is {v.progress_to_target:.0f}% of the way to your target",
                    detail=(f"mark {v.mark:.2f}  target {pos.target_price:.2f}"
                            if pos and pos.target_price else None),
                    as_of=as_of,
                ))

            prior_iv = prior_iv_map.get(v.position_id)
            if prior_iv and prior_iv > 0:
                chg = abs(v.iv - prior_iv) / prior_iv
                if chg >= config.ALERT_IV_CHANGE_PCT:
                    direction = "up" if v.iv > prior_iv else "down"
                    alerts.append(Alert(
                        kind="iv_change", severity="warn",
                        position_id=v.position_id, ticker=v.ticker,
                        message=(f"{desc} IV moved {chg*100:.0f}% {direction} — "
                                 f"was {prior_iv*100:.1f}%, now {v.iv*100:.1f}%"),
                        detail=None, as_of=as_of,
                    ))

        else:  # ShareValuation
            desc = f"{v.ticker} shares"
            pnl_detail = f"P&L {v.unrealized_pnl:+,.2f} ({v.unrealized_pnl_pct:+.1f}%)"

            if pos and pos.target_price is not None and v.mark >= pos.target_price:
                alerts.append(Alert(
                    kind="target_hit", severity="high",
                    position_id=v.position_id, ticker=v.ticker,
                    message=f"{desc} hit your target level — mark {v.mark:.2f} ≥ target {pos.target_price:.2f}",
                    detail=pnl_detail, as_of=as_of,
                ))
            elif pos and pos.stop_price is not None and v.mark <= pos.stop_price:
                alerts.append(Alert(
                    kind="stop_hit", severity="high",
                    position_id=v.position_id, ticker=v.ticker,
                    message=f"{desc} hit your stop level — mark {v.mark:.2f} ≤ stop {pos.stop_price:.2f}",
                    detail=pnl_detail, as_of=as_of,
                ))
            elif (v.progress_to_target is not None
                  and v.progress_to_target >= config.ALERT_TARGET_NEAR_PCT * 100
                  and v.progress_to_target < 100):
                alerts.append(Alert(
                    kind="target_near", severity="info",
                    position_id=v.position_id, ticker=v.ticker,
                    message=f"{desc} is {v.progress_to_target:.0f}% of the way to your target",
                    detail=(f"mark {v.mark:.2f}  target {pos.target_price:.2f}"
                            if pos and pos.target_price else None),
                    as_of=as_of,
                ))

    # Chain diffs
    for diff in chain_diffs:
        for expiry in diff.new_expiries:
            alerts.append(Alert(
                kind="new_expiry", severity="info",
                position_id="", ticker=diff.ticker,
                message=f"{diff.ticker} new expiry listed: {expiry}",
                detail=None, as_of=as_of,
            ))
        for ns in diff.new_strikes:
            iv_str = f"  IV {ns.iv*100:.1f}%" if ns.iv else ""
            detail = (f"bid {ns.bid}  ask {ns.ask}{iv_str}  "
                      f"vol {ns.volume}  OI {ns.oi}").strip()
            alerts.append(Alert(
                kind="new_strikes", severity="info",
                position_id="", ticker=diff.ticker,
                message=(f"{diff.ticker} new {ns.option_type} "
                         f"${ns.strike:.0f} {ns.expiry} listed"),
                detail=detail or None, as_of=as_of,
            ))

    # News flags (contrarian only — aligned/neutral don't need an alert)
    for nr in news_results:
        if nr.position_flag == "contrarian":
            driver = "  •  ".join(nr.key_drivers[:2]) if nr.key_drivers else None
            alerts.append(Alert(
                kind="news_flag", severity="warn",
                position_id="", ticker=nr.ticker,
                message=(f"{nr.ticker} news is contrarian to your position "
                         f"(sentiment: {nr.sentiment})"),
                detail=driver, as_of=as_of,
            ))

    return alerts


def load_prior_iv(conn: sqlite3.Connection, as_of: str) -> dict[str, float]:
    """Return {position_id: iv} from the most recent snapshot before as_of."""
    rows = conn.execute(
        """
        SELECT position_id, iv, as_of_date
        FROM position_valuations
        WHERE as_of_date < ? AND iv IS NOT NULL
        ORDER BY as_of_date DESC
        """,
        (as_of,),
    ).fetchall()
    seen: dict[str, float] = {}
    for row in rows:
        pid = row["position_id"]
        if pid not in seen:
            seen[pid] = float(row["iv"])
    return seen
