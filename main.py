#!/usr/bin/env python3
"""
Portfolio monitor entry point.

Usage:
    python main.py                        # run for today
    python main.py --asof 2026-06-20      # stamp run with a specific date
    python main.py --rate 0.05            # override risk-free rate
    python main.py --positions my.json    # use a different positions file
    python main.py --quiet                # suppress per-step logging
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import date

# Load .env before anything else so API keys are available
def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        pass

_load_dotenv()

# Force UTF-8 on Windows terminals that default to cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from src.models import OptionValuation, ShareValuation
from src.portfolio import run_portfolio, load_positions
from src.analytics import compute_analytics, PortfolioAnalytics
from src.macro import compute_macro, MacroResult
from src.news import analyze_ticker_news, NewsResult
from src.diff import compute_chain_diffs
from src.alerts import generate_alerts, load_prior_iv, Alert
from src import snapshot as snap
from src import notifier


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_DIM    = "\033[2m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


def _color_pnl(val: float) -> str:
    c = _GREEN if val >= 0 else _RED
    sign = "+" if val >= 0 else ""
    return f"{c}{sign}{val:,.2f}{_RESET}"


def _color_pct(val: float) -> str:
    c = _GREEN if val >= 0 else _RED
    sign = "+" if val >= 0 else ""
    return f"{c}{sign}{val:.1f}%{_RESET}"


def _progress_bar(pct: float | None, width: int = 20) -> str:
    if pct is None:
        return "  n/a"
    clamped = max(0.0, min(100.0, pct))
    filled = int(clamped / 100.0 * width)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {pct:6.1f}%"


def print_valuation(v: OptionValuation | ShareValuation, idx: int) -> None:
    sep = _DIM + "─" * 70 + _RESET

    if isinstance(v, OptionValuation):
        flag = v.option_type.upper()
        header = (
            f"{_BOLD}{_CYAN}[{idx}] {v.ticker}  "
            f"{flag} ${v.strike:.0f}  exp {v.expiry}  "
            f"({v.dte}d DTE){_RESET}"
        )
        print(header)
        print(
            f"  Mark        {v.mark:>10.3f}    "
            f"IV {v.iv*100:.1f}%    "
            f"Contracts {v.contracts}"
        )
        print(
            f"  Value       {v.current_value:>10,.2f}    "
            f"Entry {v.entry_value:,.2f}"
        )
        print(
            f"  P&L         {_color_pnl(v.unrealized_pnl):>10}    "
            f"{_color_pct(v.unrealized_pnl_pct)}"
        )
        g = v.greeks
        print(
            f"  Greeks      d={g.delta:+.4f}   "
            f"G={g.gamma:.5f}   "
            f"T={g.theta:+.4f}/day   "
            f"V={g.vega:.4f}/1%IV"
        )
        print(f"  > Target    {_progress_bar(v.progress_to_target)}")
        print(f"  > Stop      {_progress_bar(v.progress_to_stop)}")

    else:  # ShareValuation
        header = f"{_BOLD}{_CYAN}[{idx}] {v.ticker}  {v.contracts} shares{_RESET}"
        print(header)
        print(
            f"  Mark        {v.mark:>10.3f}    "
            f"Shares {v.contracts}"
        )
        print(
            f"  Value       {v.current_value:>10,.2f}    "
            f"Entry {v.entry_value:,.2f}"
        )
        print(
            f"  P&L         {_color_pnl(v.unrealized_pnl):>10}    "
            f"{_color_pct(v.unrealized_pnl_pct)}"
        )
        print(f"  > Target    {_progress_bar(v.progress_to_target)}")
        print(f"  > Stop      {_progress_bar(v.progress_to_stop)}")

    print(sep)


_SEV_COLOR = {"high": _RED, "warn": _YELLOW, "info": _CYAN}
_SEV_ICON  = {"high": "[!!]", "warn": "[! ]", "info": "[ i]"}


def print_alerts(alerts: list[Alert]) -> None:
    if not alerts:
        print(f"\n  {_GREEN}No alerts.{_RESET}\n")
        return

    W = 70
    div = _DIM + "=" * W + _RESET
    high  = [a for a in alerts if a.severity == "high"]
    warn  = [a for a in alerts if a.severity == "warn"]
    info  = [a for a in alerts if a.severity == "info"]

    print(f"\n{_BOLD}{'ALERTS':^{W}}{_RESET}")
    print(div)

    for group, label in [(high, "HIGH"), (warn, "WARN"), (info, "INFO")]:
        if not group:
            continue
        c = _SEV_COLOR[group[0].severity]
        print(f"\n{c}{_BOLD}{label}{_RESET}")
        for a in group:
            icon = _SEV_COLOR[a.severity] + _SEV_ICON[a.severity] + _RESET
            print(f"  {icon}  {a.message}")
            if a.detail:
                print(f"         {_DIM}{a.detail}{_RESET}")

    print(f"\n{div}\n")


def print_macro(m: MacroResult) -> None:
    W = 70
    div = _DIM + "=" * W + _RESET

    if m.regime == "RISK-ON":
        rc = _GREEN
    elif m.regime == "CAUTION":
        rc = _YELLOW
    else:
        rc = _RED

    print(f"\n{_BOLD}{'MACRO GATE':^{W}}{_RESET}")
    print(div)
    print(
        f"  Composite Score  {rc}{_BOLD}{m.composite_score:5.1f}{_RESET}  "
        f"Regime: {rc}{_BOLD}{m.regime}{_RESET}"
    )
    print()

    def _row(label: str, score: float | None, detail: str) -> None:
        if score is None:
            print(f"  {label:<20} {'n/a':>6}   {_DIM}{detail}{_RESET}")
        else:
            bar_w = 20
            filled = int(score / 100 * bar_w)
            bar = "#" * filled + "-" * (bar_w - filled)
            sc = _GREEN if score >= 60 else _YELLOW if score >= 35 else _RED
            print(f"  {label:<20} {sc}{score:5.1f}{_RESET}  [{bar}]  {_DIM}{detail}{_RESET}")

    _row("VIX level",      m.vix_score,
         f"VIX={m.vix_level}  pct={m.vix_percentile}%  (low VIX = good)" if m.vix_level else "fetch failed")
    _row("Term structure",  m.term_score,
         f"VIX3M={m.vix3m_level}  ratio={m.term_ratio}  (<1 = contango)" if m.term_ratio else "fetch failed")
    _row("Breadth",        m.breadth_score,
         f"{m.breadth_pct}% of ETFs above 200d MA" if m.breadth_pct is not None else "fetch failed")
    _row("Credit (HYG/TLT)", m.credit_score,
         f"ratio pct={m.credit_percentile}%  (high = tight spreads)" if m.credit_percentile is not None else "fetch failed")

    print(f"\n{div}\n")


def print_news(results: list[NewsResult]) -> None:
    if not results:
        return

    W = 70
    div = _DIM + "=" * W + _RESET
    thin = _DIM + "-" * W + _RESET

    print(f"\n{_BOLD}{'NEWS ANALYSIS (Claude)':^{W}}{_RESET}")
    print(div)

    _sent_color = {
        "bullish": _GREEN,
        "bearish": _RED,
        "mixed":   _YELLOW,
        "neutral": _RESET,
    }
    _flag_color = {
        "aligned":    _GREEN,
        "contrarian": _RED,
        "neutral":    _RESET,
        "no news":    _DIM,
    }

    for r in results:
        cached_tag = f"{_DIM}[cached]{_RESET}" if r.cached else ""
        sc = _sent_color.get(r.sentiment, _RESET)
        fc = _flag_color.get(r.position_flag, _RESET)
        print(
            f"\n  {_BOLD}{r.ticker}{_RESET}  "
            f"sentiment={sc}{r.sentiment}{_RESET}  "
            f"position={fc}{r.position_flag}{_RESET}  "
            f"headlines={r.headline_count}  {cached_tag}"
        )
        if r.summary:
            print(f"  {r.summary}")
        if r.key_drivers:
            drivers = "  •  ".join(r.key_drivers)
            print(f"  Drivers: {_DIM}{drivers}{_RESET}")
        print(f"  {thin}")

    print()


def print_analytics(ana: PortfolioAnalytics) -> None:
    W = 70
    div = _DIM + "=" * W + _RESET
    thin = _DIM + "-" * W + _RESET

    print(f"\n{_BOLD}{'PORTFOLIO ANALYTICS':^{W}}{_RESET}")
    print(div)

    # ── Allocation by ticker ────────────────────────────────────────────────
    print(f"\n{_BOLD}Allocation by Ticker{_RESET}")
    for entry in ana.allocations_by_ticker:
        bar_w = 30
        filled = int(entry.pct / 100 * bar_w)
        bar = "#" * filled + "-" * (bar_w - filled)
        print(f"  {entry.ticker:<6}  [{bar}] {entry.pct:5.1f}%   ${entry.value:>10,.2f}   {entry.sector}")

    # ── Allocation by sector ────────────────────────────────────────────────
    print(f"\n{_BOLD}Allocation by Sector{_RESET}")
    for sec in ana.allocations_by_sector:
        bar_w = 30
        filled = int(sec.pct / 100 * bar_w)
        bar = "#" * filled + "-" * (bar_w - filled)
        print(f"  {sec.sector:<28}  [{bar}] {sec.pct:5.1f}%   ${sec.value:>10,.2f}")

    # ── Concentration flags ─────────────────────────────────────────────────
    if ana.concentration_flags:
        print(f"\n{_BOLD}Concentration Flags{_RESET}")
        for flag in ana.concentration_flags:
            label = flag.kind.upper()
            print(
                f"  {_RED}[WARN]{_RESET} {label} {flag.name:<20}  "
                f"{flag.pct:.1f}% > cap {flag.cap:.0f}%"
            )
    else:
        print(f"\n  {_GREEN}No concentration flags.{_RESET}")

    print(f"\n{thin}")

    # ── Aggregate greeks ────────────────────────────────────────────────────
    g = ana.aggregate_greeks
    delta_c = _GREEN if g.net_delta_shares >= 0 else _RED
    theta_c = _RED   if g.total_theta_daily < 0 else _GREEN
    vega_c  = _GREEN if g.net_vega_per_pp >= 0 else _RED

    print(f"\n{_BOLD}Aggregate Greeks{_RESET}")
    print(f"  Net Delta       {delta_c}{g.net_delta_shares:+.2f} share-equivalents{_RESET}")
    print(f"  Daily Theta     {theta_c}{g.total_theta_daily:+.2f} $/day{_RESET}")
    print(f"  Net Vega        {vega_c}{g.net_vega_per_pp:+.2f} $ per 1pp IV move{_RESET}")

    print(f"\n{thin}")

    # ── IV environment ──────────────────────────────────────────────────────
    if ana.iv_stats:
        print(f"\n{_BOLD}IV Environment{_RESET}")
        hdr = f"  {'Position':<35} {'IV':>6}  {'Rank':>6}  {'Pct':>6}  {'Days':>5}  Status"
        print(_DIM + hdr + _RESET)
        for iv in ana.iv_stats:
            rank_s = f"{iv.iv_rank:5.1f}" if iv.iv_rank is not None else "  n/a"
            pct_s  = f"{iv.iv_percentile:5.1f}" if iv.iv_percentile is not None else "  n/a"
            if iv.status == "rich":
                sc = _RED
            elif iv.status == "cheap":
                sc = _GREEN
            elif iv.status == "building history":
                sc = _DIM
            else:
                sc = _RESET
            label = f"{sc}{iv.status}{_RESET}"
            print(
                f"  {iv.position_id:<35} {iv.current_iv*100:5.1f}%  "
                f"{rank_s}  {pct_s}  {iv.history_days:5d}  {label}"
            )

    # ── DTE flags ───────────────────────────────────────────────────────────
    if ana.dte_flags:
        print(f"\n{_BOLD}Upcoming Expiries  (<= {ana.dte_flags[0].threshold}d){_RESET}")
        for flag in ana.dte_flags:
            urgency = _RED if flag.dte <= 14 else _YELLOW if flag.dte <= 30 else _RESET
            print(
                f"  {urgency}{flag.position_id:<35}  {flag.dte:3d} DTE  "
                f"(exp {flag.expiry}){_RESET}"
            )
    else:
        print(f"\n  {_GREEN}No near-expiry positions (<= {config.DTE_WARNING_THRESHOLD}d).{_RESET}")

    print(f"\n{div}\n")


def print_summary(valuations: list) -> None:
    total_value  = sum(v.current_value for v in valuations)
    total_entry  = sum(v.entry_value   for v in valuations)
    total_pnl    = total_value - total_entry
    total_pnl_pct = total_pnl / total_entry * 100 if total_entry else 0.0

    print(f"\n{_BOLD}Portfolio Summary{_RESET}")
    print(f"  Positions     {len(valuations)}")
    print(f"  Total Value   ${total_value:>12,.2f}")
    print(f"  Total Entry   ${total_entry:>12,.2f}")
    print(f"  Net P&L       {_color_pnl(total_pnl)}  ({_color_pct(total_pnl_pct)})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Options + equity portfolio monitor")
    p.add_argument(
        "--asof",
        metavar="YYYY-MM-DD",
        default=date.today().isoformat(),
        help="Stamp date for storage / diffing (default: today)",
    )
    p.add_argument(
        "--rate",
        type=float,
        default=config.RISK_FREE_RATE,
        metavar="FLOAT",
        help=f"Annual risk-free rate (default {config.RISK_FREE_RATE})",
    )
    p.add_argument(
        "--positions",
        default=config.POSITIONS_FILE,
        metavar="FILE",
        help=f"Path to positions JSON (default {config.POSITIONS_FILE})",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-step progress output",
    )
    p.add_argument(
        "--skip-news",
        action="store_true",
        help="Skip Claude news analysis (saves API cost)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    print(f"{_BOLD}Portfolio Monitor — as-of {args.asof}{_RESET}")
    print(f"  Risk-free rate : {args.rate*100:.2f}%")
    print(f"  Positions file : {args.positions}")
    print()

    # Load positions separately so alert generator has target/stop prices
    positions = load_positions(args.positions)
    pos_map = {p.id: p for p in positions}

    valuations = run_portfolio(
        as_of=args.asof,
        positions_file=args.positions,
        risk_free_rate=args.rate,
        verbose=not args.quiet,
    )

    print()
    for i, v in enumerate(valuations, 1):
        print_valuation(v, i)

    if not valuations:
        return

    print_summary(valuations)

    conn = snap.get_connection()

    # ── Analytics layer ────────────────────────────────────────────────────
    analytics = compute_analytics(valuations, args.asof, conn)
    snap.upsert_analytics(conn, analytics, args.asof)
    print_analytics(analytics)

    # ── Chain diff ─────────────────────────────────────────────────────────
    if not args.quiet:
        print("  [diff] comparing chain vs prior run…")
    chain_diffs = compute_chain_diffs(conn, valuations, args.asof)

    # ── Macro gate ─────────────────────────────────────────────────────────
    if not args.quiet:
        print("  [macro] fetching market data…")
    macro = compute_macro()
    snap.upsert_macro(conn, macro, args.asof)
    print_macro(macro)

    # ── News analysis ──────────────────────────────────────────────────────
    news_results: list[NewsResult] = []
    if not args.skip_news:
        tickers = sorted({v.ticker for v in valuations})
        for ticker in tickers:
            pos_parts = []
            for v in valuations:
                if v.ticker != ticker:
                    continue
                if isinstance(v, OptionValuation):
                    pos_parts.append(
                        f"{ticker} {v.option_type.upper()} ${v.strike:.0f} "
                        f"exp {v.expiry} ({v.contracts} contracts, "
                        f"entry ${v.entry_value/max(v.contracts*100,1):.2f}/share)"
                    )
                else:
                    pos_parts.append(f"{ticker} {v.contracts} shares")
            position_ctx = "; ".join(pos_parts) or ticker
            if not args.quiet:
                print(f"  [news] analyzing {ticker}…")
            news_results.append(analyze_ticker_news(conn, ticker, position_ctx, args.asof))

        print_news(news_results)

    # ── Alerts ─────────────────────────────────────────────────────────────
    prior_iv = load_prior_iv(conn, args.asof)
    alerts = generate_alerts(valuations, pos_map, chain_diffs, news_results, prior_iv, args.asof)
    snap.upsert_alerts(conn, alerts, args.asof)
    print_alerts(alerts)

    # ── Notifier ───────────────────────────────────────────────────────────
    notifier.send_daily_emails(alerts, valuations, analytics,
                               chain_diffs, news_results, macro, args.asof)

    conn.close()


if __name__ == "__main__":
    main()
