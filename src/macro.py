"""
Macro gate — Layer 3a.

Computes a composite macro score (0-100) from four components:
  VIX level percentile, VIX/VIX3M term structure,
  sector breadth (% of basket above 200-day MA), and credit (HYG/TLT ratio).

Usage:
    from src.macro import compute_macro, MacroResult
    result = compute_macro()
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import numpy as np
import yfinance as yf

import config


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MacroResult:
    composite_score: float          # 0-100; higher = more risk-on
    regime: str                     # "RISK-ON" | "CAUTION" | "RISK-OFF"

    vix_level: float | None
    vix_percentile: float | None    # VIX rank vs 1y history (low VIX = high score)
    vix_score: float | None

    vix3m_level: float | None
    term_ratio: float | None        # VIX / VIX3M  (<1 = contango = good)
    term_score: float | None

    breadth_pct: float | None       # % of basket tickers above 200d MA
    breadth_score: float | None

    credit_percentile: float | None # HYG/TLT ratio rank vs 1y history
    credit_score: float | None

    weights: dict[str, float]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_macro() -> MacroResult:
    vix_level, vix_pct, vix_score = _vix_score()
    vix3m, ratio, term_score     = _term_score(vix_level)
    breadth_pct, breadth_score   = _breadth_score()
    credit_pct, credit_score     = _credit_score()

    weights = {
        "vix":     config.MACRO_VIX_WEIGHT,
        "term":    config.MACRO_TERM_WEIGHT,
        "breadth": config.MACRO_BREADTH_WEIGHT,
        "credit":  config.MACRO_CREDIT_WEIGHT,
    }

    # Weighted average; skip any component that failed to fetch
    total_w = 0.0
    composite = 0.0
    for score, wt in [
        (vix_score,     weights["vix"]),
        (term_score,    weights["term"]),
        (breadth_score, weights["breadth"]),
        (credit_score,  weights["credit"]),
    ]:
        if score is not None:
            composite += score * wt
            total_w += wt

    composite = composite / total_w if total_w > 0 else 50.0

    if composite <= config.MACRO_RISK_OFF_THRESHOLD:
        regime = "RISK-OFF"
    elif composite <= config.MACRO_CAUTION_THRESHOLD:
        regime = "CAUTION"
    else:
        regime = "RISK-ON"

    return MacroResult(
        composite_score=round(composite, 1),
        regime=regime,
        vix_level=vix_level,
        vix_percentile=vix_pct,
        vix_score=vix_score,
        vix3m_level=vix3m,
        term_ratio=ratio,
        term_score=term_score,
        breadth_pct=breadth_pct,
        breadth_score=breadth_score,
        credit_percentile=credit_pct,
        credit_score=credit_score,
        weights=weights,
    )


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def _vix_score() -> tuple[float | None, float | None, float | None]:
    """Score based on where today's VIX sits vs its 1-year distribution.
    Low VIX = low fear = high score."""
    try:
        df = yf.download("^VIX", period=f"{config.MACRO_LOOKBACK_DAYS}d",
                         interval="1d", auto_adjust=False, progress=False)
        closes = df["Close"].dropna()
        if len(closes) < 20:
            return None, None, None
        current = float(closes.iloc[-1])
        pct = float(np.mean(closes.values < current) * 100)
        score = 100.0 - pct   # low VIX percentile → high score
        return round(current, 2), round(pct, 1), round(score, 1)
    except Exception:
        return None, None, None


def _term_score(vix: float | None) -> tuple[float | None, float | None, float | None]:
    """Score based on VIX / VIX3M ratio.
    Contango (ratio < 1) = normal = high score; backwardation = stressed = low score."""
    if vix is None:
        return None, None, None
    try:
        df3m = yf.download("^VIX3M", period="5d", interval="1d",
                           auto_adjust=False, progress=False)
        closes = df3m["Close"].dropna()
        if closes.empty:
            return None, None, None
        vix3m = float(closes.iloc[-1])
        ratio = vix / vix3m
        # ratio=0.7 → score=100, ratio=1.0 → score=50, ratio=1.3 → score=0
        score = max(0.0, min(100.0, (1.3 - ratio) / 0.6 * 100.0))
        return round(vix3m, 2), round(ratio, 3), round(score, 1)
    except Exception:
        return None, None, None


def _breadth_score() -> tuple[float | None, float | None]:
    """% of sector ETF basket trading above their 200-day MA → score 0-100."""
    basket = config.MACRO_BREADTH_BASKET
    try:
        df = yf.download(basket, period="220d", interval="1d",
                         auto_adjust=True, progress=False)
        # Handle multi/single-ticker column shape
        if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, "levels"):
            closes = df["Close"]
        else:
            closes = df[["Close"]]
            closes.columns = basket[:1]

        above = 0
        total = 0
        for ticker in basket:
            if ticker not in closes.columns:
                continue
            series = closes[ticker].dropna()
            if len(series) < 200:
                continue
            ma200 = float(series.iloc[-200:].mean())
            current = float(series.iloc[-1])
            above += int(current > ma200)
            total += 1

        if total == 0:
            return None, None
        pct = above / total * 100.0
        return round(pct, 1), round(pct, 1)   # score == pct directly
    except Exception:
        return None, None


def _credit_score() -> tuple[float | None, float | None]:
    """HYG/TLT ratio percentile vs 1y history.
    High ratio = tight credit spreads = risk-on = high score."""
    try:
        df = yf.download(["HYG", "TLT"], period=f"{config.MACRO_LOOKBACK_DAYS}d",
                         interval="1d", auto_adjust=True, progress=False)
        # Multi-ticker shape: columns are (Price, Ticker)
        if hasattr(df.columns, "levels"):
            hyg = df["Close"]["HYG"].dropna()
            tlt = df["Close"]["TLT"].dropna()
        else:
            return None, None

        ratio = (hyg / tlt).dropna()
        if len(ratio) < 20:
            return None, None
        current_ratio = float(ratio.iloc[-1])
        pct = float(np.mean(ratio.values < current_ratio) * 100)
        return round(pct, 1), round(pct, 1)   # score == percentile
    except Exception:
        return None, None
