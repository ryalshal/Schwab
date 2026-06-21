"""
Portfolio Monitor Dashboard — Layer 4c.

Bloomberg-terminal–style single-page Streamlit app.

Run:
    streamlit run dashboard.py

The dashboard runs the full pipeline internally (cached 5 min).
Use the sidebar Refresh button to force a fresh pull.
"""
from __future__ import annotations

import math
import json
import os
from datetime import date, timedelta
from typing import Optional

# Load .env before importing modules that need API keys
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

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import config
from src.portfolio import run_portfolio, load_positions
from src.analytics import compute_analytics
from src.macro import compute_macro
from src.news import analyze_ticker_news, NewsResult
from src.diff import compute_chain_diffs
from src.alerts import generate_alerts, load_prior_iv, Alert
from src.models import OptionValuation, ShareValuation
from src import snapshot as snap

# ─── Page setup ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Portfolio Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  /* Dense monospace numbers throughout */
  .stDataFrame td, .stDataFrame th { font-family: 'Courier New', monospace; font-size: 12px; }
  /* Tight metric labels */
  [data-testid="metric-container"] { padding: 6px 10px; }
  [data-testid="stMetricLabel"]   { font-size: 11px; color: #8b949e; }
  [data-testid="stMetricValue"]   { font-size: 18px; font-weight: 700; }
  [data-testid="stMetricDelta"]   { font-size: 11px; }
  /* Alert boxes */
  .alert-high { background:#2d1215; border-left:3px solid #f85149;
                padding:6px 10px; margin:3px 0; border-radius:4px; font-size:13px; }
  .alert-warn { background:#2d2100; border-left:3px solid #e3b341;
                padding:6px 10px; margin:3px 0; border-radius:4px; font-size:13px; }
  .alert-info { background:#0d1b2a; border-left:3px solid #388bfd;
                padding:6px 10px; margin:3px 0; border-radius:4px; font-size:13px; }
  .badge-new  { background:#b08800; color:#fff; font-size:9px; padding:1px 4px;
                border-radius:3px; vertical-align:middle; margin-left:4px; }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙ Controls")
    asof = st.text_input("As-of date", value=date.today().isoformat())
    rate = st.number_input("Risk-free rate", value=config.RISK_FREE_RATE,
                           min_value=0.0, max_value=0.20, step=0.005, format="%.3f")
    positions_file = st.text_input("Positions file", value=config.POSITIONS_FILE)
    skip_news = st.checkbox("Skip news (saves API cost)", value=False)
    refresh = st.button("🔄 Refresh", type="primary", use_container_width=True)
    if refresh:
        st.cache_data.clear()
        st.rerun()

# ─── Cached pipeline ──────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Running portfolio…")
def _run(asof_: str, pfile_: str, rate_: float):
    return run_portfolio(as_of=asof_, positions_file=pfile_,
                         risk_free_rate=rate_, verbose=False)

@st.cache_data(ttl=300, show_spinner="Fetching macro data…")
def _macro():
    return compute_macro()

valuations = _run(asof, positions_file, rate)

if not valuations:
    st.error("No valuations returned — check positions file and market connectivity.")
    st.stop()

positions  = load_positions(positions_file)
pos_map    = {p.id: p for p in positions}
conn       = snap.get_connection()
analytics  = compute_analytics(valuations, asof, conn)
macro      = _macro()
snap.upsert_macro(conn, macro, asof)
snap.upsert_analytics(conn, analytics, asof)

prior_iv    = load_prior_iv(conn, asof)
chain_diffs = compute_chain_diffs(conn, valuations, asof)

news_results: list[NewsResult] = []
if not skip_news:
    for ticker in sorted({v.ticker for v in valuations}):
        parts = []
        for v in valuations:
            if v.ticker != ticker:
                continue
            if isinstance(v, OptionValuation):
                parts.append(f"{ticker} {v.option_type.upper()} ${v.strike:.0f} "
                             f"exp {v.expiry} ({v.contracts}x)")
            else:
                parts.append(f"{ticker} {v.contracts} shares")
        news_results.append(analyze_ticker_news(conn, ticker, "; ".join(parts) or ticker, asof))

alerts = generate_alerts(valuations, pos_map, chain_diffs, news_results, prior_iv, asof)
snap.upsert_alerts(conn, alerts, asof)
conn.close()

# ─── Derived totals ───────────────────────────────────────────────────────────

total_value = sum(v.current_value for v in valuations)
total_entry = sum(v.entry_value   for v in valuations)
total_pnl   = total_value - total_entry
total_pnl_pct = total_pnl / total_entry * 100 if total_entry else 0.0

ag = analytics.aggregate_greeks
high_alerts = sum(1 for a in alerts if a.severity == "high")
all_alerts  = len(alerts)

# ─── Status strip ─────────────────────────────────────────────────────────────

st.markdown(f"### Portfolio Monitor &nbsp;&nbsp;<span style='font-size:14px;color:#8b949e'>as-of {asof}</span>",
            unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)

with c1:
    st.metric("NAV", f"${total_value:,.0f}")
with c2:
    sign = "+" if total_pnl >= 0 else ""
    st.metric("Net P&L", f"{sign}${total_pnl:,.0f}",
              delta=f"{sign}{total_pnl_pct:.1f}%",
              delta_color="normal" if total_pnl >= 0 else "inverse")
with c3:
    st.metric("Positions", len(valuations))
with c4:
    alert_label = f"{high_alerts} HIGH" if high_alerts else str(all_alerts)
    st.metric("Alerts", alert_label)
with c5:
    regime_emoji = {"RISK-ON": "🟢", "CAUTION": "🟡", "RISK-OFF": "🔴"}.get(macro.regime, "⚪")
    st.metric("Macro", f"{macro.composite_score:.0f}",
              delta=f"{regime_emoji} {macro.regime}")
with c6:
    sign = "+" if ag.net_delta_shares >= 0 else ""
    st.metric("Net Δ", f"{sign}{ag.net_delta_shares:.1f} sh")
with c7:
    st.metric("Daily Θ", f"${ag.total_theta_daily:+.0f}/day")
with c8:
    st.metric("Net V", f"${ag.net_vega_per_pp:+.0f}/1%IV")

st.divider()

# ─── Layout: alerts | positions ───────────────────────────────────────────────

left_col, right_col = st.columns([1, 2])

# ── Active alerts ─────────────────────────────────────────────────────────────
with left_col:
    sev_order = {"high": 0, "warn": 1, "info": 2}
    sorted_alerts = sorted(alerts, key=lambda a: sev_order.get(a.severity, 9))

    st.subheader(f"Alerts ({len(sorted_alerts)})")
    if not sorted_alerts:
        st.success("No alerts")
    else:
        for a in sorted_alerts:
            is_new_strike = a.kind in ("new_strikes", "new_expiry")
            badge = '<span class="badge-new">NEW</span>' if is_new_strike else ""
            detail_html = f"<br><small style='color:#8b949e'>{a.detail}</small>" if a.detail else ""
            st.markdown(
                f'<div class="alert-{a.severity}">'
                f'<b>[{a.kind.upper()}]</b> {a.message}{badge}{detail_html}'
                f'</div>',
                unsafe_allow_html=True,
            )

# ── Positions grid ────────────────────────────────────────────────────────────
with right_col:
    st.subheader("Positions")

    rows = []
    for v in valuations:
        pos = pos_map.get(v.position_id)
        if isinstance(v, OptionValuation):
            rows.append({
                "Position": v.position_id,
                "Type": v.option_type.upper(),
                "Strike": v.strike,
                "Expiry": v.expiry,
                "DTE": v.dte,
                "Qty": v.contracts,
                "Entry": v.entry_value / max(v.contracts * 100, 1),
                "Mark": v.mark,
                "Value": v.current_value,
                "P&L $": v.unrealized_pnl,
                "P&L %": v.unrealized_pnl_pct,
                "Δ": v.greeks.delta,
                "Θ/d": v.greeks.theta * 100 * v.contracts,
                "V/1%": v.greeks.vega * 100 * v.contracts,
                "IV %": v.iv * 100,
                "→Tgt": v.progress_to_target,
                "→Stp": v.progress_to_stop,
            })
        else:
            rows.append({
                "Position": v.position_id,
                "Type": "SHR",
                "Strike": None,
                "Expiry": None,
                "DTE": None,
                "Qty": v.contracts,
                "Entry": v.entry_value / max(v.contracts, 1),
                "Mark": v.mark,
                "Value": v.current_value,
                "P&L $": v.unrealized_pnl,
                "P&L %": v.unrealized_pnl_pct,
                "Δ": 1.0,
                "Θ/d": 0.0,
                "V/1%": 0.0,
                "IV %": None,
                "→Tgt": v.progress_to_target,
                "→Stp": v.progress_to_stop,
            })

    df = pd.DataFrame(rows)

    col_cfg = {
        "Entry":  st.column_config.NumberColumn(format="$%.2f"),
        "Mark":   st.column_config.NumberColumn(format="$%.3f"),
        "Value":  st.column_config.NumberColumn(format="$%.0f"),
        "P&L $":  st.column_config.NumberColumn(format="$%+.0f"),
        "P&L %":  st.column_config.NumberColumn(format="%+.1f%%"),
        "IV %":   st.column_config.NumberColumn(format="%.1f%%"),
        "Δ":      st.column_config.NumberColumn(format="%+.3f"),
        "Θ/d":    st.column_config.NumberColumn(format="$%+.2f"),
        "V/1%":   st.column_config.NumberColumn(format="$%+.2f"),
        "→Tgt":   st.column_config.ProgressColumn("→ Target", min_value=0, max_value=100, format="%.0f%%"),
        "→Stp":   st.column_config.ProgressColumn("→ Stop",   min_value=0, max_value=100, format="%.0f%%"),
    }

    st.dataframe(df, use_container_width=True, hide_index=True, column_config=col_cfg)

st.divider()

# ─── Charts row: theta decay | allocation ─────────────────────────────────────

chart_left, chart_right = st.columns(2)

# ── Theta decay projection ────────────────────────────────────────────────────
with chart_left:
    st.subheader("Theta Decay Projection")
    st.caption("Projected mark at constant spot + IV (illustrative, not predictive)")

    opt_vals = [v for v in valuations if isinstance(v, OptionValuation)]

    if opt_vals:
        max_expiry = max(date.fromisoformat(v.expiry) for v in opt_vals)
        today_dt   = date.fromisoformat(asof)
        step_days  = max(1, (max_expiry - today_dt).days // 60)
        date_range: list[date] = []
        d = today_dt
        while d <= max_expiry:
            date_range.append(d)
            d += timedelta(days=step_days)
        if date_range[-1] < max_expiry:
            date_range.append(max_expiry)

        def _bs_price(S: float, K: float, T: float, r: float,
                      sigma: float, opt_type: str) -> float:
            if T <= 0:
                return max(0.0, S - K) if opt_type == "call" else max(0.0, K - S)
            d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            from math import erf, sqrt, exp
            ncdf = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
            if opt_type == "call":
                return S * ncdf(d1) - K * exp(-r * T) * ncdf(d2)
            return K * exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)

        fig = go.Figure()
        cumulative = [0.0] * len(date_range)

        for v in opt_vals:
            exp_date = date.fromisoformat(v.expiry)
            mult = config.CONTRACTS_PER_OPTION * v.contracts
            spot = v.mark / max(v.greeks.delta, 0.001) if abs(v.greeks.delta) > 0.05 else v.strike
            # Use spot from mark / delta is rough; just use strike as proxy for illustration
            # The actual spot isn't stored on the valuation — use strike as constant S proxy
            S_proxy = v.strike * (1 + (v.mark / v.strike if v.strike > 0 else 0))

            vals_over_time = []
            for dt in date_range:
                dte = max(0, (exp_date - dt).days)
                T = dte / 365.0
                price = _bs_price(S_proxy, v.strike, T, rate, v.iv, v.option_type)
                vals_over_time.append(price * mult)

            prev = cumulative[:]
            for i, val in enumerate(vals_over_time):
                cumulative[i] += val

            fig.add_trace(go.Scatter(
                x=[str(d) for d in date_range],
                y=cumulative,
                name=v.position_id,
                fill="tonexty" if fig.data else "tozeroy",
                mode="lines",
                line=dict(width=1),
                hovertemplate="%{y:$,.0f}<extra>%{fullData.name}</extra>",
            ))

        fig.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(font=dict(size=10)),
            xaxis_title=None, yaxis_title="Position Value ($)",
            yaxis_tickformat="$,.0f",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No option positions to project.")

# ── Allocation ────────────────────────────────────────────────────────────────
with chart_right:
    st.subheader("Allocation")

    tab1, tab2 = st.tabs(["By Ticker", "By Sector"])

    with tab1:
        alloc_df = pd.DataFrame([
            {"Ticker": a.ticker, "Value": a.value, "Sector": a.sector, "%": a.pct}
            for a in analytics.allocations_by_ticker
        ])
        fig = px.bar(alloc_df, x="Ticker", y="%", color="Sector",
                     hover_data={"Value": ":$,.0f", "%": ":.1f"},
                     height=280)
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(font=dict(size=9)),
                          yaxis_title="% of NAV")
        # Concentration cap line
        fig.add_hline(y=config.TICKER_CONCENTRATION_CAP * 100,
                      line_dash="dash", line_color="red",
                      annotation_text=f"Cap {config.TICKER_CONCENTRATION_CAP*100:.0f}%")
        st.plotly_chart(fig, use_container_width=True)

        if analytics.concentration_flags:
            for flag in analytics.concentration_flags:
                st.warning(f"{flag.kind.upper()} {flag.name}  {flag.pct:.1f}% > cap {flag.cap:.0f}%")

    with tab2:
        sec_df = pd.DataFrame([
            {"Sector": s.sector, "Value": s.value, "%": s.pct}
            for s in analytics.allocations_by_sector
        ])
        fig = px.pie(sec_df, names="Sector", values="%",
                     hover_data={"Value": ":$,.0f"}, height=280)
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(font=dict(size=9)))
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# ─── Macro detail ─────────────────────────────────────────────────────────────

st.subheader("Macro Gate")
mc1, mc2, mc3, mc4, mc5 = st.columns(5)

regime_color = {"RISK-ON": "🟢", "CAUTION": "🟡", "RISK-OFF": "🔴"}.get(macro.regime, "⚪")
mc1.metric("Composite", f"{macro.composite_score:.1f}", delta=f"{regime_color} {macro.regime}")
mc2.metric("VIX", f"{macro.vix_level:.1f}" if macro.vix_level else "n/a",
           delta=f"score {macro.vix_score:.0f}" if macro.vix_score else None)
mc3.metric("Term (VIX/VIX3M)", f"{macro.term_ratio:.3f}" if macro.term_ratio else "n/a",
           delta=f"score {macro.term_score:.0f}" if macro.term_score else None)
mc4.metric("Breadth", f"{macro.breadth_pct:.0f}%" if macro.breadth_pct is not None else "n/a",
           delta=f"score {macro.breadth_score:.0f}" if macro.breadth_score else None)
mc5.metric("Credit (HYG/TLT)", f"pct {macro.credit_percentile:.0f}%" if macro.credit_percentile else "n/a",
           delta=f"score {macro.credit_score:.0f}" if macro.credit_score else None)

st.divider()

# ─── Strike ladder ────────────────────────────────────────────────────────────

st.subheader("Strike Ladder")
st.caption("±6 strikes around each held option; NEW = listed since last run")

# Build set of new-strike keys for badge rendering
new_strike_keys: set[tuple] = set()
for diff in chain_diffs:
    for ns in diff.new_strikes:
        new_strike_keys.add((diff.ticker, ns.expiry, ns.option_type, ns.strike))

conn2 = snap.get_connection()

for v in [v for v in valuations if isinstance(v, OptionValuation)]:
    with st.expander(f"{v.position_id}  —  mark {v.mark:.3f}  IV {v.iv*100:.1f}%  DTE {v.dte}"):
        rows_chain = conn2.execute(
            """
            SELECT strike, bid, ask, last_price, mark, iv, volume, open_interest
            FROM option_chains
            WHERE ticker = ? AND as_of_date = ? AND expiry = ? AND option_type = ?
            ORDER BY ABS(strike - ?) LIMIT 13
            """,
            (v.ticker, asof, v.expiry, v.option_type, v.strike),
        ).fetchall()

        if not rows_chain:
            st.info("No chain data — run main.py first to populate snapshots.")
            continue

        # Sort by strike and find nearest 6 above/below
        all_strikes = sorted({r["strike"] for r in rows_chain})
        try:
            idx = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - v.strike))
        except ValueError:
            continue
        lo = max(0, idx - 6)
        hi = min(len(all_strikes), idx + 7)
        ladder_strikes = set(all_strikes[lo:hi])

        chain_map = {r["strike"]: dict(r) for r in rows_chain}
        ladder_rows = []
        for s in sorted(ladder_strikes):
            r = chain_map.get(s, {})
            is_new = (v.ticker, v.expiry, v.option_type, s) in new_strike_keys
            ladder_rows.append({
                "Strike": s,
                "Held": "★" if s == v.strike else "",
                "NEW":  "NEW" if is_new else "",
                "Bid":  r.get("bid"),
                "Ask":  r.get("ask"),
                "Last": r.get("last_price"),
                "IV %": (r["iv"] * 100) if r.get("iv") else None,
                "Vol":  r.get("volume"),
                "OI":   r.get("open_interest"),
            })

        ladder_df = pd.DataFrame(ladder_rows)
        st.dataframe(
            ladder_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "IV %": st.column_config.NumberColumn(format="%.1f%%"),
                "Bid":  st.column_config.NumberColumn(format="$%.2f"),
                "Ask":  st.column_config.NumberColumn(format="$%.2f"),
                "Last": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

conn2.close()

st.divider()

# ─── News panel ───────────────────────────────────────────────────────────────

if news_results:
    st.subheader("News Analysis")
    st.caption(f"Via {config.NEWS_MODEL}  ·  last {config.NEWS_WINDOW_DAYS} days")

    _sent_color = {"bullish": "🟢", "bearish": "🔴", "mixed": "🟡", "neutral": "⚪"}
    _flag_color = {"aligned": "🟢", "contrarian": "🔴", "neutral": "⚪", "no news": "⚫"}

    cols_per_row = 2
    for i in range(0, len(news_results), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, nr in enumerate(news_results[i : i + cols_per_row]):
            with cols[j]:
                cached_tag = " *(cached)*" if nr.cached else ""
                s_icon = _sent_color.get(nr.sentiment, "⚪")
                f_icon = _flag_color.get(nr.position_flag, "⚪")
                st.markdown(
                    f"**{nr.ticker}**  "
                    f"{s_icon} {nr.sentiment}  ·  "
                    f"{f_icon} {nr.position_flag}  ·  "
                    f"{nr.headline_count} headlines{cached_tag}"
                )
                if nr.summary:
                    st.caption(nr.summary)
                if nr.key_drivers:
                    st.markdown(
                        "Drivers: " + "  ·  ".join(
                            f"*{d}*" for d in nr.key_drivers
                        )
                    )
                st.markdown("---")
