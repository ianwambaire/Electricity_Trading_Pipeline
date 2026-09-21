from pathlib import Path
import json
import math
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard_data import (
    csv_has_rows,
    downsample_time_series,
    load_csv_summary,
    load_dashboard_csv,
    load_final_release_metadata,
    load_next24h_forecast_report,
    summarize_next24h_forecast,
)
from dashboard_health import (
    age_label,
    alert_configuration_status,
    assess_operational_health,
    count_quality_statuses,
    filter_incidents,
    forecast_freshness_state,
    latest_quality_state,
    load_recent_incidents,
    load_recent_stage_timings,
    model_performance_state,
    load_latest_successful_run_time,
    load_recent_data_quality_history,
    load_recent_pipeline_history,
    parse_operational_metadata,
    prepare_data_quality_history,
    prepare_pipeline_history,
    redact_operational_text,
    source_freshness_state,
    summarize_pipeline_timings,
)
from models.next24h_monitoring import summarize_realized_performance


SILVER_DATA = Path("data/processed/silver_electricity_market_data.csv")
GOLD_DATA = Path("data/features/gold_model_features.csv")
PREDICTIONS_DATA = Path("data/reports/actual_vs_predicted.csv")
ANOMALIES_DATA = Path("data/reports/detected_anomalies.csv")
FEATURE_IMPORTANCE_DATA = Path("data/reports/feature_importance.csv")
FINAL_RELEASE_MANIFEST = Path("artifacts/models/final_model_release_manifest.json")
FINAL_HOLDOUT_METRICS = Path("data/reports/final_holdout_metrics.csv")
NEXT24H_FORECAST_DATA = Path("data/reports/next24h_forecast.csv")
NEXT24H_PROVENANCE_DATA = Path("data/reports/next24h_forecast_provenance.json")
NEXT24H_PERFORMANCE_DATA = Path("data/reports/next24h_performance.csv")
NEXT24H_REALIZED_DATA = Path("data/reports/next24h_realized_errors.csv")
NEXT24H_HISTORY_DATA = Path("data/reports/next24h_forecast_history.csv")
NEXT24H_RELEASE_MANIFEST = Path("artifacts/models/releases/next24h/next24h_release_manifest.json")
NEXT24H_RELEASE_MODEL = Path("artifacts/models/releases/next24h/next24h_model.joblib")
NEXT24H_RELEASE_CONTRACT = Path("artifacts/models/releases/next24h/next24h_feature_contract.joblib")
PIPELINE_DATABASE = Path("database/electricity_trading.db")
CHART_MAX_POINTS = 4_000


st.set_page_config(
    page_title="PowerFlow — Electricity Trading Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto",
)


st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-family: "Avenir Next", "Segoe UI", system-ui, -apple-system, sans-serif;
        color: #172033;
    }

    .stApp {
        background: #F5F7FA;
    }

    .block-container {
        padding: 2.25rem 3rem 4rem;
        max-width: 1500px;
    }

    section[data-testid="stSidebar"] {
        background: #FFFFFF;
        border-right: 1px solid #E2E8F0;
        padding-top: 0;
    }

    .sidebar-brand {
        border-bottom: 1px solid #E8EDF3;
        padding: 1.4rem 0.5rem 1.25rem;
        margin-bottom: 1.1rem;
    }

    .brand-logo {
        font-size: 1.35rem;
        font-weight: 750;
        color: #0F2744;
        letter-spacing: -0.02em;
    }

    .bolt {
        color: #0B6FFB;
        font-size: 1.35rem;
        margin-right: 0.15rem;
    }

    .brand-tagline {
        font-size: 0.72rem;
        color: #667085;
        line-height: 1.4;
        margin-top: 0.25rem;
    }

    .nav-section-label {
        font-size: 0.72rem;
        font-weight: 650;
        color: #667085;
        padding: 0 0.55rem;
        margin: 0 0 0.45rem;
    }

    div[data-testid="stRadio"] label {
        font-size: 0.88rem;
        font-weight: 520;
        color: #475467;
        padding: 0.48rem 0.65rem;
        border-radius: 7px;
        transition: background-color 120ms ease, color 120ms ease;
    }

    div[data-testid="stRadio"] label:hover {
        color: #0F2744;
        background: #F2F6FA;
    }

    div[data-testid="stRadio"] label:has(input:checked) {
        color: #075DC7;
        background: #EAF3FF;
        font-weight: 650;
    }

    div[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {
        line-height: 1.25;
    }

    .sidebar-status-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 0.9rem;
        margin-top: 1.15rem;
    }

    .sidebar-status-title {
        color: #344054;
        font-size: 0.75rem;
        font-weight: 700;
        margin-bottom: 0.7rem;
    }

    .sidebar-status-row {
        display: flex;
        justify-content: space-between;
        gap: 0.75rem;
        padding: 0.28rem 0;
        color: #667085;
        font-size: 0.72rem;
    }

    .sidebar-status-row strong {
        color: #344054;
        font-weight: 650;
        text-align: right;
    }

    div[data-testid="metric-container"],
    div[data-testid="stMetric"] {
        min-height: 118px;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 1rem 1.1rem;
        border-radius: 10px;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }

    div[data-testid="metric-container"] label,
    div[data-testid="stMetricLabel"] {
        font-size: 0.76rem !important;
        font-weight: 600 !important;
        color: #667085 !important;
    }

    div[data-testid="metric-container"] [data-testid="metric-value"],
    div[data-testid="stMetricValue"] {
        font-variant-numeric: tabular-nums;
        font-size: 1.4rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.025em !important;
        line-height: 1.15 !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
        overflow-wrap: anywhere;
        color: #0F2744 !important;
    }

    div[data-testid="stMetricValue"] * {
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: normal !important;
    }

    .section-divider {
        display: flex;
        align-items: center;
        gap: 0.9rem;
        margin: 1.9rem 0 0.9rem;
    }

    .section-label {
        font-size: 0.9rem;
        font-weight: 700;
        color: #243B53;
        white-space: nowrap;
    }

    .section-line {
        flex: 1;
        height: 1px;
        background: #DCE3EA;
    }

    .chart-title {
        font-size: 0.82rem;
        font-weight: 650;
        color: #475467;
        margin: 0.15rem 0 0.4rem;
    }

    .page-heading {
        margin-bottom: 1.25rem;
    }

    .page-eyebrow {
        color: #0B6FFB;
        font-size: 0.75rem;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }

    .page-subtitle {
        color: #667085;
        font-size: 0.88rem;
        margin: 0.35rem 0 0;
    }

    h1 {
        font-family: "Avenir Next", "Segoe UI", system-ui, sans-serif !important;
        font-size: 2rem !important;
        font-weight: 720 !important;
        letter-spacing: -0.035em !important;
        color: #0F2744 !important;
        margin: 0 !important;
    }

    h2, h3 {
        font-family: "Avenir Next", "Segoe UI", system-ui, sans-serif !important;
        color: #243B53 !important;
    }

    div[data-testid="stPlotlyChart"],
    div[data-testid="stDataFrame"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
        overflow: hidden;
    }

    div[data-testid="stAlert"] {
        border-radius: 9px;
        border-width: 1px;
        box-shadow: none;
    }

    div[data-testid="stCaptionContainer"] {
        color: #667085;
    }

    hr {
        border-color: #E8EDF3 !important;
    }

    header[data-testid="stHeader"] {
        background: transparent;
    }

    #MainMenu, footer {
        visibility: hidden;
    }

    @media (max-width: 900px) {
        .block-container {
            padding: 1.25rem 1rem 3rem;
        }

        h1 {
            font-size: 1.65rem !important;
        }

        div[data-testid="metric-container"],
        div[data-testid="stMetric"] {
            min-height: 104px;
            padding: 0.85rem;
        }

        div[data-testid="metric-container"] [data-testid="metric-value"],
        div[data-testid="stMetricValue"] {
            font-size: 1.3rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#FFFFFF",
    font=dict(family="Avenir Next, Segoe UI, sans-serif", color="#475467", size=11),
    xaxis=dict(
        gridcolor="#E9EEF5",
        linecolor="#CDD5DF",
        zerolinecolor="#DCE3EA",
        tickfont=dict(color="#667085"),
        title_font=dict(color="#344054"),
    ),
    yaxis=dict(
        gridcolor="#E9EEF5",
        linecolor="#CDD5DF",
        zerolinecolor="#DCE3EA",
        tickfont=dict(color="#667085"),
        title_font=dict(color="#344054"),
    ),
    margin=dict(l=28, r=20, t=24, b=38),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=10, color="#475467"),
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
)

CHART_COLORS = ["#0B6FFB", "#16A3A3", "#F59E0B", "#2E9D68", "#7A5AF8", "#D92D20"]


def load_latest_pipeline_run(path: Path):
    recent = load_recent_pipeline_history(path, limit=1)
    if recent.empty:
        return None, "No pipeline runs have been recorded yet."
    return recent.iloc[0].to_dict(), None


def fmt(value):
    if pd.isna(value):
        return "N/A"
    return f"{value:,.2f}"


def fmt_int(value):
    if pd.isna(value):
        return "N/A"
    return f"{int(value):,}"


def fmt_date(value):
    if value is None or pd.isna(value):
        return "N/A"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def fmt_timestamp(value):
    if value is None or pd.isna(value):
        return "N/A"
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if timestamp.tzinfo is None:
        return timestamp.strftime("%Y-%m-%d %H:%M")
    return timestamp.tz_convert("UTC").strftime("%Y-%m-%d %H:%M UTC")


def has_columns(data: pd.DataFrame, columns) -> bool:
    return not data.empty and set(columns).issubset(data.columns)


def show_data_warning(label: str, path: Path):
    st.warning(
        f"{label} is unavailable or unreadable at `{path}`. "
        "Run the ENTSO-E pipeline to regenerate it."
    )


def section_header(label):
    st.markdown(
        f"""
        <div class="section-divider">
            <span class="section-label">{label}</span>
            <span class="section-line"></span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def apply_chart_theme(fig):
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig


def page_title(eyebrow, title, subtitle=None):
    subtitle_html = ""
    if subtitle:
        subtitle_html = f'<p class="page-subtitle">{subtitle}</p>'

    st.markdown(
        f"""
        <div class="page-heading">
            <div class="page-eyebrow">{eyebrow}</div>
            <h1>{title}</h1>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


silver_summary = load_csv_summary(SILVER_DATA)
latest_pipeline_run, pipeline_run_error = load_latest_pipeline_run(PIPELINE_DATABASE)
latest_timestamp = silver_summary["latest_timestamp"]
earliest_timestamp = silver_summary["earliest_timestamp"]


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
        label="Dashboard page",
        options=[
            "Executive Overview",
            "Market Intelligence",
            "Forecasting",
            "Anomaly Detection",
            "Model Insights",
            "Pipeline Summary",
        ],
        label_visibility="collapsed",
    )

    st.markdown(
        f"""
        <div class="sidebar-status-card">
            <div class="sidebar-status-title">System status</div>
            <div class="sidebar-status-row">
                <span>Pipeline</span>
                <strong>{latest_pipeline_run['status'].title() if latest_pipeline_run else 'Unknown'}</strong>
            </div>
            <div class="sidebar-status-row">
                <span>Market</span>
                <strong>DE-LU</strong>
            </div>
            <div class="sidebar-status-row">
                <span>Hourly records</span>
                <strong>{fmt_int(silver_summary['row_count']) if silver_summary['available'] else 'N/A'}</strong>
            </div>
            <div class="sidebar-status-row">
                <span>Data through</span>
                <strong>{fmt_date(latest_timestamp)}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


if page == "Executive Overview":
    silver_data = load_dashboard_csv(
        SILVER_DATA,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )
    anomaly_summary = load_csv_summary(ANOMALIES_DATA)
    silver_ready = has_columns(
        silver_data,
        ["timestamp", "price_eur_mwh", "load_mw", "wind_total_mw", "solar_mw"],
    )
    timestamped_silver = (
        silver_data.dropna(subset=["timestamp"])
        if silver_ready
        else pd.DataFrame()
    )
    latest_price = (
        timestamped_silver["price_eur_mwh"].iloc[-1]
        if not timestamped_silver.empty
        else None
    )

    page_title(
        "Executive Overview",
        "Market Dashboard",
        "Historical Germany-Luxembourg electricity market analysis",
    )

    if not silver_ready:
        show_data_warning("Silver dataset", SILVER_DATA)
    else:
        st.caption(
            f"Historical dataset coverage: {fmt_timestamp(earliest_timestamp)} to "
            f"{fmt_timestamp(latest_timestamp)}."
        )

        section_header("Key Metrics")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Hourly Records", fmt_int(len(silver_data)))
        col2.metric("Latest Price", f"{fmt(latest_price)} EUR/MWh")
        col3.metric("Avg Load", f"{fmt(silver_data['load_mw'].mean())} MW")
        col4.metric(
            "Anomalies",
            fmt_int(anomaly_summary["row_count"])
            if anomaly_summary["available"]
            else "N/A",
        )

        section_header("Market Overview")
        col5, col6 = st.columns(2)
        overview_plot_data = downsample_time_series(
            timestamped_silver,
            CHART_MAX_POINTS,
        )

        with col5:
            st.markdown('<div class="chart-title">Electricity price trend</div>', unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=overview_plot_data["timestamp"],
                y=overview_plot_data["price_eur_mwh"],
                mode="lines",
                line=dict(color="#0B6FFB", width=1.5),
                name="Price EUR/MWh",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")

        with col6:
            st.markdown('<div class="chart-title">Load and renewable generation</div>', unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=overview_plot_data["timestamp"],
                y=overview_plot_data["load_mw"],
                mode="lines",
                line=dict(color="#16A3A3", width=1.4),
                name="Load MW",
            ))
            fig.add_trace(go.Scatter(
                x=overview_plot_data["timestamp"],
                y=(
                    overview_plot_data["wind_total_mw"]
                    + overview_plot_data["solar_mw"]
                ),
                mode="lines",
                line=dict(color="#2E9D68", width=1.4),
                name="Wind + Solar MW",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")

        section_header("Latest Historical Records")
        st.dataframe(
            timestamped_silver.tail(10).iloc[::-1],
            width="stretch",
            hide_index=True,
        )


elif page == "Market Intelligence":
    silver_data = load_dashboard_csv(
        SILVER_DATA,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )
    page_title("Market Intelligence", "Price and Generation Analysis")

    generation_cols = [
        "biomass_mw",
        "lignite_mw",
        "gas_mw",
        "hard_coal_mw",
        "hydro_mw",
        "nuclear_mw",
        "solar_mw",
        "wind_total_mw",
    ]

    market_columns = generation_cols + [
        "timestamp",
        "price_eur_mwh",
        "temperature_2m",
        "wind_speed_10m",
    ]
    if not has_columns(silver_data, market_columns):
        show_data_warning("Silver market dataset", SILVER_DATA)
    else:
        market_plot_data = downsample_time_series(
            silver_data.dropna(subset=["timestamp"]),
            CHART_MAX_POINTS,
        )
        st.caption(
            f"Historical dataset coverage: {fmt_timestamp(earliest_timestamp)} to "
            f"{fmt_timestamp(latest_timestamp)}."
        )

        section_header("Price Statistics")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Min Price", fmt(silver_data["price_eur_mwh"].min()))
        col2.metric("Max Price", fmt(silver_data["price_eur_mwh"].max()))
        col3.metric("Avg Price", fmt(silver_data["price_eur_mwh"].mean()))
        col4.metric("Volatility", fmt(silver_data["price_eur_mwh"].std()))

        section_header("Market Price Movement")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=market_plot_data["timestamp"],
            y=market_plot_data["price_eur_mwh"],
            mode="lines",
            line=dict(color="#0B6FFB", width=1.5),
            name="Electricity Price",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, width="stretch")

        section_header("Generation Mix")
        gen_avg = silver_data[generation_cols].mean().reset_index()
        gen_avg.columns = ["source", "average_mw"]
        gen_avg["source"] = (
            gen_avg["source"]
            .str.removesuffix("_mw")
            .str.replace("_", " ")
            .str.title()
        )

        fig = px.bar(
            gen_avg.sort_values("average_mw", ascending=False),
            x="source",
            y="average_mw",
            color="source",
            color_discrete_sequence=CHART_COLORS,
        )
        apply_chart_theme(fig)
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, width="stretch")

        section_header("Weather Conditions")
        col1, col2 = st.columns(2)

        with col1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=market_plot_data["timestamp"],
                y=market_plot_data["temperature_2m"],
                mode="lines",
                line=dict(color="#F59E0B", width=1.2),
                name="Temperature",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")

        with col2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=market_plot_data["timestamp"],
                y=market_plot_data["wind_speed_10m"],
                mode="lines",
                line=dict(color="#16A3A3", width=1.4),
                name="Wind Speed",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")


elif page == "Forecasting":
    next24h_forecast, next24h_error = load_next24h_forecast_report(
        NEXT24H_FORECAST_DATA
    )
    realized_errors = load_dashboard_csv(
        NEXT24H_REALIZED_DATA,
        timestamp_columns=("forecast_issue_time", "target_timestamp", "issued_at_utc"),
    )
    forecast_history = load_dashboard_csv(
        NEXT24H_HISTORY_DATA,
        timestamp_columns=("forecast_issue_time", "target_timestamp", "issued_at_utc"),
    )
    try:
        next24h_manifest = json.loads(NEXT24H_RELEASE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        next24h_manifest = {}
    final_release, final_release_error = load_final_release_metadata(
        FINAL_RELEASE_MANIFEST,
        FINAL_HOLDOUT_METRICS,
    )
    predictions = load_dashboard_csv(
        PREDICTIONS_DATA,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )
    page_title("Forecasting", "Electricity Price Forecasts")

    section_header("Rolling Next 24-Hour Production Forecast")
    st.caption("Histogram Gradient Boosting · 24 direct hourly predictions · not trading signals.")
    if next24h_error:
        st.warning(next24h_error)
    else:
        issue_time = next24h_forecast["forecast_issue_time"].iloc[0]
        forecast_summary = summarize_next24h_forecast(next24h_forecast)
        try:
            provenance = json.loads(NEXT24H_PROVENANCE_DATA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            provenance = {}
        if not isinstance(provenance, dict) or provenance.get("forecast_issue_time") != issue_time.isoformat():
            provenance = {}
        display_now = pd.Timestamp.now(tz="UTC")
        freshness_hours = (display_now - issue_time).total_seconds() / 3600
        try:
            maximum_age = float(os.getenv("POWERFLOW_NEXT24H_MAX_AGE_HOURS", "3"))
        except ValueError:
            maximum_age = 3.0
        if not math.isfinite(maximum_age) or not 0 < maximum_age <= 24:
            maximum_age = 3.0
        if freshness_hours < 0 or freshness_hours > maximum_age:
            st.warning(
                f"This forecast is stale: its issue hour is {freshness_hours:.1f} "
                f"hours old (limit {maximum_age:g} hours). It is retained for reference, "
                "not presented as a current forecast."
            )
        elif next24h_forecast["target_timestamp"].iloc[0] <= display_now:
            st.warning(
                "Some forecast target hours have already passed. Review the "
                "issue time before using this as a forward-looking forecast."
            )
        high = next24h_forecast.loc[next24h_forecast["predicted_price_eur_mwh"].idxmax()]
        low = next24h_forecast.loc[next24h_forecast["predicted_price_eur_mwh"].idxmin()]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Forecast Issue (UTC)", issue_time.strftime("%Y-%m-%d %H:%M"))
        market_hour = provenance.get("market_latest_complete_hour")
        col2.metric(
            "Market Data Through (UTC)" if market_hour else "Silver Data Through (UTC)",
            pd.Timestamp(market_hour).strftime("%Y-%m-%d %H:%M")
            if market_hour else (
                latest_timestamp.strftime("%Y-%m-%d %H:%M")
                if latest_timestamp is not None and pd.notna(latest_timestamp) else "N/A"
            ),
        )
        col3.metric("Highest Predicted Price", f"{high['predicted_price_eur_mwh']:.2f} EUR/MWh")
        col4.metric("Lowest Predicted Price", f"{low['predicted_price_eur_mwh']:.2f} EUR/MWh")
        st.caption(
            f"Release: {next24h_forecast['model_release'].iloc[0]} · "
            f"Peak: {high['target_timestamp']:%Y-%m-%d %H:%M} UTC · "
            f"Low: {low['target_timestamp']:%Y-%m-%d %H:%M} UTC"
        )
        if provenance.get("weather_acquired_at_utc"):
            st.caption(
                "Issue-hour weather: Open-Meteo operational model (not historical "
                "observations or future-horizon weather) · Acquired: "
                f"{provenance['weather_acquired_at_utc']}"
            )
        issued_rows = (
            forecast_history.loc[forecast_history["forecast_issue_time"] == issue_time]
            if "forecast_issue_time" in forecast_history and "issued_at_utc" in forecast_history
            else pd.DataFrame()
        )
        issued_at = issued_rows["issued_at_utc"].min() if not issued_rows.empty else None
        st.caption(
            f"Forecast issued: {fmt_timestamp(issued_at)} · "
            f"Freshness: {age_label(issue_time, now=display_now)} · "
            f"Model: Histogram Gradient Boosting · Release: {forecast_summary['release_id']}"
        )
        analyst_metrics = [
            ("24h Average", f"{forecast_summary['average']:.2f} EUR/MWh"),
            ("24h Median", f"{forecast_summary['median']:.2f} EUR/MWh"),
            ("First-to-Last Change", f"{forecast_summary['first_to_last_change']:+.2f} EUR/MWh"),
            ("Negative-Price Hours", str(forecast_summary["negative_hours"])),
            ("Hours ≥ 200 EUR/MWh", str(forecast_summary["elevated_hours"])),
            ("Forecast Rows", str(forecast_summary["rows"])),
        ]
        for offset in range(0, len(analyst_metrics), 3):
            columns = st.columns(3)
            for column, (label, value) in zip(columns, analyst_metrics[offset:offset + 3]):
                column.metric(label, value)
        if forecast_summary["negative_hours"]:
            st.warning(
                f"Negative price conditions are forecast for {forecast_summary['negative_hours']} hour(s)."
            )
        if forecast_summary["elevated_hours"]:
            st.warning(
                f"Elevated price conditions are forecast for {forecast_summary['elevated_hours']} hour(s)."
            )
        figure = go.Figure()
        figure.add_trace(go.Scatter(
            x=next24h_forecast["target_timestamp"],
            y=next24h_forecast["predicted_price_eur_mwh"],
            mode="lines+markers", line=dict(color="#0B6FFB", width=2),
            name="Predicted Price (EUR/MWh)",
        ))
        apply_chart_theme(figure)
        figure.update_layout(yaxis_title="EUR/MWh")
        st.plotly_chart(figure, width="stretch")
        with st.expander("View all 24 forecast hours"):
            st.dataframe(next24h_forecast, width="stretch", hide_index=True)
        st.download_button(
            "Download current 24-hour forecast (CSV)",
            data=next24h_forecast.to_csv(index=False),
            file_name=f"powerflow_next24h_{issue_time:%Y%m%d_%H00}_UTC.csv",
            mime="text/csv",
        )

    section_header("Realized Next24h Performance")
    required_errors = {
        "forecast_issue_time", "target_timestamp", "issued_at_utc",
        "horizon_hours", "absolute_error", "squared_error", "signed_error",
    }
    if required_errors.issubset(realized_errors.columns):
        monitoring = summarize_realized_performance(realized_errors)
    else:
        monitoring = summarize_realized_performance(pd.DataFrame())
    overall = monitoring["overall"]
    if overall["status"] == "Available":
        columns = st.columns(4)
        for column, (label, value) in zip(columns, [
            ("Overall MAE", overall["mae"]), ("Overall RMSE", overall["rmse"]),
            ("Overall Bias", overall["bias"]), ("Matched Pairs", overall["pair_count"]),
        ]):
            column.metric(label, str(value) if label == "Matched Pairs" else f"{value:.2f} EUR/MWh")
    else:
        st.info(f"Insufficient realized forecasts for aggregate metrics ({overall['pair_count']} matched pairs; minimum 20).")
    window_rows = []
    for window, values in monitoring["windows"].items():
        window_rows.append({
            "Period": window, "Pairs": values["pair_count"],
            "MAE (EUR/MWh)": round(values["mae"], 2) if values["mae"] is not None else None,
            "RMSE (EUR/MWh)": round(values["rmse"], 2) if values["rmse"] is not None else None,
            "Bias (EUR/MWh)": round(values["bias"], 2) if values["bias"] is not None else None,
            "Status": values["status"],
        })
    st.dataframe(pd.DataFrame(window_rows), width="stretch", hide_index=True)
    st.caption("Windows use observed target time; bias = predicted minus observed. Minimum 20 pairs per aggregate/window and 5 per horizon.")
    model_health = model_performance_state(monitoring, next24h_manifest)
    st.info(f"Model performance: {model_health['label']}. {model_health['reason']}")
    with st.expander("View realized performance by horizon (h+1 to h+24)"):
        st.dataframe(monitoring["horizons"], width="stretch", hide_index=True)

    section_header("Frozen One-Hour Model Evaluation")
    st.caption("Ordinary Linear Regression · historical final holdout evaluation, not live next24h performance.")
    if final_release is None:
        st.warning(final_release_error)
    else:
        section_header("Final Holdout Metrics")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Final Model", str(final_release["model_name"]))
        col2.metric("MAE", fmt(final_release["mae"]))
        col3.metric("RMSE", fmt(final_release["rmse"]))
        col4.metric("R² Score", f"{final_release['r2']:.3f}")
        st.caption(
            f"Final evaluation period: {fmt_date(final_release['holdout_start'])} to "
            f"{fmt_date(final_release['holdout_end'])} · "
            f"{final_release['improvement_vs_persistence_pct']:.2f}% RMSE improvement "
            "over persistence."
        )
        st.info(
            "Model limitation: forecast performance is weaker during extreme "
            "price events at or above EUR 200/MWh."
        )

    prediction_columns = ["timestamp", "actual_price", "predicted_price"]
    if not has_columns(predictions, prediction_columns):
        show_data_warning("Actual-vs-predicted report", PREDICTIONS_DATA)
    else:
        section_header("Historical One-Hour Actual vs Predicted")
        plot_data = predictions.tail(500)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=plot_data["timestamp"],
            y=plot_data["actual_price"],
            mode="lines",
            line=dict(color="#0B6FFB", width=1.5),
            name="Actual Price",
        ))
        fig.add_trace(go.Scatter(
            x=plot_data["timestamp"],
            y=plot_data["predicted_price"],
            mode="lines",
            line=dict(color="#2E9D68", width=1.5),
            name="Predicted Price",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, width="stretch")

        section_header("Forecast Records")
        st.dataframe(
            predictions.tail(20).iloc[::-1],
            width="stretch",
            hide_index=True,
        )


elif page == "Anomaly Detection":
    anomalies = load_dashboard_csv(
        ANOMALIES_DATA,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )
    silver_data = load_dashboard_csv(
        SILVER_DATA,
        timestamp_columns=("timestamp",),
        sort_by="timestamp",
    )
    silver_ready = has_columns(
        silver_data,
        ["timestamp", "price_eur_mwh", "load_mw", "wind_total_mw", "solar_mw"],
    )
    page_title("Anomaly Detection", "Unusual Historical Market Events")

    anomaly_columns = ["timestamp", "price_eur_mwh", "load_mw"]
    if not has_columns(anomalies, anomaly_columns):
        show_data_warning("Detected-anomalies report", ANOMALIES_DATA)
    else:
        section_header("Anomaly Summary")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Detected Anomalies", fmt_int(len(anomalies)))
        col2.metric("Max Anomaly Price", fmt(anomalies["price_eur_mwh"].max()))
        col3.metric("Min Anomaly Price", fmt(anomalies["price_eur_mwh"].min()))
        col4.metric("Avg Anomaly Load", f"{fmt(anomalies['load_mw'].mean())} MW")

        if silver_ready:
            anomaly_background = downsample_time_series(
                silver_data.dropna(subset=["timestamp"]),
                CHART_MAX_POINTS,
            )
            section_header("Price Anomalies")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=anomaly_background["timestamp"],
                y=anomaly_background["price_eur_mwh"],
                mode="lines",
                line=dict(color="#0B6FFB", width=1.2),
                name="Price",
            ))
            fig.add_trace(go.Scatter(
                x=anomalies["timestamp"],
                y=anomalies["price_eur_mwh"],
                mode="markers",
                marker=dict(color="#D92D20", size=6),
                name="Anomaly",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")
        else:
            show_data_warning("Silver dataset for anomaly context", SILVER_DATA)

        section_header("Top Anomaly Events")
        st.dataframe(
            anomalies.sort_values("price_eur_mwh", ascending=False).head(20),
            width="stretch",
            hide_index=True,
        )


elif page == "Model Insights":
    feature_importance = load_dashboard_csv(FEATURE_IMPORTANCE_DATA)
    page_title("Model Insights", "Final Model Feature Influence")

    if not has_columns(feature_importance, ["feature", "importance"]):
        show_data_warning("Feature-importance report", FEATURE_IMPORTANCE_DATA)
    else:
        section_header("Top Feature Drivers")
        ranked_features = feature_importance.sort_values("importance", ascending=False)
        top_features = ranked_features.head(15)

        fig = px.bar(
            top_features.sort_values("importance"),
            x="importance",
            y="feature",
            orientation="h",
            color="importance",
            color_continuous_scale="Blues",
        )
        apply_chart_theme(fig)
        fig.update_layout(showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")

        section_header("Feature Importance Table")
        st.dataframe(
            ranked_features,
            width="stretch",
            hide_index=True,
        )

        section_header("Interpretation")
        leading_features = ", ".join(ranked_features.head(5)["feature"].astype(str))
        st.info(
            "The final linear model has the largest absolute standardized "
            f"coefficients for: {leading_features}. Correlated predictors mean "
            "these magnitudes should not be interpreted as causal effects."
        )


elif page == "Pipeline Summary":
    gold_summary = load_csv_summary(GOLD_DATA)
    source_summaries = {
        "ENTSO-E prices": load_csv_summary(Path("data/raw/entsoe/prices.csv")),
        "ENTSO-E load": load_csv_summary(Path("data/raw/entsoe/load.csv")),
        "ENTSO-E generation": load_csv_summary(Path("data/raw/entsoe/generation.csv")),
        "Open-Meteo historical weather": load_csv_summary(Path("data/raw/weather/open_meteo_weather.csv")),
        "Silver": silver_summary,
        "Gold": gold_summary,
    }
    gold_feature_count = (
        len(
            [
                column
                for column in gold_summary["columns"]
                if column not in {"timestamp", "target_price_next_hour"}
            ]
        )
        if gold_summary["available"]
        else None
    )
    final_release, final_release_error = load_final_release_metadata(
        FINAL_RELEASE_MANIFEST,
        FINAL_HOLDOUT_METRICS,
    )
    report_availability = {
        PREDICTIONS_DATA: csv_has_rows(PREDICTIONS_DATA),
        ANOMALIES_DATA: csv_has_rows(ANOMALIES_DATA),
        FEATURE_IMPORTANCE_DATA: csv_has_rows(FEATURE_IMPORTANCE_DATA),
    }
    pipeline_history = load_recent_pipeline_history(PIPELINE_DATABASE, limit=10)
    quality_history = load_recent_data_quality_history(PIPELINE_DATABASE, limit=20)
    incident_history = load_recent_incidents(PIPELINE_DATABASE, limit=100)
    stage_timings = load_recent_stage_timings(PIPELINE_DATABASE, limit=200)
    latest_successful_run_time = load_latest_successful_run_time(PIPELINE_DATABASE)
    quality_counts = count_quality_statuses(quality_history)
    stored_message = latest_pipeline_run["message"] if latest_pipeline_run else None
    operational_metadata = parse_operational_metadata(stored_message)
    unresolved_gaps = (
        operational_metadata.get("unresolved_source_gaps", {})
        if isinstance(operational_metadata, dict)
        else {}
    )
    if not isinstance(unresolved_gaps, dict):
        unresolved_gaps = {}
    continuity_warning_count = len(unresolved_gaps)
    current_forecast, current_forecast_error = load_next24h_forecast_report(
        NEXT24H_FORECAST_DATA
    )
    forecast_issue = (
        current_forecast["forecast_issue_time"].iloc[0]
        if current_forecast_error is None else None
    )
    withheld = (
        isinstance(operational_metadata, dict)
        and operational_metadata.get("next24h_forecast_status") == "UNAVAILABLE"
    )
    forecast_status = forecast_freshness_state(
        forecast_issue, withholding_known=withheld
    )
    health = assess_operational_health(
        latest_run_status=latest_pipeline_run["status"] if latest_pipeline_run else None,
        latest_success_time=latest_successful_run_time,
        core_source_timestamps={
            name: source_summaries[name]["latest_timestamp"]
            for name in ("ENTSO-E prices", "ENTSO-E load", "ENTSO-E generation")
        },
        forecast_issue_time=forecast_issue,
        forecast_withheld=withheld,
        quality_state=latest_quality_state(quality_history),
        unresolved_gap_count=continuity_warning_count,
        required_artifacts_available=(
            final_release is not None
            and all(path.is_file() for path in (
                NEXT24H_RELEASE_MANIFEST, NEXT24H_RELEASE_MODEL,
                NEXT24H_RELEASE_CONTRACT,
            ))
        ),
    )
    email_alert_status = alert_configuration_status()
    page_title("Pipeline Summary", "Automated DataOps Workflow")

    section_header("System Health / Data Quality")
    health_message = f"{health['label']}. {health['reason']}"
    getattr(st, health["level"])(health_message)
    with st.expander("How health status is determined"):
        st.caption(
            "Hourly health rules: degraded for a failed latest run, missing release/core "
            "market source, failed current quality check, or >6-hour pipeline/core-market "
            "age; warning for >2-hour last success, >3-hour core-market age, stale/withheld "
            "forecast, or current quality/continuity warnings. Archive weather is excluded "
            "from live freshness thresholds."
        )

    health_metrics = [
        (
            "Latest Pipeline Status",
            str(latest_pipeline_run["status"])
            if latest_pipeline_run
            else "Unavailable",
        ),
        (
            "Latest Successful Run",
            fmt_timestamp(latest_successful_run_time),
        ),
        (
            "Latest Complete Market Hour",
            fmt_timestamp(
                operational_metadata.get("latest_complete_price_hour")
            ).removesuffix(" UTC")
            if isinstance(operational_metadata, dict)
            and operational_metadata.get("latest_complete_price_hour")
            else "Unavailable",
        ),
        (
            "S3 Sync Status",
            str(operational_metadata.get("s3_sync_status"))
            if isinstance(operational_metadata, dict)
            and operational_metadata.get("s3_sync_status") is not None
            else "Unavailable",
        ),
        ("Quality Checks Passed", fmt_int(quality_counts["passed"])),
        ("Quality Checks Failed", fmt_int(quality_counts["failed"])),
        ("Continuity Warnings", fmt_int(continuity_warning_count)),
        ("Next24h Forecast", forecast_status),
    ]
    try:
        next24h_release = json.loads(NEXT24H_RELEASE_MANIFEST.read_text(encoding="utf-8")).get("release_id")
    except (OSError, ValueError):
        next24h_release = None
    for metric_start in range(0, len(health_metrics), 4):
        metric_columns = st.columns(4)
        for column, (label, value) in zip(
            metric_columns,
            health_metrics[metric_start : metric_start + 4],
        ):
            column.metric(label, value)
    st.caption(
        f"Latest successful pipeline run: {fmt_timestamp(latest_successful_run_time)} · "
        f"Latest next24h issue: {fmt_timestamp(forecast_issue)} "
        f"({age_label(forecast_issue)})"
    )
    st.caption(
        f"Market: DE-LU · Storage: "
        f"{operational_metadata.get('storage_backend', 'Unavailable') if isinstance(operational_metadata, dict) else 'Unavailable'} "
        f"· One-hour model: {final_release['model_name'] if final_release else 'Unavailable'} "
        f"· Next24h release: {next24h_release or 'Unavailable'} "
        f"· Failure email alerts: {email_alert_status}"
    )

    section_header("Latest Pipeline Run")
    if latest_pipeline_run is None:
        st.warning(pipeline_run_error)
    else:
        records_label = "Recorded Row Count"
        records_value = latest_pipeline_run["records_processed"]
        if isinstance(operational_metadata, dict):
            run_message = str(operational_metadata.get("message") or "")
            if "No complete aligned raw hour advanced" in run_message:
                records_label = "New Rows Ingested"
                records_value = operational_metadata.get(
                    "new_rows_ingested", records_value
                )
            elif latest_pipeline_run["status"] == "SUCCESS":
                records_label = "Gold Rows Validated"

        col1, col2, col3 = st.columns(3)
        col1.metric("Pipeline Status", str(latest_pipeline_run["status"]))
        col2.metric("Latest Run Time", fmt_timestamp(latest_pipeline_run["run_time"]))
        col3.metric(records_label, fmt_int(records_value))

        if not isinstance(operational_metadata, dict):
            st.info(redact_operational_text(stored_message or "No pipeline message recorded."))
        else:
            summary_fields = [
                ("mode", "Mode"),
                ("storage_backend", "Storage Backend"),
                ("s3_sync_status", "S3 Sync Status"),
                ("new_rows_ingested", "New Rows Ingested"),
                ("predictions_generated", "Predictions Generated"),
                (
                    "latest_complete_price_hour",
                    "Latest Complete Price Hour (UTC)",
                ),
            ]
            available_fields = [
                (key, label, operational_metadata[key])
                for key, label in summary_fields
                if operational_metadata.get(key) is not None
            ]

            if available_fields:
                section_header("Operational Summary")
                for field_start in range(0, len(available_fields), 3):
                    columns = st.columns(3)
                    for column, (key, label, value) in zip(
                        columns,
                        available_fields[field_start : field_start + 3],
                    ):
                        if key in {"new_rows_ingested", "predictions_generated"}:
                            try:
                                value = fmt_int(value)
                            except (TypeError, ValueError):
                                value = str(value)
                        elif key == "latest_complete_price_hour":
                            value = fmt_timestamp(value).removesuffix(" UTC")
                        column.metric(label, str(value))

            st.info(redact_operational_text(
                operational_metadata.get("message") or "No pipeline message recorded."
            ))

            if unresolved_gaps:
                warning_count = len(unresolved_gaps)
                warning_label = "warning" if warning_count == 1 else "warnings"
                st.warning(
                    f"{warning_count} source continuity {warning_label} detected"
                )
                with st.expander("View source continuity details"):
                    gap_summaries = []
                    for source_name, gap_details in unresolved_gaps.items():
                        details = gap_details if isinstance(gap_details, dict) else {}
                        gap_summaries.append(
                            {
                                "Source": source_name,
                                "Last Contiguous Timestamp": details.get(
                                    "last_contiguous_timestamp"
                                ),
                                "First Unresolved Timestamp": details.get(
                                    "first_unresolved_timestamp"
                                ),
                                "Missing Count": details.get("missing_count", "N/A"),
                            }
                        )
                    for summary in gap_summaries:
                        summary["Last Contiguous Timestamp"] = fmt_timestamp(
                            summary["Last Contiguous Timestamp"]
                        )
                        summary["First Unresolved Timestamp"] = fmt_timestamp(
                            summary["First Unresolved Timestamp"]
                        )
                    st.dataframe(
                        pd.DataFrame(gap_summaries),
                        width="stretch",
                        hide_index=True,
                    )

    section_header("Recent Pipeline Execution History")
    if pipeline_history.empty:
        st.info("No pipeline execution history is available.")
    else:
        st.dataframe(
            prepare_pipeline_history(pipeline_history),
            width="stretch",
            hide_index=True,
        )

    section_header("Recent Data-Quality Check History")
    if quality_history.empty:
        st.info("No data-quality check history is available.")
    else:
        st.dataframe(
            prepare_data_quality_history(quality_history),
            width="stretch",
            hide_index=True,
        )

    section_header("Data-Source Health")
    issue_by_source = {}
    for incident in incident_history.to_dict(orient="records"):
        if incident.get("severity") not in {"WARNING", "ERROR"}:
            continue
        component = str(incident.get("component", ""))
        message = str(incident.get("message", ""))
        for source_name in (*source_summaries, "Open-Meteo operational weather", "next24h forecast"):
            if source_name not in issue_by_source and (
                source_name.lower() in component.lower()
                or source_name.lower() in message.lower()
            ):
                issue_by_source[source_name] = message
    source_rows = []
    for name, summary in source_summaries.items():
        timestamp = summary["latest_timestamp"]
        kind = (
            "historical_weather" if name == "Open-Meteo historical weather"
            else name.lower() if name in {"Silver", "Gold"}
            else "market"
        )
        source_rows.append({
            "Source": name,
            "Status": source_freshness_state(timestamp, source_kind=kind),
            "Latest UTC": fmt_timestamp(timestamp),
            "Age": age_label(timestamp),
            "Rows": summary["row_count"] if summary["available"] else None,
            "Last Known Issue": issue_by_source.get(name, ""),
        })
    operational_weather_time = (
        operational_metadata.get("next24h_weather_acquired_at_utc")
        if isinstance(operational_metadata, dict) else None
    )
    source_rows.extend([
        {
            "Source": "Open-Meteo operational weather",
            "Status": source_freshness_state(operational_weather_time, source_kind="market"),
            "Latest UTC": fmt_timestamp(operational_weather_time),
            "Age": age_label(operational_weather_time),
            "Rows": None,
            "Last Known Issue": issue_by_source.get("Open-Meteo operational weather", ""),
        },
        {
            "Source": "next24h forecast",
            "Status": forecast_status,
            "Latest UTC": fmt_timestamp(forecast_issue),
            "Age": age_label(forecast_issue),
            "Rows": len(current_forecast) if current_forecast_error is None else None,
            "Last Known Issue": issue_by_source.get("next24h forecast", ""),
        },
    ])
    st.dataframe(pd.DataFrame(source_rows), width="stretch", hide_index=True)
    st.caption("Historical weather and Silver/Gold are archive-aligned; operational weather is an in-memory issue-hour input, so its acquisition time—not an archive watermark—is shown.")

    section_header("Recent Operational Incidents")
    if incident_history.empty:
        st.info("No operational incidents have been recorded yet.")
    else:
        filters = st.columns(3)
        severity = filters[0].selectbox("Severity", ["All", *sorted(incident_history["severity"].dropna().unique())])
        component = filters[1].selectbox("Component", ["All", *sorted(incident_history["component"].dropna().unique())])
        period = filters[2].selectbox("Recent period", ["All", "24 hours", "7 days", "30 days"])
        visible = filter_incidents(
            incident_history, severity=severity, component=component, period=period,
        )
        if visible.empty:
            st.info("No incidents match these filters.")
        else:
            st.dataframe(
                visible.loc[:, ["timestamp_utc", "severity", "component", "message"]]
                .rename(columns={"timestamp_utc": "Time (UTC)", "severity": "Severity", "component": "Component", "message": "Message"}),
                width="stretch", hide_index=True,
            )

    section_header("Pipeline Performance")
    timing_summary = summarize_pipeline_timings(stage_timings)
    if timing_summary is None:
        st.info("Stage timings will appear after an instrumented pipeline run.")
    else:
        columns = st.columns(4)
        columns[0].metric("Latest Pipeline", f"{timing_summary['latest_total_seconds']:.1f} s")
        columns[1].metric("Recent Average (≤10)", f"{timing_summary['recent_average_seconds']:.1f} s" if timing_summary["recent_average_seconds"] is not None else "Unavailable")
        columns[2].metric("Forecast Generation", f"{timing_summary['latest_forecast_seconds']:.1f} s" if timing_summary["latest_forecast_seconds"] is not None else "Unavailable")
        columns[3].metric("Slowest Stage", timing_summary["slowest_stage"] or "Unavailable")
        with st.expander("View latest stage durations"):
            st.dataframe(
                timing_summary["latest_run_timings"].loc[:, ["stage_name", "duration_seconds", "status"]]
                .rename(columns={"stage_name": "Stage", "duration_seconds": "Seconds", "status": "Status"}),
                width="stretch", hide_index=True,
            )

    section_header("Dataset Status")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Silver Rows",
        fmt_int(silver_summary["row_count"])
        if silver_summary["available"]
        else "N/A",
    )
    col2.metric(
        "Gold Rows",
        fmt_int(gold_summary["row_count"])
        if gold_summary["available"]
        else "N/A",
    )
    col3.metric("Model Features", fmt_int(gold_feature_count))

    if silver_summary["available"] and "timestamp" in silver_summary["columns"]:
        st.caption(
            f"Silver historical coverage: {fmt_timestamp(earliest_timestamp)} to "
            f"{fmt_timestamp(latest_timestamp)}."
        )
    else:
        show_data_warning("Silver dataset", SILVER_DATA)

    if gold_summary["available"] and "timestamp" in gold_summary["columns"]:
        st.caption(
            f"Gold historical coverage: "
            f"{fmt_timestamp(gold_summary['earliest_timestamp'])} to "
            f"{fmt_timestamp(gold_summary['latest_timestamp'])}."
        )
    else:
        show_data_warning("Gold feature dataset", GOLD_DATA)

    section_header("Available Data Products")
    st.dataframe(
        pd.DataFrame(
            [
                {"Layer": "Silver", "Path": str(SILVER_DATA), "Status": "Available" if silver_summary["available"] else "Missing"},
                {"Layer": "Gold", "Path": str(GOLD_DATA), "Status": "Available" if gold_summary["available"] else "Missing"},
                {"Layer": "Final Model Release", "Path": str(FINAL_RELEASE_MANIFEST), "Status": "Available" if final_release is not None else "Missing"},
                {"Layer": "Final Holdout Metrics", "Path": str(FINAL_HOLDOUT_METRICS), "Status": "Available" if FINAL_HOLDOUT_METRICS.exists() else "Missing"},
                {"Layer": "Predictions", "Path": str(PREDICTIONS_DATA), "Status": "Available" if report_availability[PREDICTIONS_DATA] else "Missing"},
                {"Layer": "Anomalies", "Path": str(ANOMALIES_DATA), "Status": "Available" if report_availability[ANOMALIES_DATA] else "Missing"},
                {"Layer": "Feature Importance", "Path": str(FEATURE_IMPORTANCE_DATA), "Status": "Available" if report_availability[FEATURE_IMPORTANCE_DATA] else "Missing"},
            ]
        ),
        width="stretch",
        hide_index=True,
    )
