import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


DATABASE_PATH = Path("database/electricity_trading.db")


st.set_page_config(
    page_title="PowerFlow — Electricity Trading Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

    /* ── Reset & Base ───────────────────────────────────────────── */
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif;
    }

    .stApp {
        background-color: #060B14;
        background-image:
            linear-gradient(rgba(37,99,235,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(37,99,235,0.03) 1px, transparent 1px);
        background-size: 40px 40px;
    }

    .block-container {
        padding: 1.5rem 2.5rem 3rem 2.5rem;
        max-width: 1600px;
    }

    /* ── Sidebar ────────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background-color: #060B14;
        border-right: 1px solid #1a2744;
        padding-top: 0;
    }

    section[data-testid="stSidebar"] > div {
        padding-top: 0;
    }

    /* Sidebar header brand bar */
    .sidebar-brand {
        background: linear-gradient(135deg, #0f1f3d 0%, #0a1628 100%);
        border-bottom: 1px solid #1a2744;
        padding: 20px 16px 18px 16px;
        margin-bottom: 16px;
    }

    .sidebar-brand .brand-logo {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.4rem;
        font-weight: 600;
        color: #F9FAFB;
        letter-spacing: 0.08em;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .sidebar-brand .brand-logo .bolt {
        color: #2563EB;
        font-size: 1.5rem;
    }

    .sidebar-brand .brand-tagline {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        color: #4B6A9B;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        margin-top: 4px;
    }

    /* Nav section label */
    .nav-section-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.6rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #2563EB;
        padding: 0 16px;
        margin: 12px 0 8px 0;
    }

    /* Radio nav items */
    div[data-testid="stRadio"] label {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 0.85rem;
        font-weight: 400;
        color: #7A90B8;
        padding: 6px 12px;
        border-radius: 4px;
        transition: all 0.15s ease;
        cursor: pointer;
    }

    div[data-testid="stRadio"] label:hover {
        color: #F9FAFB;
        background-color: #0f1f3d;
    }

    div[data-testid="stRadio"] [data-checked="true"] label {
        color: #F9FAFB;
        font-weight: 600;
    }

    /* Sidebar metadata */
    .sidebar-meta {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 16px;
        border-top: 1px solid #1a2744;
        background-color: #060B14;
    }

    .sidebar-meta-item {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        color: #2D4A7A;
        margin-bottom: 4px;
        display: flex;
        justify-content: space-between;
    }

    .sidebar-meta-item span {
        color: #4B6A9B;
    }

    /* ── Page Header ────────────────────────────────────────────── */
    .page-header {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        margin-bottom: 1.75rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid #1a2744;
    }

    .page-header-left .page-eyebrow {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #2563EB;
        margin-bottom: 6px;
    }

    .page-header-left h1 {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 1.6rem;
        font-weight: 700;
        color: #F9FAFB;
        letter-spacing: -0.02em;
        margin: 0;
        line-height: 1;
    }

    .page-header-right .timestamp-badge {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        color: #4B6A9B;
        background: #0a1628;
        border: 1px solid #1a2744;
        padding: 6px 12px;
        border-radius: 4px;
        letter-spacing: 0.05em;
    }

    /* ── Metric Cards ───────────────────────────────────────────── */
    div[data-testid="metric-container"] {
        background: linear-gradient(160deg, #0d1b30 0%, #0a1220 100%);
        border: 1px solid #1a2744;
        border-top: 2px solid #2563EB;
        padding: 16px 18px;
        border-radius: 6px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.4);
        position: relative;
        overflow: hidden;
    }

    div[data-testid="metric-container"]::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background: radial-gradient(ellipse at top left, rgba(37,99,235,0.06) 0%, transparent 60%);
        pointer-events: none;
    }

    div[data-testid="metric-container"] label {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.65rem !important;
        letter-spacing: 0.15em !important;
        text-transform: uppercase !important;
        color: #4B6A9B !important;
        font-weight: 400 !important;
    }

    div[data-testid="metric-container"] [data-testid="metric-value"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 1.6rem !important;
        font-weight: 600 !important;
        color: #F9FAFB !important;
        letter-spacing: -0.02em !important;
        line-height: 1.2 !important;
    }

    div[data-testid="metric-container"] [data-testid="metric-delta"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.7rem !important;
    }

    /* ── Section Divider ────────────────────────────────────────── */
    .section-divider {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 1.5rem 0 1rem 0;
    }

    .section-divider .section-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #2563EB;
        white-space: nowrap;
    }

    .section-divider .section-line {
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, #1a2744 0%, transparent 100%);
    }

    /* ── Status Indicators ──────────────────────────────────────── */
    .status-bar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border-radius: 4px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.75rem;
        font-weight: 500;
        letter-spacing: 0.08em;
        margin-bottom: 1.25rem;
    }

    .status-bar::before {
        content: '';
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .status-operational {
        background: rgba(6,78,59,0.3);
        border: 1px solid rgba(16,185,129,0.3);
        color: #6EE7B7;
    }

    .status-operational::before {
        background: #10B981;
        box-shadow: 0 0 6px #10B981;
    }

    .status-failed {
        background: rgba(127,29,29,0.3);
        border: 1px solid rgba(239,68,68,0.3);
        color: #FCA5A5;
    }

    .status-failed::before {
        background: #EF4444;
        box-shadow: 0 0 6px #EF4444;
    }

    .status-unknown {
        background: rgba(55,65,81,0.3);
        border: 1px solid rgba(107,114,128,0.3);
        color: #9CA3AF;
    }

    .status-unknown::before {
        background: #6B7280;
    }

    /* ── Chart Containers ───────────────────────────────────────── */
    .chart-card {
        background: linear-gradient(160deg, #0d1b30 0%, #080f1e 100%);
        border: 1px solid #1a2744;
        border-radius: 6px;
        padding: 16px 18px 10px 18px;
        margin-bottom: 1rem;
    }

    .chart-card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
    }

    .chart-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #7A90B8;
    }

    /* ── Data Tables ────────────────────────────────────────────── */
    div[data-testid="stDataFrame"] {
        border: 1px solid #1a2744;
        border-radius: 6px;
        overflow: hidden;
    }

    div[data-testid="stDataFrame"] table {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.78rem !important;
    }

    /* ── Subheader overrides ────────────────────────────────────── */
    h2 {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.68rem !important;
        letter-spacing: 0.18em !important;
        text-transform: uppercase !important;
        color: #4B6A9B !important;
        font-weight: 400 !important;
        margin-bottom: 10px !important;
        margin-top: 20px !important;
    }

    h3 {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.65rem !important;
        letter-spacing: 0.15em !important;
        text-transform: uppercase !important;
        color: #4B6A9B !important;
        font-weight: 400 !important;
    }

    /* ── Caption & small text ───────────────────────────────────── */
    .caption-text {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        color: #2D4A7A;
        letter-spacing: 0.05em;
    }

    /* ── Warning / Info ─────────────────────────────────────────── */
    div[data-testid="stAlert"] {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.78rem;
        border-radius: 4px;
    }

    /* ── Scrollbar ──────────────────────────────────────────────── */
    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: #060B14; }
    ::-webkit-scrollbar-thumb { background: #1a2744; border-radius: 2px; }
    ::-webkit-scrollbar-thumb:hover { background: #2563EB; }

    /* ── Main title override ────────────────────────────────────── */
    h1 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-size: 1.65rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em !important;
        color: #F9FAFB !important;
    }

    /* ── Hide default Streamlit branding ────────────────────────── */
    #MainMenu, footer, header { visibility: hidden; }

    </style>
    """,
    unsafe_allow_html=True,
)


# ── Plotly theme shared across all charts ───────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Mono", color="#7A90B8", size=10),
    xaxis=dict(
        gridcolor="#111827",
        linecolor="#1a2744",
        tickcolor="#1a2744",
        tickfont=dict(size=9, color="#4B6A9B"),
        title_font=dict(size=9, color="#4B6A9B"),
    ),
    yaxis=dict(
        gridcolor="#111827",
        linecolor="#1a2744",
        tickcolor="#1a2744",
        tickfont=dict(size=9, color="#4B6A9B"),
        title_font=dict(size=9, color="#4B6A9B"),
    ),
    margin=dict(l=10, r=10, t=10, b=30),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=9, color="#7A90B8"),
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
    hoverlabel=dict(
        bgcolor="#0d1b30",
        bordercolor="#2563EB",
        font=dict(family="IBM Plex Mono", size=10, color="#F9FAFB"),
    ),
)

CHART_COLORS = ["#2563EB", "#06B6D4", "#8B5CF6", "#10B981", "#F59E0B", "#EF4444"]


# ── Helpers ──────────────────────────────────────────────────────
def load_table(table_name: str) -> pd.DataFrame:
    connection = sqlite3.connect(DATABASE_PATH)
    data = pd.read_sql_query(f"SELECT * FROM {table_name}", connection)
    connection.close()
    return data


def fmt(value):
    if pd.isna(value):
        return "N/A"
    return f"{value:,.2f}"


def fmt_int(value):
    if pd.isna(value):
        return "N/A"
    return f"{int(value):,}"


def section_header(label):
    st.markdown(
        f"""<div class="section-divider">
            <span class="section-label">{label}</span>
            <span class="section-line"></span>
        </div>""",
        unsafe_allow_html=True,
    )


def status_bar(pipeline_status):
    if pipeline_status == "SUCCESS":
        st.markdown(
            '<div class="status-bar status-operational">PIPELINE OPERATIONAL — All systems nominal</div>',
            unsafe_allow_html=True,
        )
    elif pipeline_status == "FAILED":
        st.markdown(
            '<div class="status-bar status-failed">PIPELINE FAULT DETECTED — Intervention required</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="status-bar status-unknown">PIPELINE STATUS UNKNOWN — No run data available</div>',
            unsafe_allow_html=True,
        )


def apply_chart_theme(fig):
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig


# ── Load data ────────────────────────────────────────────────────
if not DATABASE_PATH.exists():
    st.error("⚡ Database not found. Run: python3 src/run_pipeline.py")
    st.stop()

market_data = load_table("clean_market_data")
pipeline_runs = load_table("pipeline_runs")
data_quality = load_table("data_quality_results")

try:
    model_registry = load_table("model_registry")
except Exception:
    model_registry = pd.DataFrame()

try:
    predictions = load_table("predictions")
except Exception:
    predictions = pd.DataFrame()

if market_data.empty:
    st.warning("No market data found. Run the data pipeline first.")
    st.stop()

market_data["timestamp"] = pd.to_datetime(market_data["timestamp"])
if not pipeline_runs.empty and "run_time" in pipeline_runs.columns:
    pipeline_runs["run_time"] = pd.to_datetime(pipeline_runs["run_time"])
if not data_quality.empty and "check_time" in data_quality.columns:
    data_quality["check_time"] = pd.to_datetime(data_quality["check_time"])
if not model_registry.empty and "training_date" in model_registry.columns:
    model_registry["training_date"] = pd.to_datetime(model_registry["training_date"])
if not predictions.empty and "prediction_time" in predictions.columns:
    predictions["prediction_time"] = pd.to_datetime(predictions["prediction_time"])


# ── Sidebar ───────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="brand-logo"><span class="bolt">⚡</span> PowerFlow</div>
            <div class="brand-tagline">Electricity Trading Intelligence</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="nav-section-label">Navigation</div>', unsafe_allow_html=True)

    page = st.radio(
        label="",
        options=[
            "Executive Overview",
            "Market Intelligence",
            "Pipeline Operations",
            "Data Quality Control",
            "Model Registry",
            "Forecasting",
        ],
        label_visibility="collapsed",
    )

    st.markdown("<br>" * 2, unsafe_allow_html=True)
    st.markdown("---")

    latest_run_time_str = "—"
    if not pipeline_runs.empty:
        latest_run_time_str = str(
            pipeline_runs.sort_values("run_time").tail(1).iloc[0]["run_time"]
        )[:16]

    st.markdown(
        f"""
        <div style="font-family:'IBM Plex Mono',monospace; font-size:0.62rem; color:#2D4A7A; line-height:1.8;">
            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                <span>RECORDS</span>
                <span style="color:#4B6A9B">{fmt_int(len(market_data))}</span>
            </div>
            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                <span>LAST RUN</span>
                <span style="color:#4B6A9B">{latest_run_time_str}</span>
            </div>
            <div style="display:flex;justify-content:space-between;">
                <span>SYSTEM</span>
                <span style="color:#10B981">LIVE</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Pages ─────────────────────────────────────────────────────────

if page == "Executive Overview":
    st.markdown(
        """<div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        Executive Overview</div>
        <h1 style="margin-bottom:0.25rem;">Market Dashboard</h1>
        <p style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#2D4A7A;
        margin-bottom:1.5rem;letter-spacing:0.04em;">
        REAL-TIME ELECTRICITY MARKET INTELLIGENCE PLATFORM
        </p>""",
        unsafe_allow_html=True,
    )

    latest_pipeline_status = "UNKNOWN"
    latest_run_time = "N/A"
    if not pipeline_runs.empty:
        latest_run = pipeline_runs.sort_values("run_time").tail(1).iloc[0]
        latest_pipeline_status = latest_run["status"]
        latest_run_time = latest_run["run_time"]

    status_bar(latest_pipeline_status)

    section_header("Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Market Records", fmt_int(len(market_data)))
    col2.metric("Avg Market Price", fmt(market_data["market_price"].mean()))
    col3.metric("Avg System Demand", fmt(market_data["demand_mw"].mean()) + " MW")
    col4.metric("Avg System Supply", fmt(market_data["supply_mw"].mean()) + " MW")

    section_header("Market Overview")
    col5, col6 = st.columns(2)

    with col5:
        st.markdown('<div class="chart-title">MARKET PRICE TREND</div>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=market_data["timestamp"],
            y=market_data["market_price"],
            mode="lines",
            line=dict(color="#2563EB", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(37,99,235,0.07)",
            name="Market Price",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    with col6:
        st.markdown('<div class="chart-title">DEMAND vs SUPPLY</div>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=market_data["timestamp"],
            y=market_data["demand_mw"],
            mode="lines",
            line=dict(color="#06B6D4", width=1.5),
            name="Demand",
        ))
        fig.add_trace(go.Scatter(
            x=market_data["timestamp"],
            y=market_data["supply_mw"],
            mode="lines",
            line=dict(color="#8B5CF6", width=1.5),
            name="Supply",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    section_header("Latest Records")
    st.dataframe(
        market_data.sort_values("timestamp", ascending=False).head(10),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown(
        f'<div class="caption-text" style="margin-top:6px;">Last pipeline run: {latest_run_time}</div>',
        unsafe_allow_html=True,
    )


elif page == "Market Intelligence":
    st.markdown(
        """<div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        Market Intelligence</div>
        <h1 style="margin-bottom:1.5rem;">Price Analysis</h1>""",
        unsafe_allow_html=True,
    )

    section_header("Price Statistics")
    col1, col2, col3 = st.columns(3)
    col1.metric("Min Price", fmt(market_data["market_price"].min()))
    col2.metric("Max Price", fmt(market_data["market_price"].max()))
    col3.metric("Price Volatility (σ)", fmt(market_data["market_price"].std()))

    section_header("Price Movement")
    st.markdown('<div class="chart-title">INTRADAY MARKET PRICE</div>', unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=market_data["timestamp"],
        y=market_data["market_price"],
        mode="lines",
        line=dict(color="#2563EB", width=1.5),
        name="Market Price",
    ))
    apply_chart_theme(fig)
    st.plotly_chart(fig, use_container_width=True)

    col4, col5 = st.columns(2)
    with col4:
        st.markdown('<div class="chart-title">PRICE BY ENERGY SOURCE</div>', unsafe_allow_html=True)
        fig = px.bar(
            market_data,
            x="energy_source",
            y="market_price",
            color_discrete_sequence=CHART_COLORS,
        )
        apply_chart_theme(fig)
        fig.update_layout(showlegend=False)
        fig.update_traces(marker_line_color="rgba(0,0,0,0)", marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True)

    with col5:
        st.markdown('<div class="chart-title">SUPPLY-DEMAND GAP</div>', unsafe_allow_html=True)
        fig = go.Figure()
        gap = market_data["supply_demand_gap"]
        fig.add_trace(go.Scatter(
            x=market_data["timestamp"],
            y=gap,
            mode="lines",
            line=dict(color="#F59E0B", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(245,158,11,0.07)",
            name="S/D Gap",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    section_header("Market Dataset")
    st.dataframe(
        market_data.sort_values("timestamp", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


elif page == "Pipeline Operations":
    st.markdown(
        """<div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        Pipeline Operations</div>
        <h1 style="margin-bottom:1.5rem;">Run History</h1>""",
        unsafe_allow_html=True,
    )

    if pipeline_runs.empty:
        st.warning("No pipeline runs found.")
    else:
        latest_run = pipeline_runs.sort_values("run_time").tail(1).iloc[0]
        status_bar(latest_run["status"])

        section_header("Latest Run")
        col1, col2, col3 = st.columns(3)
        col1.metric("Status", latest_run["status"])
        col2.metric("Records Processed", fmt_int(latest_run["records_processed"]))
        col3.metric("Run Time", str(latest_run["run_time"])[:16])

        section_header("Run History")
        st.dataframe(
            pipeline_runs.sort_values("run_time", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        section_header("Throughput Chart")
        st.markdown('<div class="chart-title">RECORDS PROCESSED PER RUN</div>', unsafe_allow_html=True)
        color_map = {"SUCCESS": "#10B981", "FAILED": "#EF4444"}
        fig = px.bar(
            pipeline_runs,
            x="run_time",
            y="records_processed",
            color="status",
            color_discrete_map=color_map,
        )
        apply_chart_theme(fig)
        fig.update_traces(marker_line_color="rgba(0,0,0,0)", marker_line_width=0)
        st.plotly_chart(fig, use_container_width=True)


elif page == "Data Quality Control":
    st.markdown(
        """<div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        Data Quality Control</div>
        <h1 style="margin-bottom:1.5rem;">Validation Results</h1>""",
        unsafe_allow_html=True,
    )

    if data_quality.empty:
        st.warning("No data quality results found.")
    else:
        passed = len(data_quality[data_quality["status"] == "PASSED"])
        failed = len(data_quality[data_quality["status"] == "FAILED"])
        warning = len(data_quality[data_quality["status"] == "WARNING"])
        total = len(data_quality)
        quality_rate = (passed / total) * 100 if total > 0 else 0

        if failed > 0:
            st.markdown(
                f'<div class="status-bar status-failed">{failed} DATA QUALITY ISSUE(S) DETECTED — Review required</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="status-bar status-operational">ALL DATA QUALITY CONTROLS PASSING</div>',
                unsafe_allow_html=True,
            )

        section_header("Quality Summary")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Checks", fmt_int(total))
        col2.metric("Passed", fmt_int(passed))
        col3.metric("Failed", fmt_int(failed))
        col4.metric("Pass Rate", f"{quality_rate:.1f}%")

        section_header("Distribution & Log")
        col5, col6 = st.columns([1, 2])

        with col5:
            st.markdown('<div class="chart-title">STATUS DISTRIBUTION</div>', unsafe_allow_html=True)
            color_map = {"PASSED": "#10B981", "FAILED": "#EF4444", "WARNING": "#F59E0B"}
            fig = px.pie(
                data_quality,
                names="status",
                color="status",
                color_discrete_map=color_map,
                hole=0.55,
            )
            apply_chart_theme(fig)
            fig.update_traces(
                textfont=dict(family="IBM Plex Mono", size=9),
                marker=dict(line=dict(color="#060B14", width=2)),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col6:
            st.markdown('<div class="chart-title">RECENT CHECKS</div>', unsafe_allow_html=True)
            st.dataframe(
                data_quality.sort_values("check_time", ascending=False).head(10),
                use_container_width=True,
                hide_index=True,
            )

        section_header("Full Quality Log")
        st.dataframe(
            data_quality.sort_values("check_time", ascending=False),
            use_container_width=True,
            hide_index=True,
        )


elif page == "Model Registry":
    st.markdown(
        """<div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        Model Registry</div>
        <h1 style="margin-bottom:1.5rem;">ML Model Management</h1>""",
        unsafe_allow_html=True,
    )

    if model_registry.empty:
        st.warning("No model records found. Run: python3 src/train_model.py")
    else:
        latest_model = model_registry.sort_values("training_date").tail(1).iloc[0]

        section_header("Active Model")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Version", latest_model["version"])
        col2.metric("MAE", fmt(latest_model["mae"]))
        col3.metric("RMSE", fmt(latest_model["rmse"]))
        col4.metric("R² Score", fmt(latest_model["r2_score"]))

        section_header("Registered Versions")
        st.dataframe(
            model_registry.sort_values("training_date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        section_header("Performance Trend")
        st.markdown('<div class="chart-title">MODEL METRICS OVER TRAINING RUNS</div>', unsafe_allow_html=True)
        fig = go.Figure()
        metrics = [
            ("mae", "#EF4444"),
            ("rmse", "#F59E0B"),
            ("r2_score", "#10B981"),
        ]
        for col_name, color in metrics:
            if col_name in model_registry.columns:
                fig.add_trace(go.Scatter(
                    x=model_registry["training_date"],
                    y=model_registry[col_name],
                    mode="lines+markers",
                    line=dict(color=color, width=1.5),
                    marker=dict(size=5, color=color),
                    name=col_name.upper(),
                ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)


elif page == "Forecasting":
    st.markdown(
        """<div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        Forecasting</div>
        <h1 style="margin-bottom:1.5rem;">Price Forecast</h1>""",
        unsafe_allow_html=True,
    )

    if predictions.empty:
        st.warning("No predictions found. Run: python3 src/predict.py")
    else:
        latest_pred = predictions.sort_values("prediction_time").tail(1).iloc[0]

        section_header("Latest Forecast")
        col1, col2, col3 = st.columns(3)
        col1.metric("Forecasted Price", fmt(latest_pred["predicted_price"]))
        col2.metric("Model Version", latest_pred["model_version"])
        col3.metric("Forecast Time", str(latest_pred["prediction_time"])[:16])

        section_header("Forecast Log")
        st.dataframe(
            predictions.sort_values("prediction_time", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        section_header("Predicted Price Trend")
        st.markdown('<div class="chart-title">FORECAST TIMELINE</div>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=predictions["prediction_time"],
            y=predictions["predicted_price"],
            mode="lines+markers",
            line=dict(color="#2563EB", width=1.5, dash="dot"),
            marker=dict(size=5, color="#2563EB"),
            fill="tozeroy",
            fillcolor="rgba(37,99,235,0.06)",
            name="Predicted Price",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)