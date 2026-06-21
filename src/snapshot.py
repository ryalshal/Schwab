"""
Persistence layer — JSON files + SQLite.

JSON snapshots : snapshots/TICKER_YYYY-MM-DD.json
SQLite tables  : option_chains, position_valuations
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import config
from src.models import OptionValuation, ShareValuation, Valuation
# analytics imported lazily below to avoid circular import


# ---------------------------------------------------------------------------
# JSON snapshots
# ---------------------------------------------------------------------------

def save_chain_snapshot(ticker: str, chain: dict, as_of: str) -> str:
    """Write full chain dict to snapshots/TICKER_YYYY-MM-DD.json. Returns path."""
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)
    path = os.path.join(config.SNAPSHOTS_DIR, f"{ticker}_{as_of}.json")
    payload = {"as_of": as_of, "fetched_at": _now_iso(), **chain}
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return path


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS option_chains (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT    NOT NULL,
            as_of_date      TEXT    NOT NULL,
            expiry          TEXT    NOT NULL,
            option_type     TEXT    NOT NULL,
            strike          REAL    NOT NULL,
            bid             REAL,
            ask             REAL,
            last_price      REAL,
            mark            REAL,
            iv              REAL,
            volume          INTEGER,
            open_interest   INTEGER,
            contract_symbol TEXT,
            in_the_money    INTEGER,
            fetched_at      TEXT,
            UNIQUE(ticker, as_of_date, expiry, option_type, strike)
        );

        CREATE TABLE IF NOT EXISTS portfolio_analytics (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date              TEXT    NOT NULL UNIQUE,
            total_value             REAL,
            net_delta_shares        REAL,
            total_theta_daily       REAL,
            net_vega_per_pp         REAL,
            allocation_by_ticker    TEXT,   -- JSON
            allocation_by_sector    TEXT,   -- JSON
            concentration_flags     TEXT,   -- JSON
            iv_stats                TEXT,   -- JSON
            dte_flags               TEXT,   -- JSON
            created_at              TEXT
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date  TEXT    NOT NULL,
            position_id TEXT,
            ticker      TEXT,
            kind        TEXT    NOT NULL,
            severity    TEXT    NOT NULL,
            message     TEXT    NOT NULL,
            detail      TEXT,
            created_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS macro_scores (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date          TEXT    NOT NULL UNIQUE,
            composite_score     REAL,
            regime              TEXT,
            vix_level           REAL,
            vix_percentile      REAL,
            vix_score           REAL,
            vix3m_level         REAL,
            term_ratio          REAL,
            term_score          REAL,
            breadth_pct         REAL,
            breadth_score       REAL,
            credit_percentile   REAL,
            credit_score        REAL,
            weights             TEXT,
            created_at          TEXT
        );

        CREATE TABLE IF NOT EXISTS news_analyses (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date          TEXT    NOT NULL,
            ticker              TEXT    NOT NULL,
            news_window_days    INTEGER,
            headline_count      INTEGER,
            summary             TEXT,
            sentiment           TEXT,
            key_drivers         TEXT,
            position_flag       TEXT,
            model               TEXT,
            created_at          TEXT,
            UNIQUE(as_of_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS position_valuations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of_date          TEXT    NOT NULL,
            position_id         TEXT    NOT NULL,
            ticker              TEXT    NOT NULL,
            asset_type          TEXT    NOT NULL,
            contracts           INTEGER,
            mark                REAL,
            current_value       REAL,
            entry_value         REAL,
            unrealized_pnl      REAL,
            unrealized_pnl_pct  REAL,
            dte                 INTEGER,
            iv                  REAL,
            delta               REAL,
            gamma               REAL,
            theta               REAL,
            vega                REAL,
            progress_to_target  REAL,
            progress_to_stop    REAL,
            created_at          TEXT,
            UNIQUE(as_of_date, position_id)
        );
    """)
    conn.commit()


def upsert_chain(conn: sqlite3.Connection, ticker: str, chain: dict, as_of: str) -> None:
    """Flatten a full-chain dict and upsert every row into option_chains."""
    now = _now_iso()
    rows: list[tuple] = []

    for expiry, sides in chain.get("expiries", {}).items():
        for opt_type in ("calls", "puts"):
            for rec in sides.get(opt_type, []):
                rows.append((
                    ticker,
                    as_of,
                    expiry,
                    opt_type.rstrip("s"),   # "call" / "put"
                    rec.get("strike"),
                    rec.get("bid"),
                    rec.get("ask"),
                    rec.get("lastPrice"),
                    rec.get("mark"),
                    rec.get("impliedVolatility"),
                    rec.get("volume"),
                    rec.get("openInterest"),
                    rec.get("contractSymbol"),
                    1 if rec.get("inTheMoney") else 0,
                    now,
                ))

    conn.executemany(
        """
        INSERT INTO option_chains
            (ticker, as_of_date, expiry, option_type, strike,
             bid, ask, last_price, mark, iv, volume, open_interest,
             contract_symbol, in_the_money, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker, as_of_date, expiry, option_type, strike)
        DO UPDATE SET
            bid=excluded.bid, ask=excluded.ask, last_price=excluded.last_price,
            mark=excluded.mark, iv=excluded.iv, volume=excluded.volume,
            open_interest=excluded.open_interest, fetched_at=excluded.fetched_at
        """,
        rows,
    )
    conn.commit()


def upsert_valuation(conn: sqlite3.Connection, v: Valuation, as_of: str) -> None:
    now = _now_iso()
    if isinstance(v, OptionValuation):
        row = (
            as_of, v.position_id, v.ticker, "option", v.contracts,
            v.mark, v.current_value, v.entry_value,
            v.unrealized_pnl, v.unrealized_pnl_pct,
            v.dte, v.iv,
            v.greeks.delta, v.greeks.gamma, v.greeks.theta, v.greeks.vega,
            v.progress_to_target, v.progress_to_stop, now,
        )
    else:
        row = (
            as_of, v.position_id, v.ticker, "shares", v.contracts,
            v.mark, v.current_value, v.entry_value,
            v.unrealized_pnl, v.unrealized_pnl_pct,
            None, None,
            None, None, None, None,
            v.progress_to_target, v.progress_to_stop, now,
        )

    conn.execute(
        """
        INSERT INTO position_valuations
            (as_of_date, position_id, ticker, asset_type, contracts,
             mark, current_value, entry_value, unrealized_pnl, unrealized_pnl_pct,
             dte, iv, delta, gamma, theta, vega,
             progress_to_target, progress_to_stop, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of_date, position_id)
        DO UPDATE SET
            mark=excluded.mark, current_value=excluded.current_value,
            unrealized_pnl=excluded.unrealized_pnl,
            unrealized_pnl_pct=excluded.unrealized_pnl_pct,
            iv=excluded.iv, delta=excluded.delta, gamma=excluded.gamma,
            theta=excluded.theta, vega=excluded.vega,
            progress_to_target=excluded.progress_to_target,
            progress_to_stop=excluded.progress_to_stop,
            created_at=excluded.created_at
        """,
        row,
    )
    conn.commit()


def upsert_analytics(conn: sqlite3.Connection, analytics: Any, as_of: str) -> None:
    """Persist a PortfolioAnalytics result to the portfolio_analytics table."""
    from dataclasses import asdict

    def _serial(obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: _serial(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [_serial(i) for i in obj]
        return obj

    ag = analytics.aggregate_greeks

    conn.execute(
        """
        INSERT INTO portfolio_analytics
            (as_of_date, total_value,
             net_delta_shares, total_theta_daily, net_vega_per_pp,
             allocation_by_ticker, allocation_by_sector, concentration_flags,
             iv_stats, dte_flags, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of_date) DO UPDATE SET
            total_value=excluded.total_value,
            net_delta_shares=excluded.net_delta_shares,
            total_theta_daily=excluded.total_theta_daily,
            net_vega_per_pp=excluded.net_vega_per_pp,
            allocation_by_ticker=excluded.allocation_by_ticker,
            allocation_by_sector=excluded.allocation_by_sector,
            concentration_flags=excluded.concentration_flags,
            iv_stats=excluded.iv_stats,
            dte_flags=excluded.dte_flags,
            created_at=excluded.created_at
        """,
        (
            as_of,
            analytics.total_value,
            ag.net_delta_shares,
            ag.total_theta_daily,
            ag.net_vega_per_pp,
            json.dumps(_serial(analytics.allocations_by_ticker)),
            json.dumps(_serial(analytics.allocations_by_sector)),
            json.dumps(_serial(analytics.concentration_flags)),
            json.dumps(_serial(analytics.iv_stats)),
            json.dumps(_serial(analytics.dte_flags)),
            _now_iso(),
        ),
    )
    conn.commit()


def upsert_alerts(conn: sqlite3.Connection, alerts: list, as_of: str) -> None:
    """Replace all alerts for as_of with the current run's result."""
    conn.execute("DELETE FROM alerts WHERE as_of_date = ?", (as_of,))
    rows = [
        (as_of, a.position_id, a.ticker, a.kind, a.severity,
         a.message, a.detail, _now_iso())
        for a in alerts
    ]
    conn.executemany(
        """
        INSERT INTO alerts
            (as_of_date, position_id, ticker, kind, severity, message, detail, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()


def load_alerts(conn: sqlite3.Connection, as_of: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM alerts WHERE as_of_date = ? ORDER BY severity, id",
        (as_of,),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_macro(conn: sqlite3.Connection, macro: Any, as_of: str) -> None:
    """Persist a MacroResult to macro_scores."""
    conn.execute(
        """
        INSERT INTO macro_scores
            (as_of_date, composite_score, regime,
             vix_level, vix_percentile, vix_score,
             vix3m_level, term_ratio, term_score,
             breadth_pct, breadth_score,
             credit_percentile, credit_score,
             weights, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of_date) DO UPDATE SET
            composite_score=excluded.composite_score,
            regime=excluded.regime,
            vix_level=excluded.vix_level,
            vix_percentile=excluded.vix_percentile,
            vix_score=excluded.vix_score,
            vix3m_level=excluded.vix3m_level,
            term_ratio=excluded.term_ratio,
            term_score=excluded.term_score,
            breadth_pct=excluded.breadth_pct,
            breadth_score=excluded.breadth_score,
            credit_percentile=excluded.credit_percentile,
            credit_score=excluded.credit_score,
            weights=excluded.weights,
            created_at=excluded.created_at
        """,
        (
            as_of,
            macro.composite_score, macro.regime,
            macro.vix_level, macro.vix_percentile, macro.vix_score,
            macro.vix3m_level, macro.term_ratio, macro.term_score,
            macro.breadth_pct, macro.breadth_score,
            macro.credit_percentile, macro.credit_score,
            json.dumps(macro.weights),
            _now_iso(),
        ),
    )
    conn.commit()


def load_prior_chain(ticker: str, as_of: str, conn: sqlite3.Connection) -> list[dict]:
    """Return chain rows from the most recent run before *as_of* for diffing."""
    cur = conn.execute(
        """
        SELECT * FROM option_chains
        WHERE ticker = ? AND as_of_date < ?
        ORDER BY as_of_date DESC, expiry, option_type, strike
        LIMIT 2000
        """,
        (ticker, as_of),
    )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
