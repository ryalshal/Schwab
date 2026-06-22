"""
Concentrated Thesis Strategy Dashboard.
Tabs: Overview · Risk · Scenarios · Catalysts · Framework
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

st.set_page_config(
    page_title="Strategy Dashboard",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
  .strategy-header { font-size:11px; letter-spacing:3px; color:#6b7280; text-transform:uppercase; }
  .strategy-title  { font-size:32px; font-weight:700; color:#f9fafb; margin:4px 0 8px; }
  .strategy-sub    { font-size:14px; color:#9ca3af; }
  .stDataFrame td  { font-size:13px; }
  .stDataFrame th  { font-size:11px; color:#9ca3af; text-transform:uppercase; letter-spacing:1px; }
  [data-testid="metric-container"] { background:#111827; border:1px solid #1f2937;
                                      border-radius:8px; padding:12px 16px; }
  [data-testid="stMetricLabel"]    { font-size:10px; color:#6b7280; letter-spacing:1px; text-transform:uppercase; }
  [data-testid="stMetricValue"]    { font-size:22px; font-weight:700; }
  [data-testid="stMetricDelta"]    { font-size:12px; }
  .section-label { font-size:10px; letter-spacing:2px; color:#6b7280; text-transform:uppercase;
                   margin-bottom:12px; border-bottom:1px solid #1f2937; padding-bottom:8px; }
  .archetype-card { background:#111827; border:1px solid #1f2937; border-radius:12px;
                    padding:20px; margin-bottom:12px; }
  .archetype-title { font-size:16px; font-weight:600; color:#f9fafb; }
  .rule-card { background:#111827; border:1px solid #1f2937; border-radius:10px;
               padding:16px 20px; margin-bottom:10px; display:flex; gap:16px; align-items:flex-start; }
  .rule-num  { background:#1f2937; color:#6366f1; border-radius:50%; width:28px; height:28px;
               display:flex; align-items:center; justify-content:center;
               font-weight:700; font-size:13px; flex-shrink:0; }
  .exit-row  { display:flex; justify-content:space-between; align-items:center;
               padding:12px 0; border-bottom:1px solid #1f2937; }
  .corr-badge-low     { background:#064e3b; color:#6ee7b7; padding:2px 10px; border-radius:4px; font-size:11px; }
  .corr-badge-vlow    { background:#1e3a5f; color:#93c5fd; padding:2px 10px; border-radius:4px; font-size:11px; }
  .corr-badge-med     { background:#3d2b00; color:#fcd34d; padding:2px 10px; border-radius:4px; font-size:11px; }
  .corr-badge-none    { background:#1f2937; color:#6b7280; padding:2px 10px; border-radius:4px; font-size:11px; }
  .lesson-row { display:flex; gap:12px; margin-bottom:10px; }
  .lesson-no  { background:#2d1215; color:#f87171; padding:8px 14px; border-radius:8px;
                font-size:12px; flex:1; }
  .lesson-yes { background:#052e16; color:#86efac; padding:8px 14px; border-radius:8px;
                font-size:12px; flex:1; }
  .process-step { display:flex; gap:16px; margin-bottom:16px; align-items:flex-start; }
  .step-circle  { background:#312e81; color:#a5b4fc; border-radius:50%; width:32px; height:32px;
                  display:flex; align-items:center; justify-content:center;
                  font-weight:700; font-size:14px; flex-shrink:0; }
  .disclaimer { font-size:10px; color:#4b5563; text-align:center; padding:16px; letter-spacing:1px; }
</style>
""", unsafe_allow_html=True)

# ─── Load positions ───────────────────────────────────────────────────────────

STRATEGY_FILE = Path("strategy_positions.json")

@st.cache_data(ttl=60)
def _load() -> list[dict]:
    if not STRATEGY_FILE.exists():
        return []
    with open(STRATEGY_FILE, encoding="utf-8") as f:
        return json.load(f)

positions = _load()
if not positions:
    st.error("strategy_positions.json not found.")
    st.stop()

df = pd.DataFrame(positions)

# ─── Book constants ───────────────────────────────────────────────────────────

TOTAL_BOOK   = 7290.0
cash_reserve = 900.0
deployed     = TOTAL_BOOK - cash_reserve

# Scale position sizes to fit the book
raw_total = df["size"].sum()
if raw_total > 0:
    df["size"] = (df["size"] / raw_total * deployed).round(0)

df["pct_port"] = df["size"] / TOTAL_BOOK * 100

calls_val  = df[df["vehicle"] == "Calls"]["size"].sum()
shares_val = df[df["vehicle"] == "Shares"]["size"].sum()

PALETTE = ["#6366f1","#06b6d4","#10b981","#f59e0b","#ef4444","#8b5cf6","#f97316","#ec4899","#84cc16"]

# ─── Header ───────────────────────────────────────────────────────────────────

st.markdown('<p class="strategy-header">Investment Framework</p>', unsafe_allow_html=True)
st.markdown('<h1 class="strategy-title">The Concentrated Thesis Strategy</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="strategy-sub">Semi-aggressive options + shares portfolio targeting 2-3x on $8,100 over 6-12 months. '
    'Concentrated positions with structural thesis backing. Mix of LEAPs, catalyst calls, and shares '
    'based on each name\'s specific setup.</p>',
    unsafe_allow_html=True,
)
st.markdown("---")

# ─── KPI strip ────────────────────────────────────────────────────────────────

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total Book",   f"${TOTAL_BOOK:,.0f}")
k2.metric("Deployed",     f"${deployed:,.0f}",     delta=f"{deployed/TOTAL_BOOK*100:.0f}% of book")
k3.metric("Cash Reserve", f"${cash_reserve:,.0f}", delta=f"{cash_reserve/TOTAL_BOOK*100:.0f}% dry powder")
k4.metric("Positions",    f"{len(positions)}")
k5.metric("Options Book", f"${calls_val:,.0f}",    delta=f"{calls_val/TOTAL_BOOK*100:.0f}% of book")
k6.metric("Shares Book",  f"${shares_val:,.0f}",   delta=f"{shares_val/TOTAL_BOOK*100:.0f}% of book")

st.markdown("---")

# ─── Tabs ─────────────────────────────────────────────────────────────────────

tab_ov, tab_risk, tab_scen, tab_cat, tab_fw = st.tabs(
    ["OVERVIEW", "RISK", "SCENARIOS", "CATALYSTS", "FRAMEWORK"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════

with tab_ov:
    col_charts, col_table = st.columns([1, 1.8])

    with col_charts:
        st.markdown('<p class="section-label">Allocation by Ticker</p>', unsafe_allow_html=True)
        ticker_alloc = df.groupby("ticker")["size"].sum().reset_index()
        ticker_alloc["pct"] = ticker_alloc["size"] / TOTAL_BOOK * 100

        fig_ticker = go.Figure(go.Pie(
            labels=ticker_alloc["ticker"], values=ticker_alloc["pct"], hole=0.62,
            marker=dict(colors=PALETTE[:len(ticker_alloc)], line=dict(color="#0f172a", width=2)),
            textinfo="percent", textfont=dict(size=11, color="#f9fafb"),
            hovertemplate="<b>%{label}</b><br>%{value:.1f}%<br>$%{customdata:,.0f}<extra></extra>",
            customdata=ticker_alloc["size"],
        ))
        fig_ticker.update_layout(
            height=240, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
            legend=dict(font=dict(size=10, color="#9ca3af"), orientation="h", y=-0.15, x=0.5, xanchor="center"),
            font=dict(color="#9ca3af"),
        )
        st.plotly_chart(fig_ticker, use_container_width=True, key="ticker_donut")

        st.markdown('<p class="section-label" style="margin-top:20px">Calls vs Shares vs Cash</p>',
                    unsafe_allow_html=True)
        veh_df = pd.DataFrame({
            "Vehicle": ["Options", "Shares", "Cash"],
            "Value":   [calls_val, shares_val, cash_reserve],
        })
        veh_df["pct"] = veh_df["Value"] / TOTAL_BOOK * 100

        fig_veh = go.Figure(go.Pie(
            labels=veh_df["Vehicle"], values=veh_df["pct"], hole=0.62,
            marker=dict(colors=["#6366f1","#10b981","#374151"], line=dict(color="#0f172a", width=2)),
            textinfo="percent", textfont=dict(size=11, color="#f9fafb"),
        ))
        fig_veh.update_layout(
            height=220, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(font=dict(size=10, color="#9ca3af"), orientation="h", y=-0.15, x=0.5, xanchor="center"),
            font=dict(color="#9ca3af"),
        )
        st.plotly_chart(fig_veh, use_container_width=True, key="vehicle_donut")

    with col_table:
        st.markdown('<p class="section-label">All Positions</p>', unsafe_allow_html=True)
        tbl = df[["id","vehicle","sector","size","pct_port","entry","dte","thesis"]].copy()
        tbl.columns = ["Position","Vehicle","Sector","Size","% Port","Entry","DTE","Thesis"]
        tbl["Size"]   = tbl["Size"].apply(lambda x: f"${x:,.0f}")
        tbl["% Port"] = tbl["% Port"].apply(lambda x: f"{x:.1f}%")
        tbl["Entry"]  = tbl["Entry"].apply(lambda x: f"${x:g}")
        tbl["DTE"]    = tbl["DTE"].apply(lambda x: str(int(x)) if pd.notna(x) and x else "—")
        st.dataframe(tbl, use_container_width=True, hide_index=True, height=420,
                     column_config={"Vehicle": st.column_config.Column(width="small"),
                                    "DTE":     st.column_config.Column(width="small"),
                                    "% Port":  st.column_config.Column(width="small")})

    # Radar
    st.markdown('<p class="section-label" style="margin-top:28px">Thesis Quality Radar</p>',
                unsafe_allow_html=True)
    radar_cols   = ["conviction","upside","downside_protection","catalyst_clarity","thesis_strength","liquidity"]
    radar_labels = ["Conviction","Upside","Downside Protection","Catalyst Clarity","Thesis Strength","Liquidity"]
    top4 = df.nlargest(4, "size")
    RADAR_COLORS = ["#6366f1","#06b6d4","#8b5cf6","#10b981"]

    fig_radar = go.Figure()
    for i, (_, row) in enumerate(top4.iterrows()):
        vals = [row[c] for c in radar_cols] + [row[radar_cols[0]]]
        c = RADAR_COLORS[i]
        r,g,b_ = int(c[1:3],16), int(c[3:5],16), int(c[5:],16)
        fig_radar.add_trace(go.Scatterpolar(
            r=vals, theta=radar_labels+[radar_labels[0]], fill="toself",
            fillcolor=f"rgba({r},{g},{b_},0.15)",
            line=dict(color=c, width=2), name=row["ticker"],
        ))
    fig_radar.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=True, range=[0,10], gridcolor="#1f2937",
                            tickfont=dict(size=9, color="#4b5563"), tickvals=[2,4,6,8,10]),
            angularaxis=dict(gridcolor="#1f2937", linecolor="#1f2937",
                             tickfont=dict(size=11, color="#9ca3af")),
        ),
        paper_bgcolor="rgba(0,0,0,0)", height=380,
        margin=dict(l=60, r=60, t=20, b=20),
        legend=dict(font=dict(size=11, color="#9ca3af"), orientation="h", y=-0.08, x=0.5, xanchor="center"),
    )
    st.plotly_chart(fig_radar, use_container_width=True, key="radar")
    st.markdown('<p class="disclaimer">NOT FINANCIAL ADVICE — ALL PROBABILITIES ARE ESTIMATES — POSITION SIZE TO WHAT YOU CAN LOSE</p>',
                unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# RISK
# ═══════════════════════════════════════════════════════════════════════════════

with tab_risk:
    st.markdown('<p class="section-label">Portfolio Risk Profile</p>', unsafe_allow_html=True)
    r1,r2,r3,r4 = st.columns(4)
    weighted_conv   = (df["conviction"] * df["size"]).sum() / df["size"].sum()
    avg_dte_options = df[df["dte"].notna()]["dte"].mean()
    r1.metric("Avg Conviction (weighted)", f"{weighted_conv:.1f} / 10")
    r2.metric("Avg DTE (options)",         f"{avg_dte_options:.0f}d" if not math.isnan(avg_dte_options) else "N/A")
    r3.metric("Largest Single Position",   f"{df['pct_port'].max():.1f}%")
    r4.metric("Options Exposure",          f"{calls_val/TOTAL_BOOK*100:.0f}% of book")

    st.markdown("---")
    rc1, rc2 = st.columns(2)

    with rc1:
        st.markdown('<p class="section-label">Position Sizing vs Conviction</p>', unsafe_allow_html=True)
        fig_conv = px.scatter(
            df, x="conviction", y="pct_port", size="size", color="vehicle", text="ticker",
            color_discrete_map={"Calls":"#6366f1","Shares":"#10b981"},
            labels={"conviction":"Conviction (1-10)","pct_port":"% of Book"}, height=300,
        )
        fig_conv.update_traces(textposition="top center", textfont=dict(size=10, color="#9ca3af"))
        fig_conv.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,24,39,1)",
                               margin=dict(l=0,r=0,t=10,b=0), font=dict(color="#9ca3af"),
                               legend=dict(font=dict(size=10,color="#9ca3af")),
                               xaxis=dict(gridcolor="#1f2937"), yaxis=dict(gridcolor="#1f2937"))
        st.plotly_chart(fig_conv, use_container_width=True, key="conviction_scatter")

    with rc2:
        st.markdown('<p class="section-label">Downside Protection by Position</p>', unsafe_allow_html=True)
        fig_dd = px.bar(
            df.sort_values("downside_protection"), x="id", y="downside_protection", color="vehicle",
            color_discrete_map={"Calls":"#6366f1","Shares":"#10b981"},
            labels={"id":"","downside_protection":"Protection Score (1-10)"}, height=300,
        )
        fig_dd.add_hline(y=5, line_dash="dash", line_color="#f59e0b", annotation_text="Minimum Threshold")
        fig_dd.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,24,39,1)",
                             margin=dict(l=0,r=0,t=10,b=0), font=dict(color="#9ca3af"),
                             legend=dict(font=dict(size=10,color="#9ca3af")),
                             xaxis=dict(gridcolor="#1f2937",tickangle=-30,tickfont=dict(size=9)),
                             yaxis=dict(gridcolor="#1f2937"))
        st.plotly_chart(fig_dd, use_container_width=True, key="dd_bar")

    risk_df = df[["id","vehicle","size","pct_port","conviction","downside_protection","catalyst_clarity","bear_case","entry"]].copy()
    risk_df["Max Loss ($)"] = ((risk_df["entry"] - risk_df["bear_case"]) / risk_df["entry"] * risk_df["size"]).apply(lambda x: f"${x:,.0f}")
    risk_df["size"]     = risk_df["size"].apply(lambda x: f"${x:,.0f}")
    risk_df["pct_port"] = risk_df["pct_port"].apply(lambda x: f"{x:.1f}%")
    risk_df.columns = ["Position","Vehicle","Size","% Port","Conviction","Downside Prot.","Catalyst Clarity","Bear Case","Entry","Max Loss (est.)"]
    st.dataframe(risk_df, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_scen:
    st.markdown('<p class="section-label">Scenario Analysis</p>', unsafe_allow_html=True)
    s1,s2,s3 = st.columns(3)
    bull_val = sum(r["bull_case"]/r["entry"]*r["size"] for _,r in df.iterrows())
    base_val = sum(r["base_case"]/r["entry"]*r["size"] for _,r in df.iterrows())
    bear_val = sum(r["bear_case"]/r["entry"]*r["size"] for _,r in df.iterrows())
    total_entry_val = df["size"].sum()
    s1.metric("Bull Case", f"${bull_val+cash_reserve:,.0f}", delta=f"+{(bull_val-total_entry_val)/total_entry_val*100:.0f}% return")
    s2.metric("Base Case", f"${base_val+cash_reserve:,.0f}", delta=f"+{(base_val-total_entry_val)/total_entry_val*100:.0f}% return")
    s3.metric("Bear Case", f"${bear_val+cash_reserve:,.0f}", delta=f"{(bear_val-total_entry_val)/total_entry_val*100:.0f}% return", delta_color="inverse")

    st.markdown("---")
    scen_rows = [{"Position":r["id"],
                  "Bull %":(r["bull_case"]/r["entry"]-1)*100,
                  "Base %":(r["base_case"]/r["entry"]-1)*100,
                  "Bear %":(r["bear_case"]/r["entry"]-1)*100,
                  "Size $":r["size"]} for _,r in df.iterrows()]
    scen_df = pd.DataFrame(scen_rows).sort_values("Bull %", ascending=False)

    fig_scen = go.Figure()
    fig_scen.add_trace(go.Bar(name="Bull", x=scen_df["Position"], y=scen_df["Bull %"], marker_color="#10b981"))
    fig_scen.add_trace(go.Bar(name="Base", x=scen_df["Position"], y=scen_df["Base %"], marker_color="#6366f1"))
    fig_scen.add_trace(go.Bar(name="Bear", x=scen_df["Position"], y=scen_df["Bear %"], marker_color="#ef4444"))
    fig_scen.add_hline(y=0, line_color="#4b5563", line_width=1)
    fig_scen.update_layout(
        barmode="group", height=360,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,24,39,1)",
        margin=dict(l=0,r=0,t=10,b=0), font=dict(color="#9ca3af"),
        legend=dict(font=dict(size=10,color="#9ca3af")),
        xaxis=dict(gridcolor="#1f2937",tickangle=-30,tickfont=dict(size=9)),
        yaxis=dict(gridcolor="#1f2937",ticksuffix="%"),
    )
    st.plotly_chart(fig_scen, use_container_width=True, key="scenario_bars")

    disp = scen_df.copy()
    disp["Size $"] = disp["Size $"].apply(lambda x: f"${x:,.0f}")
    for col in ["Bull %","Base %","Bear %"]:
        disp[col] = disp[col].apply(lambda x: f"+{x:.0f}%" if x >= 0 else f"{x:.0f}%")
    st.dataframe(disp, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# CATALYSTS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_cat:
    st.markdown('<p class="section-label">Upcoming Catalysts</p>', unsafe_allow_html=True)
    today = date.today()
    all_cats = []
    for _, row in df.iterrows():
        for cat in (row.get("catalysts") or []):
            try:
                cat_date   = date.fromisoformat(cat["date"])
                days_away  = (cat_date - today).days
                all_cats.append({
                    "Date": cat["date"], "Days Away": days_away,
                    "Ticker": row["ticker"], "Position": row["id"],
                    "Event": cat["event"], "Expected Move": cat.get("expected_move","—"),
                    "Vehicle": row["vehicle"], "Size": row["size"], "Thesis": row["thesis"],
                })
            except (ValueError, KeyError):
                pass

    cats_df = pd.DataFrame(all_cats).sort_values("Days Away") if all_cats else pd.DataFrame()

    if not cats_df.empty:
        fig_cat = go.Figure()
        for veh, color in [("Calls","#6366f1"),("Shares","#10b981")]:
            sub = cats_df[cats_df["Vehicle"] == veh]
            if sub.empty:
                continue
            fig_cat.add_trace(go.Scatter(
                x=sub["Date"], y=sub["Ticker"], mode="markers+text",
                marker=dict(size=14, color=color, symbol="diamond"),
                text=sub["Event"].apply(lambda e: e[:22]),
                textposition="top center", textfont=dict(size=9, color="#9ca3af"),
                name=veh,
                hovertemplate="<b>%{y}</b><br>%{x}<br>%{customdata}<extra></extra>",
                customdata=sub["Event"],
            ))
        fig_cat.update_layout(
            height=320, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,24,39,1)",
            margin=dict(l=0,r=0,t=10,b=0), font=dict(color="#9ca3af"),
            xaxis=dict(gridcolor="#1f2937",tickfont=dict(color="#9ca3af")),
            yaxis=dict(gridcolor="#1f2937",tickfont=dict(color="#9ca3af")),
            legend=dict(font=dict(size=10,color="#9ca3af")),
        )
        st.plotly_chart(fig_cat, use_container_width=True, key="catalyst_timeline")

        disp_cat = cats_df.copy()
        disp_cat["Size"] = disp_cat["Size"].apply(lambda x: f"${x:,.0f}")
        disp_cat["Days Away"] = disp_cat["Days Away"].apply(
            lambda x: f"{'🔴 ' if x < 14 else '🟠 ' if x < 45 else '🟢 '}{x}d")
        st.dataframe(
            disp_cat[["Date","Days Away","Ticker","Event","Expected Move","Vehicle","Size","Thesis"]],
            use_container_width=True, hide_index=True,
        )

# ═══════════════════════════════════════════════════════════════════════════════
# FRAMEWORK
# ═══════════════════════════════════════════════════════════════════════════════

with tab_fw:

    # ── Philosophy ────────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Philosophy — The Core Idea</p>', unsafe_allow_html=True)
    ph1,ph2,ph3 = st.columns(3)
    with ph1:
        st.info("**Conviction Over Diversification**\n\n3-5 core positions with deep research, not 15 shallow bets. Each position has a specific thesis, catalyst, and exit plan.")
    with ph2:
        st.warning("**Vehicle Matches Thesis**\n\nOptions for leverage on high-conviction calls with catalyst paths. Shares for names with structural downside protection or no viable options chain.")
    with ph3:
        st.success("**Cash Is a Weapon**\n\n15-30% cash reserve isn't idle — it's optionality. Deploy on post-earnings IV crush, panic selloffs, and overreactions. This is where the edge compounds.")

    st.markdown("---")

    # ── Vehicle Selection Framework ───────────────────────────────────────────
    st.markdown('<p class="section-label">When to Use Calls vs Shares — Vehicle Selection Framework</p>',
                unsafe_allow_html=True)
    fw1, fw2 = st.columns([1, 1.4])
    with fw1:
        st.dataframe(pd.DataFrame({
            "Vehicle":  ["LEAP Calls","Short Calls","Shares","Cash"],
            "Leverage": ["8-12x","15-30x","1x","—"],
            "Theta":    ["Low","High","None","—"],
            "Best For": [
                "High-conviction thesis trades with 6-12 month catalysts",
                "Binary catalyst trades with 1-3 month window",
                "Pentagon-floor stocks, illiquid microcaps, dividend plays",
                "Post-earnings deployment, panic buying, optionality",
            ],
        }), use_container_width=True, hide_index=True)
    with fw2:
        target_df = pd.DataFrame({
            "Category": ["LEAP Calls 40%","Short Calls 20%","Shares (Mid) 18%","Shares (Micro) 7%","Cash Reserve 15%"],
            "Value": [40,20,18,7,15],
        })
        fig_target = go.Figure(go.Pie(
            labels=target_df["Category"], values=target_df["Value"], hole=0.55,
            marker=dict(colors=["#6366f1","#8b5cf6","#10b981","#f59e0b","#374151"],
                        line=dict(color="#0f172a", width=2)),
            textinfo="percent", textfont=dict(size=10, color="#f9fafb"),
        ))
        fig_target.update_layout(
            height=260, margin=dict(l=0,r=0,t=0,b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(font=dict(size=9,color="#9ca3af"),orientation="h",y=-0.2,x=0.5,xanchor="center"),
            font=dict(color="#9ca3af"),
        )
        st.plotly_chart(fig_target, use_container_width=True, key="target_alloc")

    # Decision flow
    st.markdown("---")
    st.markdown('<p class="section-label">Calls or Shares? — Decision Flow</p>', unsafe_allow_html=True)
    d1,d2,d3 = st.columns(3)
    with d1:
        st.markdown("**Does the stock have liquid options?**\n\n✅ Yes → Consider calls\n❌ No → Buy shares\n\n*Ex: OSS, SLS — no viable options chain*")
    with d2:
        st.markdown("**Is IV below 65% (fair premium)?**\n\n✅ Yes → Calls are cost-effective\n❌ No → Shares or wait for IV crush\n\n*Check IV rank before buying calls*")
    with d3:
        st.markdown("**Does downside have structural protection?**\n\n✅ Yes → Shares capture the floor\n❌ No → Calls OK — accept binary risk\n\n*Ex: MP Pentagon floor → shares preserve it*")

    st.markdown("---")

    # ── Five Archetypes ───────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Position Classification — Five Thesis Archetypes</p>',
                unsafe_allow_html=True)
    archetypes = [
        {
            "icon":"↺","name":"Value Mean Reversion","tag":"LEAP Calls (8-12 months)","pct":"30-50% of book",
            "color":"#6366f1",
            "desc":"Stock crashed on narrative, not fundamentals. Buy LEAPs when beaten-down, hold through recovery.",
            "example":"NOW — down 60% on SaaSocalypse fear despite beat-and-raise. Jensen validated. Institutions accumulating 400%+.",
            "signals":["P/E compressed to floor","Institutional buying accelerating","Revenue still growing","Catalysts ahead"],
        },
        {
            "icon":"/","name":"Momentum Re-rating","tag":"Mix of LEAPs + Short Calls","pct":"20-35% of book",
            "color":"#06b6d4",
            "desc":"Market reclassifying stock from old identity to new identity. Multiple expansion drives returns.",
            "example":"NOK — telecom 2.6x P/S re-rating to AI networking 5-15x P/S. Nvidia $1B + Anduril + AI/Cloud +49%.",
            "signals":["P/S gap vs new peer set","Strategic partner validation","Revenue mix shifting","Analyst upgrades chasing"],
        },
        {
            "icon":"⚡","name":"Catalyst Binary","tag":"Short-dated Calls (2-5 months)","pct":"5-10% per position",
            "color":"#f59e0b",
            "desc":"Specific dated event creates asymmetric setup. Enter pre-catalyst or post-earnings on IV crush.",
            "example":"HIMS — post-earnings IV crush entry. NBIS — pre-earnings momentum with 18.79% implied move.",
            "signals":["Earnings within 90 days","IV rank below 50%","Clear binary outcome","Options liquid"],
        },
        {
            "icon":"🏛","name":"Structural Shift","tag":"Shares (6-18 months)","pct":"5-15% per position",
            "color":"#10b981",
            "desc":"Policy, regulation, or secular change creates multi-year tailwind. Use shares for floor protection.",
            "example":"MP — only domestic rare earth producer. Pentagon floor. China ban creates structural supply squeeze.",
            "signals":["Policy tailwind confirmed","Structural moat","Options illiquid or too expensive","Dividend / buyback optionality"],
        },
        {
            "icon":"🎲","name":"Microcap Lottery","tag":"Common Shares (options illiquid)","pct":"2-5% per position",
            "color":"#8b5cf6",
            "desc":"Tiny position in high-variance names. Sized for total loss. Captures fat-tail upside if thesis works.",
            "example":"SLS — biotech with binary FDA outcomes. OSCR — ACA enrollment story with growth inflection.",
            "signals":["Sized for 100% loss","No options available","Binary outcome","Uncorrelated to core book"],
        },
    ]
    for arch in archetypes:
        c = arch["color"]
        r,g,b_ = int(c[1:3],16), int(c[3:5],16), int(c[5:],16)
        st.markdown(f"""
<div class="archetype-card" style="border-left:3px solid {c}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
    <div><span style="font-size:18px;color:{c};margin-right:8px">{arch['icon']}</span>
         <span class="archetype-title">{arch['name']}</span></div>
    <div>
      <span style="background:rgba({r},{g},{b_},0.15);color:{c};padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600">{arch['tag']}</span>
      <span style="background:#1f2937;color:#9ca3af;padding:2px 10px;border-radius:4px;font-size:11px;margin-left:6px">{arch['pct']}</span>
    </div>
  </div>
  <p style="color:#d1d5db;font-size:13px;margin:0 0 8px">{arch['desc']}</p>
  <p style="color:#6b7280;font-size:12px;margin:0 0 10px"><b>Example:</b> {arch['example']}</p>
  <div>{''.join(f'<span style="background:rgba({r},{g},{b_},0.1);color:{c};padding:2px 8px;border-radius:4px;font-size:11px;margin:0 4px 4px 0;display:inline-block">{s}</span>' for s in arch['signals'])}</div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Entry Discipline ──────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Execution Rules — Entry Discipline</p>', unsafe_allow_html=True)
    rules = [
        ("Buy overreactions, not momentum peaks",
         "NOW at $87 after 60% crash = overreaction entry. NOK was harder — momentum entry worked because of fundamental backing (Nvidia $1B)."),
        ("Match vehicle to thesis, not to excitement",
         "MP shares (not calls) because Pentagon floor protects shares. NOK calls because options are cheap at 2.6x P/S with re-rating catalyst."),
        ("Stage entries around catalyst calendar",
         "Deploy 60% pre-catalyst, 40% post-catalyst. Gives you exposure to upside while preserving capital for better post-event entry."),
        ("Use limit orders — never pay the ask on LEAPs",
         "NOW calls: saved $420 starting at midpoint. Work limits patiently. Market makers fill between bid/ask within 10-15 minutes."),
        ("Cash is a position, not a failure",
         "30% cash reserve enables post-earnings deployment at crushed IV. This is where the real edge compounds — buying when others are forced sellers."),
    ]
    for i, (title, detail) in enumerate(rules, 1):
        st.markdown(f"""
<div class="rule-card">
  <div class="rule-num">{i}</div>
  <div>
    <div style="font-weight:600;color:#f9fafb;margin-bottom:4px">{title}</div>
    <div style="color:#6b7280;font-size:12px">{detail}</div>
  </div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Exit Framework ────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">Profit Taking & Loss Management — Exit Framework</p>',
                unsafe_allow_html=True)
    exits = [
        ("#10b981","🟢 +100% gain on any position", "Sell 30% to lock in profit"),
        ("#10b981","🟢 +200% gain",                  "Sell another 30%"),
        ("#06b6d4","🔵 Hold final 40%",               "Let it ride for full thesis play-out"),
        ("#ef4444","🔴 -50% on thesis break",         "Cut the position entirely"),
        ("#f59e0b","🟡 -50% on no news",              "Hold — theta + volatility, not thesis failure"),
        ("#f59e0b","🟡 Earnings in 2 days",           "Decide: exit pre-print or hold through binary"),
        ("#f59e0b","🟡 30 DTE on short calls",        "Evaluate: sell for salvage or hold for catalyst"),
    ]
    for color, label, action in exits:
        st.markdown(f"""
<div class="exit-row">
  <span style="color:{color};font-weight:600;font-size:13px">{label}</span>
  <span style="color:#9ca3af;font-size:12px">{action}</span>
</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Correlation & Diversification ─────────────────────────────────────────
    st.markdown('<p class="section-label">Correlation & Diversification — Why This Mix Works</p>',
                unsafe_allow_html=True)
    st.markdown("""<p style="color:#9ca3af;font-size:13px;margin-bottom:16px">
The portfolio combines positions with low-to-zero correlation. When tech sells off, MP (beta 0.45,
Pentagon floor) holds value. When commodities are flat, NOW and NOK capture AI narrative.
No single macro event destroys all positions simultaneously.</p>""", unsafe_allow_html=True)

    corr_rows = [
        ("NOW ↔ NOK","low","Low","SaaS recovery vs telecom re-rating — different drivers"),
        ("NOW ↔ MP","vlow","Very Low","Software vs commodity — uncorrelated sectors"),
        ("NOK ↔ NBIS","med","Medium","Both AI infrastructure — move together on AI capex news"),
        ("NOW ↔ HIMS","low","Low","Enterprise vs consumer — different end markets"),
        ("MP ↔ SLS","none","None","Rare earth vs biotech — zero shared drivers"),
    ]
    for pair, badge_cls, badge_label, why in corr_rows:
        st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;padding:10px 0;border-bottom:1px solid #1f2937">
  <span style="color:#f9fafb;font-weight:600;min-width:120px">{pair}</span>
  <span class="corr-badge-{badge_cls}">{badge_label}</span>
  <span style="color:#6b7280;font-size:12px">{why}</span>
</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── The Process ───────────────────────────────────────────────────────────
    st.markdown('<p class="section-label">From Research to Exit — The Process</p>', unsafe_allow_html=True)
    steps = [
        ("1","Research","Week 1-2",
         "Deep fundamental + quantitative analysis. No analyst PTs. Revenue trajectory, margins, catalysts, IV environment."),
        ("2","Selection","Week 2",
         "Pick 3-5 high-conviction names across uncorrelated sectors. Vehicle selection (calls vs shares) per name."),
        ("3","Entry","Week 2-3",
         "Stage entries around catalyst calendar. Limit orders. 60/40 pre/post-catalyst split."),
        ("4","Monitoring","Ongoing",
         "Watch catalysts unfold. Don't check daily P&L. Evaluate thesis, not price. Deploy cash reserve on overreactions."),
        ("5","Exits","Per rules",
         "Scale out at +100%/+200%. Cut on thesis break. Let winners run. Don't add to losers without thesis re-evaluation."),
    ]
    for num, title, timing, detail in steps:
        st.markdown(f"""
<div class="process-step">
  <div class="step-circle">{num}</div>
  <div>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
      <span style="font-weight:600;color:#f9fafb">{title}</span>
      <span style="background:#1f2937;color:#9ca3af;padding:1px 8px;border-radius:4px;font-size:11px">{timing}</span>
    </div>
    <div style="color:#6b7280;font-size:12px">{detail}</div>
  </div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Hard-Won Lessons ──────────────────────────────────────────────────────
    st.markdown('<p class="section-label">What We Learned Building This Book — Hard-Won Lessons</p>',
                unsafe_allow_html=True)
    lessons = [
        ("❌ Analyst PTs are price ceilings",
         "✅ PTs lag price — they're trailing indicators, not predictions"),
        ("❌ More OTM = higher returns",
         "✅ Sweet spot is 1-2 strikes OTM — beyond that, probability kills expected value"),
        ("❌ Diversify across 10+ names",
         "✅ 3-5 concentrated positions with deep research outperform 10 shallow ones"),
        ("❌ Don't chase momentum stocks",
         "✅ Fundamentally-backed momentum works — INTC, NOK, IREN all kept running"),
        ("❌ IV doesn't matter for LEAPs",
         "✅ High IV on low-beta stocks (MP at 70%) makes options negative EV — use shares instead"),
        ("❌ Buy pre-earnings for maximum gain",
         "✅ Post-earnings entry at crushed IV often has better risk-adjusted return"),
    ]
    for no, yes in lessons:
        st.markdown(f"""
<div class="lesson-row">
  <div class="lesson-no">{no}</div>
  <div class="lesson-yes">{yes}</div>
</div>""", unsafe_allow_html=True)

    st.markdown('<p class="disclaimer">NOT FINANCIAL ADVICE — ALL PROBABILITIES ARE ESTIMATES — POSITION SIZE TO WHAT YOU CAN LOSE</p>',
                unsafe_allow_html=True)
