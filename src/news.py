"""
News analysis — Layer 3b.

Fetches recent headlines via yfinance .news, sends them to Claude (haiku by
default), and returns a structured sentiment + position-flag result.

Per-ticker per-day caching in SQLite avoids re-billing on reruns.

Usage:
    from src.news import analyze_ticker_news, NewsResult
    result = analyze_ticker_news(conn, ticker, position_context, as_of)
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import yfinance as yf
import anthropic

import config


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class NewsResult:
    ticker: str
    as_of_date: str
    headline_count: int
    summary: str
    sentiment: str             # "bullish" | "bearish" | "neutral" | "mixed"
    key_drivers: list[str]
    position_flag: str         # "aligned" | "contrarian" | "neutral" | "no news"
    model: str
    cached: bool


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_ticker_news(
    conn: sqlite3.Connection,
    ticker: str,
    position_context: str,
    as_of: str,
    model: str = config.NEWS_MODEL,
    window_days: int = config.NEWS_WINDOW_DAYS,
    max_headlines: int = config.NEWS_MAX_HEADLINES,
) -> NewsResult:
    # Check cache first
    cached = _load_cache(conn, ticker, as_of)
    if cached:
        return cached

    # Fetch headlines
    headlines = _fetch_headlines(ticker, window_days, max_headlines)

    if not headlines:
        result = NewsResult(
            ticker=ticker,
            as_of_date=as_of,
            headline_count=0,
            summary="No recent news found.",
            sentiment="neutral",
            key_drivers=[],
            position_flag="no news",
            model=model,
            cached=False,
        )
        _save_cache(conn, result)
        return result

    # Call Claude
    result = _call_claude(ticker, headlines, position_context, as_of, model)
    _save_cache(conn, result)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_headlines(ticker: str, window_days: int, max_count: int) -> list[str]:
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=window_days)).timestamp()
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
    except Exception:
        return []

    lines = []
    for item in news:
        pub_ts = item.get("providerPublishTime", 0)
        if pub_ts < cutoff_ts:
            continue
        title = item.get("title", "").strip()
        publisher = item.get("publisher", "")
        pub_date = datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if title:
            lines.append(f"{title} ({publisher}, {pub_date})")
        if len(lines) >= max_count:
            break
    return lines


def _call_claude(
    ticker: str,
    headlines: list[str],
    position_context: str,
    as_of: str,
    model: str,
) -> NewsResult:
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    prompt = f"""You are a financial analyst providing objective market context for a portfolio manager.

Ticker: {ticker}
As of: {as_of}
Recent headlines ({len(headlines)} articles, last {config.NEWS_WINDOW_DAYS} days):

{numbered}

Held position: {position_context}

Analyze these headlines and return ONLY valid JSON (no markdown, no explanation) with exactly these fields:
{{
  "summary": "2-3 sentence summary of the key news themes",
  "sentiment": "bullish" | "bearish" | "neutral" | "mixed",
  "key_drivers": ["driver 1", "driver 2", "driver 3"],
  "position_flag": "aligned" | "contrarian" | "neutral"
}}

position_flag rules:
- "aligned": news supports the direction of the held position
- "contrarian": news works against the held position
- "neutral": news has no clear directional implication for the position"""

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=512,
        system="You are a financial analyst. Return only valid JSON when asked.",
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if model added them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "summary": raw[:300],
            "sentiment": "neutral",
            "key_drivers": [],
            "position_flag": "neutral",
        }

    return NewsResult(
        ticker=ticker,
        as_of_date=as_of,
        headline_count=len(headlines),
        summary=data.get("summary", ""),
        sentiment=data.get("sentiment", "neutral"),
        key_drivers=data.get("key_drivers", []),
        position_flag=data.get("position_flag", "neutral"),
        model=model,
        cached=False,
    )


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def _load_cache(conn: sqlite3.Connection, ticker: str, as_of: str) -> NewsResult | None:
    row = conn.execute(
        "SELECT * FROM news_analyses WHERE as_of_date = ? AND ticker = ?",
        (as_of, ticker),
    ).fetchone()
    if row is None:
        return None
    return NewsResult(
        ticker=row["ticker"],
        as_of_date=row["as_of_date"],
        headline_count=row["headline_count"],
        summary=row["summary"],
        sentiment=row["sentiment"],
        key_drivers=json.loads(row["key_drivers"] or "[]"),
        position_flag=row["position_flag"],
        model=row["model"],
        cached=True,
    )


def _save_cache(conn: sqlite3.Connection, r: NewsResult) -> None:
    conn.execute(
        """
        INSERT INTO news_analyses
            (as_of_date, ticker, news_window_days, headline_count,
             summary, sentiment, key_drivers, position_flag, model, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(as_of_date, ticker) DO UPDATE SET
            headline_count=excluded.headline_count,
            summary=excluded.summary,
            sentiment=excluded.sentiment,
            key_drivers=excluded.key_drivers,
            position_flag=excluded.position_flag,
            model=excluded.model,
            created_at=excluded.created_at
        """,
        (
            r.as_of_date, r.ticker, config.NEWS_WINDOW_DAYS, r.headline_count,
            r.summary, r.sentiment, json.dumps(r.key_drivers),
            r.position_flag, r.model,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
