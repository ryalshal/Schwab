"""
Notifier — Layer 4d.

Sends three daily emails:
  1. Portfolio Monitor  — positions, P&L, alerts, macro, news
  2. Greeks & Technical — per-position greeks, IV, theta decay table, strike ladder
  3. Strategy Overview  — thesis positions, allocation, scenarios, catalysts

Public API:
    from src import notifier
    notifier.send_daily_emails(alerts, valuations, analytics, chain_diffs,
                               news_results, macro, as_of)
"""
from __future__ import annotations

import json
import math
import os
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from src.alerts import Alert
    from src.analytics import PortfolioAnalytics
    from src.macro import MacroResult
    from src.models import OptionValuation, ShareValuation
    from src.news import NewsResult
    from src.diff import ChainDiff


# ─── Shared send helper ───────────────────────────────────────────────────────

def _send(subject: str, html: str, plain: str) -> None:
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not password:
        print("[notifier] GMAIL_APP_PASSWORD not set — skipping email")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config.NOTIFIER_EMAIL_FROM
    msg["To"]      = config.NOTIFIER_EMAIL_TO
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    try:
        with smtplib.SMTP(config.NOTIFIER_EMAIL_SMTP_HOST,
                          config.NOTIFIER_EMAIL_SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.NOTIFIER_EMAIL_FROM, password)
            server.sendmail(config.NOTIFIER_EMAIL_FROM,
                            config.NOTIFIER_EMAIL_TO,
                            msg.as_string())
        print(f"[notifier] '{subject}' sent to {config.NOTIFIER_EMAIL_TO}")
    except Exception as exc:
        print(f"[notifier] Email failed ({subject}): {exc}")


# ─── Shared HTML helpers ──────────────────────────────────────────────────────

_BASE_STYLE = """
<style>
  body { margin:0; padding:0; background:#0d1117; font-family:Arial,sans-serif; }
  .wrap { max-width:700px; margin:24px auto; background:#161b22;
          border:1px solid #30363d; border-radius:8px; overflow:hidden; }
  .hdr  { padding:16px 20px; background:#0d1117; border-bottom:1px solid #30363d; }
  .hdr-title { font-size:18px; font-weight:700; color:#e6edf3; }
  .hdr-date  { float:right; font-size:12px; color:#8b949e; }
  .section   { padding:14px 20px; border-bottom:1px solid #30363d; }
  .sec-label { font-size:10px; letter-spacing:2px; color:#6b7280;
               text-transform:uppercase; margin-bottom:10px; }
  table.data { width:100%; border-collapse:collapse; }
  table.data th { font-size:10px; color:#6b7280; text-transform:uppercase;
                  letter-spacing:1px; padding:4px 8px; border-bottom:1px solid #30363d;
                  text-align:left; }
  table.data td { font-size:12px; color:#e6edf3; padding:5px 8px;
                  border-bottom:1px solid #1f2937; font-family:monospace; }
  .green  { color:#3fb950; }
  .red    { color:#f85149; }
  .yellow { color:#e3b341; }
  .blue   { color:#388bfd; }
  .dim    { color:#8b949e; }
  .badge  { padding:1px 7px; border-radius:3px; font-size:11px; font-weight:600; }
  .badge-call  { background:#312e81; color:#a5b4fc; }
  .badge-share { background:#064e3b; color:#6ee7b7; }
  .ftr  { padding:10px 20px; background:#0d1117; border-top:1px solid #30363d; }
  .ftr span { font-size:11px; color:#484f58; }
  .disclaimer { font-size:10px; color:#484f58; text-align:center; padding:8px; }
  .metric-row { display:flex; gap:0; }
  .metric { flex:1; padding:10px 16px; border-right:1px solid #30363d; }
  .metric:last-child { border-right:none; }
  .metric-label { font-size:10px; color:#6b7280; text-transform:uppercase;
                  letter-spacing:1px; margin-bottom:4px; }
  .metric-value { font-size:18px; font-weight:700; color:#e6edf3; }
  .metric-delta { font-size:11px; }
</style>
"""


def _wrap(title: str, icon: str, as_of: str, body: str, disclaimer: bool = False) -> str:
    disc = '<p class="disclaimer">NOT FINANCIAL ADVICE — ALL PROBABILITIES ARE ESTIMATES — POSITION SIZE TO WHAT YOU CAN LOSE</p>' if disclaimer else ""
    return f"""<!DOCTYPE html><html><head>{_BASE_STYLE}</head>
<body><div class="wrap">
  <div class="hdr">
    <span class="hdr-title">{icon} {title}</span>
    <span class="hdr-date">{as_of}</span>
  </div>
  {body}
  {disc}
  <div class="ftr"><span>AI Trading · Concentrated Thesis Strategy · {as_of}</span></div>
</div></body></html>"""


def _pnl_color(val: float) -> str:
    cls = "green" if val >= 0 else "red"
    sign = "+" if val >= 0 else ""
    return f'<span class="{cls}">{sign}{val:,.2f}</span>'


def _pct_color(val: float) -> str:
    cls = "green" if val >= 0 else "red"
    sign = "+" if val >= 0 else ""
    return f'<span class="{cls}">{sign}{val:.1f}%</span>'


def _progress_html(pct: float | None, width: int = 80) -> str:
    if pct is None:
        return '<span class="dim">n/a</span>'
    clamped = max(0.0, min(100.0, pct))
    color = "#3fb950" if clamped >= 80 else "#e3b341" if clamped >= 40 else "#388bfd"
    return (f'<div style="background:#1f2937;border-radius:3px;height:6px;width:{width}px;display:inline-block;vertical-align:middle">'
            f'<div style="background:{color};height:6px;border-radius:3px;width:{clamped/100*width:.0f}px"></div></div>'
            f' <span style="font-size:11px;color:#8b949e">{pct:.0f}%</span>')


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 1 — Portfolio Monitor
# ═══════════════════════════════════════════════════════════════════════════════

def send_portfolio_email(alerts: list, valuations: list, analytics,
                         macro, news_results: list, as_of: str) -> None:

    from src.models import OptionValuation

    total_value = sum(v.current_value for v in valuations)
    total_entry = sum(v.entry_value   for v in valuations)
    total_pnl   = total_value - total_entry
    total_pnl_pct = total_pnl / total_entry * 100 if total_entry else 0.0

    high = [a for a in alerts if a.severity == "high"]
    warn = [a for a in alerts if a.severity == "warn"]
    info = [a for a in alerts if a.severity == "info"]

    # Subject
    parts = []
    if high: parts.append(f"{len(high)} HIGH")
    if warn: parts.append(f"{len(warn)} WARN")
    if not high and not warn: parts.append("All Clear")
    subject = f"📊 Portfolio Monitor {as_of} — " + ", ".join(parts)

    # KPI strip
    regime_icon = {"RISK-ON":"🟢","CAUTION":"🟡","RISK-OFF":"🔴"}.get(macro.regime,"⚪")
    kpi = f"""
<div class="metric-row" style="border-bottom:1px solid #30363d">
  <div class="metric">
    <div class="metric-label">NAV</div>
    <div class="metric-value">${total_value:,.0f}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Net P&L</div>
    <div class="metric-value">{_pnl_color(total_pnl)}</div>
    <div class="metric-delta">{_pct_color(total_pnl_pct)}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Positions</div>
    <div class="metric-value">{len(valuations)}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Macro</div>
    <div class="metric-value">{macro.composite_score:.0f}</div>
    <div class="metric-delta">{regime_icon} {macro.regime}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Alerts</div>
    <div class="metric-value {'red' if high else 'yellow' if warn else 'green'}">{len(high)} H · {len(warn)} W · {len(info)} I</div>
  </div>
</div>"""

    # Positions table
    pos_rows = ""
    for v in valuations:
        if isinstance(v, OptionValuation):
            label = f"{v.ticker} ${v.strike:.0f}{v.option_type[0].upper()} {v.expiry}"
            badge = '<span class="badge badge-call">CALL</span>'
            dte_html = f'<span class="{"red" if v.dte <= 14 else "yellow" if v.dte <= 45 else "dim"}">{v.dte}d</span>'
        else:
            label = f"{v.ticker} {v.contracts} shares"
            badge = '<span class="badge badge-share">SHARE</span>'
            dte_html = '<span class="dim">—</span>'
        pos_rows += f"""<tr>
          <td>{label}</td>
          <td>{badge}</td>
          <td>${v.current_value:,.0f}</td>
          <td>{_pnl_color(v.unrealized_pnl)}</td>
          <td>{_pct_color(v.unrealized_pnl_pct)}</td>
          <td>{dte_html}</td>
          <td>{_progress_html(v.progress_to_target)}</td>
        </tr>"""

    positions_section = f"""
<div class="section">
  <div class="sec-label">Positions</div>
  <table class="data">
    <tr><th>Position</th><th>Type</th><th>Value</th><th>P&L $</th><th>P&L %</th><th>DTE</th><th>→ Target</th></tr>
    {pos_rows}
  </table>
</div>"""

    # Alerts section
    def _alert_rows(group, color, icon):
        return "".join(f"""<tr>
          <td style="padding:5px 8px;color:{color};font-family:monospace;font-size:12px">
            {icon} {a.message}
            {"<br><span style='color:#6b7280;font-size:11px'>" + a.detail + "</span>" if a.detail else ""}
          </td></tr>""" for a in group)

    alert_body = (
        _alert_rows(high, "#f85149", "🔴") +
        _alert_rows(warn, "#e3b341", "🟡") +
        _alert_rows(info, "#388bfd", "🔵")
    ) or '<tr><td style="color:#3fb950;padding:8px">✓ No alerts today</td></tr>'

    alerts_section = f"""
<div class="section">
  <div class="sec-label">Alerts ({len(alerts)})</div>
  <table class="data">{alert_body}</table>
</div>"""

    # Macro section
    def _ms(val):
        return f"{val:.0f}" if val is not None else "n/a"
    def _mf(val, fmt=".0f"):
        return format(val, fmt) if val is not None else "n/a"

    comp_cls = "green" if macro.composite_score >= 60 else "yellow" if macro.composite_score >= 35 else "red"
    macro_section = f"""
<div class="section">
  <div class="sec-label">Macro Gate</div>
  <table class="data">
    <tr><th>Indicator</th><th>Score</th><th>Detail</th></tr>
    <tr><td>Composite</td><td class="{comp_cls}">{macro.composite_score:.1f}</td><td>{regime_icon} {macro.regime}</td></tr>
    <tr><td>VIX</td><td>{_ms(macro.vix_score)}</td><td class="dim">VIX={_mf(macro.vix_level, '.1f')}</td></tr>
    <tr><td>Term Structure</td><td>{_ms(macro.term_score)}</td><td class="dim">ratio={_mf(macro.term_ratio, '.3f')}</td></tr>
    <tr><td>Breadth</td><td>{_ms(macro.breadth_score)}</td><td class="dim">{_mf(macro.breadth_pct)}% ETFs above 200d MA</td></tr>
    <tr><td>Credit</td><td>{_ms(macro.credit_score)}</td><td class="dim">HYG/TLT pct={_mf(macro.credit_percentile)}%</td></tr>
  </table>
</div>"""

    # News section
    news_section = ""
    if news_results:
        sent_color = {"bullish":"#3fb950","bearish":"#f85149","mixed":"#e3b341","neutral":"#8b949e"}
        flag_color = {"aligned":"#3fb950","contrarian":"#f85149","neutral":"#8b949e","no news":"#484f58"}
        news_rows = "".join(f"""<tr>
          <td style="font-weight:700;color:#e6edf3">{r.ticker}</td>
          <td style="color:{sent_color.get(r.sentiment,'#8b949e')}">{r.sentiment}</td>
          <td style="color:{flag_color.get(r.position_flag,'#8b949e')}">{r.position_flag}</td>
          <td class="dim" style="font-size:11px">{r.summary or '—'}</td>
        </tr>""" for r in news_results)
        news_section = f"""
<div class="section">
  <div class="sec-label">News Sentiment</div>
  <table class="data">
    <tr><th>Ticker</th><th>Sentiment</th><th>Position Flag</th><th>Summary</th></tr>
    {news_rows}
  </table>
</div>"""

    body = kpi + positions_section + alerts_section + macro_section + news_section
    html = _wrap("Portfolio Monitor", "📊", as_of, body)

    plain_lines = [f"Portfolio Monitor — {as_of}", "=" * 60,
                   f"NAV: ${total_value:,.0f}  |  P&L: ${total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)",
                   f"Macro: {macro.composite_score:.0f} {macro.regime}", "",
                   f"HIGH: {len(high)}  WARN: {len(warn)}  INFO: {len(info)}", ""]
    for a in alerts:
        plain_lines.append(f"  [{a.severity.upper()}] {a.message}")
    plain = "\n".join(plain_lines)

    _send(subject, html, plain)


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 2 — Greeks & Technical
# ═══════════════════════════════════════════════════════════════════════════════

def send_greeks_email(valuations: list, analytics, chain_diffs: list, as_of: str) -> None:
    from src.models import OptionValuation

    subject = f"📐 Greeks & Technical {as_of}"

    # Aggregate greeks strip
    ag = analytics.aggregate_greeks
    kpi = f"""
<div class="metric-row" style="border-bottom:1px solid #30363d">
  <div class="metric">
    <div class="metric-label">Net Delta</div>
    <div class="metric-value {'green' if ag.net_delta_shares>=0 else 'red'}">{ag.net_delta_shares:+.2f}</div>
    <div class="metric-delta dim">share-equiv</div>
  </div>
  <div class="metric">
    <div class="metric-label">Daily Theta</div>
    <div class="metric-value {'red' if ag.total_theta_daily<0 else 'green'}">${ag.total_theta_daily:+.2f}</div>
    <div class="metric-delta dim">per day</div>
  </div>
  <div class="metric">
    <div class="metric-label">Net Vega</div>
    <div class="metric-value {'green' if ag.net_vega_per_pp>=0 else 'red'}">${ag.net_vega_per_pp:+.2f}</div>
    <div class="metric-delta dim">per 1% IV move</div>
  </div>
</div>"""

    # Per-position greeks table
    greek_rows = ""
    for v in valuations:
        if isinstance(v, OptionValuation):
            g = v.greeks
            theta_day = g.theta * 100 * v.contracts
            vega_pp   = g.vega  * 100 * v.contracts
            iv_color  = "red" if v.iv * 100 > config.IV_RICH_THRESHOLD else "green" if v.iv * 100 < config.IV_CHEAP_THRESHOLD else ""
            greek_rows += f"""<tr>
              <td>{v.position_id}</td>
              <td class="dim">{v.dte}d</td>
              <td>{v.mark:.3f}</td>
              <td class="{iv_color}">{v.iv*100:.1f}%</td>
              <td>{g.delta:+.4f}</td>
              <td>{g.gamma:.5f}</td>
              <td class="{'red' if theta_day<0 else ''}">${theta_day:+.2f}/d</td>
              <td>${vega_pp:+.2f}</td>
            </tr>"""
        else:
            greek_rows += f"""<tr>
              <td>{v.position_id}</td>
              <td class="dim">—</td>
              <td>{v.mark:.2f}</td>
              <td class="dim">—</td>
              <td>+1.0000</td>
              <td class="dim">—</td>
              <td class="dim">—</td>
              <td class="dim">—</td>
            </tr>"""

    greeks_section = f"""
<div class="section">
  <div class="sec-label">Per-Position Greeks</div>
  <table class="data">
    <tr><th>Position</th><th>DTE</th><th>Mark</th><th>IV</th><th>Delta</th><th>Gamma</th><th>Theta/day</th><th>Vega/1%</th></tr>
    {greek_rows}
  </table>
</div>"""

    # Theta decay table (7-day projection)
    decay_rows = ""
    opt_vals = [v for v in valuations if isinstance(v, OptionValuation)]
    if opt_vals:
        today_dt = date.fromisoformat(as_of)
        intervals = [1, 3, 7, 14, 30]
        for v in opt_vals:
            exp_date = date.fromisoformat(v.expiry)
            mult = config.CONTRACTS_PER_OPTION * v.contracts
            row = f"<tr><td>{v.position_id}</td>"
            for days in intervals:
                future = today_dt + timedelta(days=days)
                dte = max(0, (exp_date - future).days)
                T   = dte / 365.0
                if T > 0:
                    projected = _bs_price(v.mark / max(abs(v.greeks.delta), 0.05),
                                          v.strike, T, config.RISK_FREE_RATE,
                                          v.iv, v.option_type)
                else:
                    projected = 0.0
                val = projected * mult
                color = "green" if val > v.current_value else "red"
                row += f'<td class="{color}">${val:,.0f}</td>'
            row += f"<td>${v.current_value:,.0f}</td></tr>"
            decay_rows += row

    decay_section = ""
    if decay_rows:
        decay_section = f"""
<div class="section">
  <div class="sec-label">Theta Decay Projection (constant spot + IV)</div>
  <table class="data">
    <tr><th>Position</th><th>+1d</th><th>+3d</th><th>+7d</th><th>+14d</th><th>+30d</th><th>Now</th></tr>
    {decay_rows}
  </table>
  <p style="font-size:10px;color:#484f58;margin:6px 0 0">Illustrative only — assumes constant underlying price and IV</p>
</div>"""

    # IV Environment
    iv_rows = ""
    if analytics.iv_stats:
        for iv in analytics.iv_stats:
            rank_s = f"{iv.iv_rank:.1f}" if iv.iv_rank is not None else "n/a"
            pct_s  = f"{iv.iv_percentile:.1f}" if iv.iv_percentile is not None else "n/a"
            color  = "red" if iv.status == "rich" else "green" if iv.status == "cheap" else "dim"
            iv_rows += f"""<tr>
              <td>{iv.position_id}</td>
              <td>{iv.current_iv*100:.1f}%</td>
              <td>{rank_s}</td>
              <td>{pct_s}</td>
              <td>{iv.history_days}d</td>
              <td class="{color}">{iv.status}</td>
            </tr>"""

    iv_section = f"""
<div class="section">
  <div class="sec-label">IV Environment</div>
  <table class="data">
    <tr><th>Position</th><th>Current IV</th><th>IV Rank</th><th>IV Pct</th><th>History</th><th>Status</th></tr>
    {iv_rows or '<tr><td colspan="6" class="dim">No IV history yet</td></tr>'}
  </table>
</div>"""

    # DTE flags
    dte_section = ""
    if analytics.dte_flags:
        dte_rows = "".join(f"""<tr>
          <td class="{'red' if f.dte<=14 else 'yellow'}">{f.position_id}</td>
          <td class="{'red' if f.dte<=14 else 'yellow'}">{f.dte}d</td>
          <td class="dim">{f.expiry}</td>
        </tr>""" for f in analytics.dte_flags)
        dte_section = f"""
<div class="section">
  <div class="sec-label">⚠ Upcoming Expiries (≤{config.DTE_WARNING_THRESHOLD}d)</div>
  <table class="data">
    <tr><th>Position</th><th>DTE</th><th>Expiry</th></tr>
    {dte_rows}
  </table>
</div>"""

    # Strike ladder / chain diffs
    diff_section = ""
    if chain_diffs:
        diff_rows = ""
        for diff in chain_diffs:
            if diff.new_strikes:
                for ns in diff.new_strikes:
                    diff_rows += f"""<tr>
                      <td>{diff.ticker}</td>
                      <td class="yellow">NEW STRIKE</td>
                      <td>${ns.strike:.0f} {ns.option_type.upper()}</td>
                      <td class="dim">{ns.expiry}</td>
                    </tr>"""
            if diff.new_expiries:
                for ne in diff.new_expiries:
                    diff_rows += f"""<tr>
                      <td>{diff.ticker}</td>
                      <td class="blue">NEW EXPIRY</td>
                      <td class="dim">—</td>
                      <td class="dim">{ne}</td>
                    </tr>"""
        if diff_rows:
            diff_section = f"""
<div class="section">
  <div class="sec-label">Strike Ladder — New Listings Since Last Run</div>
  <table class="data">
    <tr><th>Ticker</th><th>Type</th><th>Strike</th><th>Expiry</th></tr>
    {diff_rows}
  </table>
</div>"""

    body = kpi + greeks_section + decay_section + iv_section + dte_section + diff_section
    html = _wrap("Greeks & Technical", "📐", as_of, body)

    plain_lines = [f"Greeks & Technical — {as_of}", "=" * 60,
                   f"Net Delta: {ag.net_delta_shares:+.2f} sh  |  Theta: ${ag.total_theta_daily:+.2f}/day  |  Vega: ${ag.net_vega_per_pp:+.2f}/1%IV", ""]
    for v in valuations:
        if isinstance(v, OptionValuation):
            g = v.greeks
            plain_lines.append(f"{v.position_id}: mark={v.mark:.3f} IV={v.iv*100:.1f}% Δ={g.delta:+.4f} Θ=${g.theta*100*v.contracts:+.2f}/d")
    plain = "\n".join(plain_lines)

    _send(subject, html, plain)


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 3 — Concentrated Thesis Strategy
# ═══════════════════════════════════════════════════════════════════════════════

def send_strategy_email(as_of: str) -> None:
    strategy_file = Path("strategy_positions.json")
    if not strategy_file.exists():
        print("[notifier] strategy_positions.json not found — skipping strategy email")
        return

    with open(strategy_file, encoding="utf-8") as f:
        positions = json.load(f)

    if not positions:
        return

    subject = f"📋 Concentrated Thesis Strategy {as_of}"

    TOTAL_BOOK   = 8100.0
    cash_reserve = TOTAL_BOOK * 0.15

    raw_total = sum(p["size"] for p in positions)
    deployed  = TOTAL_BOOK - cash_reserve
    scale     = deployed / raw_total if raw_total > 0 else 1.0
    for p in positions:
        p["_size"] = p["size"] * scale
        p["_pct"]  = p["_size"] / TOTAL_BOOK * 100

    calls_val  = sum(p["_size"] for p in positions if p["vehicle"] == "Calls")
    shares_val = sum(p["_size"] for p in positions if p["vehicle"] == "Shares")
    total_deployed = calls_val + shares_val

    # KPI strip
    kpi = f"""
<div class="metric-row" style="border-bottom:1px solid #30363d">
  <div class="metric">
    <div class="metric-label">Total Book</div>
    <div class="metric-value">${TOTAL_BOOK:,.0f}</div>
  </div>
  <div class="metric">
    <div class="metric-label">Deployed</div>
    <div class="metric-value">${total_deployed:,.0f}</div>
    <div class="metric-delta dim">{total_deployed/TOTAL_BOOK*100:.0f}% of book</div>
  </div>
  <div class="metric">
    <div class="metric-label">Cash Reserve</div>
    <div class="metric-value">${cash_reserve:,.0f}</div>
    <div class="metric-delta dim">{cash_reserve/TOTAL_BOOK*100:.0f}% dry powder</div>
  </div>
  <div class="metric">
    <div class="metric-label">Options</div>
    <div class="metric-value">${calls_val:,.0f}</div>
    <div class="metric-delta dim">{calls_val/TOTAL_BOOK*100:.0f}% of book</div>
  </div>
  <div class="metric">
    <div class="metric-label">Shares</div>
    <div class="metric-value">${shares_val:,.0f}</div>
    <div class="metric-delta dim">{shares_val/TOTAL_BOOK*100:.0f}% of book</div>
  </div>
</div>"""

    # Overview — positions table
    pos_rows = ""
    for p in positions:
        badge_cls = "call" if p["vehicle"] == "Calls" else "share"
        dte = str(int(p["dte"])) + "d" if p.get("dte") else "—"
        pos_rows += f"""<tr>
          <td style="font-weight:600;color:#e6edf3">{p['id']}</td>
          <td><span class="badge badge-{badge_cls}">{p['vehicle']}</span></td>
          <td class="dim">{p['sector']}</td>
          <td>${p['_size']:,.0f}</td>
          <td>{p['_pct']:.1f}%</td>
          <td class="dim">${p['entry']:g}</td>
          <td class="dim">{dte}</td>
          <td class="dim" style="font-size:11px">{p['thesis']}</td>
        </tr>"""

    overview_section = f"""
<div class="section">
  <div class="sec-label">All Positions</div>
  <table class="data">
    <tr><th>Position</th><th>Vehicle</th><th>Sector</th><th>Size</th><th>% Port</th><th>Entry</th><th>DTE</th><th>Thesis</th></tr>
    {pos_rows}
  </table>
</div>"""

    # Risk — conviction & downside scores
    risk_rows = ""
    for p in positions:
        conv_bar = int(p["conviction"] / 10 * 60)
        dd_bar   = int(p["downside_protection"] / 10 * 60)
        risk_rows += f"""<tr>
          <td>{p['id']}</td>
          <td><div style="background:#1f2937;border-radius:2px;height:5px;width:60px;display:inline-block;vertical-align:middle"><div style="background:#6366f1;height:5px;border-radius:2px;width:{conv_bar}px"></div></div> {p['conviction']}/10</td>
          <td><div style="background:#1f2937;border-radius:2px;height:5px;width:60px;display:inline-block;vertical-align:middle"><div style="background:#10b981;height:5px;border-radius:2px;width:{dd_bar}px"></div></div> {p['downside_protection']}/10</td>
          <td class="dim">{p['catalyst_clarity']}/10</td>
          <td class="dim">${p['bear_case']:g}</td>
        </tr>"""

    risk_section = f"""
<div class="section">
  <div class="sec-label">Risk Profile</div>
  <table class="data">
    <tr><th>Position</th><th>Conviction</th><th>Downside Prot.</th><th>Catalyst Clarity</th><th>Bear Case</th></tr>
    {risk_rows}
  </table>
</div>"""

    # Scenarios
    total_entry_val = sum(p["_size"] for p in positions)
    bull_val = sum(p["bull_case"] / p["entry"] * p["_size"] for p in positions)
    base_val = sum(p["base_case"] / p["entry"] * p["_size"] for p in positions)
    bear_val = sum(p["bear_case"] / p["entry"] * p["_size"] for p in positions)

    def _return_color(val, entry):
        pct = (val - entry) / entry * 100
        c   = "green" if pct >= 0 else "red"
        return f'<span class="{c}">${val+cash_reserve:,.0f} ({pct:+.0f}%)</span>'

    scen_rows = ""
    for p in positions:
        bull_r = (p["bull_case"] / p["entry"] - 1) * 100
        base_r = (p["base_case"] / p["entry"] - 1) * 100
        bear_r = (p["bear_case"] / p["entry"] - 1) * 100
        scen_rows += f"""<tr>
          <td>{p['id']}</td>
          <td class="green">+{bull_r:.0f}%</td>
          <td class="blue">+{base_r:.0f}%</td>
          <td class="red">{bear_r:.0f}%</td>
        </tr>"""

    scen_section = f"""
<div class="section">
  <div class="sec-label">Scenarios</div>
  <div style="display:flex;gap:0;margin-bottom:12px;border:1px solid #30363d;border-radius:6px;overflow:hidden">
    <div style="flex:1;padding:10px 14px;border-right:1px solid #30363d">
      <div class="sec-label">Bull Case</div>
      <div style="font-size:16px;font-weight:700">{_return_color(bull_val, total_entry_val)}</div>
    </div>
    <div style="flex:1;padding:10px 14px;border-right:1px solid #30363d">
      <div class="sec-label">Base Case</div>
      <div style="font-size:16px;font-weight:700">{_return_color(base_val, total_entry_val)}</div>
    </div>
    <div style="flex:1;padding:10px 14px">
      <div class="sec-label">Bear Case</div>
      <div style="font-size:16px;font-weight:700">{_return_color(bear_val, total_entry_val)}</div>
    </div>
  </div>
  <table class="data">
    <tr><th>Position</th><th class="green">Bull %</th><th class="blue">Base %</th><th class="red">Bear %</th></tr>
    {scen_rows}
  </table>
</div>"""

    # Catalysts
    today = date.today()
    cat_rows = ""
    for p in positions:
        for cat in (p.get("catalysts") or []):
            try:
                cat_date  = date.fromisoformat(cat["date"])
                days_away = (cat_date - today).days
                if days_away < 0:
                    continue
                urgency = "red" if days_away < 14 else "yellow" if days_away < 45 else "green"
                cat_rows += f"""<tr>
                  <td>{cat['date']}</td>
                  <td class="{urgency}">{days_away}d</td>
                  <td style="font-weight:600">{p['ticker']}</td>
                  <td>{cat['event']}</td>
                  <td class="dim">{cat.get('expected_move','—')}</td>
                  <td class="dim" style="font-size:11px">{p['thesis']}</td>
                </tr>"""
            except (ValueError, KeyError):
                pass

    catalyst_section = f"""
<div class="section">
  <div class="sec-label">Upcoming Catalysts</div>
  <table class="data">
    <tr><th>Date</th><th>Days</th><th>Ticker</th><th>Event</th><th>Expected Move</th><th>Thesis</th></tr>
    {cat_rows or '<tr><td colspan="6" class="dim">No upcoming catalysts</td></tr>'}
  </table>
</div>"""

    # Exit framework reminder
    exit_section = """
<div class="section">
  <div class="sec-label">Exit Rules (Quick Reference)</div>
  <table class="data">
    <tr><td class="green">+100% gain</td><td class="dim">Sell 30% to lock in profit</td></tr>
    <tr><td class="green">+200% gain</td><td class="dim">Sell another 30%</td></tr>
    <tr><td class="blue">Final 40%</td><td class="dim">Let it ride for full thesis play-out</td></tr>
    <tr><td class="red">-50% on thesis break</td><td class="dim">Cut the position entirely</td></tr>
    <tr><td class="yellow">-50% on no news</td><td class="dim">Hold — theta + volatility, not thesis failure</td></tr>
    <tr><td class="yellow">Earnings in 2 days</td><td class="dim">Decide: exit pre-print or hold through binary</td></tr>
    <tr><td class="yellow">30 DTE on short calls</td><td class="dim">Evaluate: sell for salvage or hold for catalyst</td></tr>
  </table>
</div>"""

    body = kpi + overview_section + risk_section + scen_section + catalyst_section + exit_section
    html = _wrap("Concentrated Thesis Strategy", "📋", as_of, body, disclaimer=True)

    plain_lines = [f"Concentrated Thesis Strategy — {as_of}", "=" * 60,
                   f"Book: ${TOTAL_BOOK:,.0f}  Deployed: ${total_deployed:,.0f}  Cash: ${cash_reserve:,.0f}", "",
                   "POSITIONS:", ""]
    for p in positions:
        plain_lines.append(f"  {p['id']:<30} ${p['_size']:>7,.0f}  {p['_pct']:.1f}%  {p['thesis']}")
    plain_lines += ["", f"Bull: ${bull_val+cash_reserve:,.0f}  Base: ${base_val+cash_reserve:,.0f}  Bear: ${bear_val+cash_reserve:,.0f}"]
    plain = "\n".join(plain_lines)

    _send(subject, html, plain)


# ═══════════════════════════════════════════════════════════════════════════════
# Black-Scholes helper (for theta decay table)
# ═══════════════════════════════════════════════════════════════════════════════

def _bs_price(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> float:
    if T <= 0 or S <= 0 or sigma <= 0:
        return max(0.0, S - K) if opt_type == "call" else max(0.0, K - S)
    from math import log, sqrt, exp, erf
    ncdf = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
    d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if opt_type == "call":
        return S * ncdf(d1) - K * exp(-r * T) * ncdf(d2)
    return K * exp(-r * T) * ncdf(-d2) - S * ncdf(-d1)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def send_daily_emails(alerts: list, valuations: list, analytics,
                      chain_diffs: list, news_results: list, macro, as_of: str) -> None:
    """Send all three daily emails. Call from main.py after all data is computed."""
    if not config.NOTIFIER_EMAIL_ENABLED:
        print("[notifier] Email disabled in config — skipping all emails")
        return

    print("[notifier] Sending email 1/3 — Portfolio Monitor…")
    send_portfolio_email(alerts, valuations, analytics, macro, news_results, as_of)

    print("[notifier] Sending email 2/3 — Greeks & Technical…")
    send_greeks_email(valuations, analytics, chain_diffs, as_of)

    print("[notifier] Sending email 3/3 — Concentrated Thesis Strategy…")
    send_strategy_email(as_of)


# Keep old signature working for any code that calls maybe_send directly
def maybe_send(alerts: list, as_of: str) -> None:
    if config.NOTIFIER_EMAIL_ENABLED:
        _send(
            subject=f"Portfolio Monitor {as_of}",
            html=_build_html_legacy(alerts, as_of),
            plain=_build_plain_legacy(alerts, as_of),
        )


def _build_html_legacy(alerts: list, as_of: str) -> str:
    high = [a for a in alerts if a.severity == "high"]
    warn = [a for a in alerts if a.severity == "warn"]
    info = [a for a in alerts if a.severity == "info"]
    rows = ""
    for group, color, icon in [(high,"#f85149","🔴"),(warn,"#e3b341","🟡"),(info,"#388bfd","🔵")]:
        for a in group:
            rows += f'<tr><td style="padding:6px 12px;font-family:monospace;font-size:13px;color:{color}">{icon} {a.message}</td></tr>'
    return f'<html><body style="background:#0d1117"><table style="max-width:680px;margin:auto;background:#161b22;border:1px solid #30363d"><tr><td style="padding:16px;color:#e6edf3;font-size:18px;font-weight:700">📊 Portfolio Monitor — {as_of}</td></tr>{rows or "<tr><td style=color:#3fb950>✓ No alerts</td></tr>"}</table></body></html>'


def _build_plain_legacy(alerts: list, as_of: str) -> str:
    lines = [f"Portfolio Monitor — {as_of}", ""]
    for a in alerts:
        lines.append(f"[{a.severity.upper()}] {a.message}")
    return "\n".join(lines) if alerts else f"Portfolio Monitor — {as_of}\nNo alerts."
