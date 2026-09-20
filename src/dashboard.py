import json
from pathlib import Path
import sqlite3

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard_data import load_final_release_metadata


SILVER_DATA = Path("data/processed/silver_electricity_market_data.csv")
GOLD_DATA = Path("data/features/gold_model_features.csv")
PREDICTIONS_DATA = Path("data/reports/actual_vs_predicted.csv")
ANOMALIES_DATA = Path("data/reports/detected_anomalies.csv")
FEATURE_IMPORTANCE_DATA = Path("data/reports/feature_importance.csv")
FINAL_RELEASE_MANIFEST = Path("artifacts/models/final_model_release_manifest.json")
FINAL_HOLDOUT_METRICS = Path("data/reports/final_holdout_metrics.csv")
PIPELINE_DATABASE = Path("database/electricity_trading.db")


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


@st.cache_data(ttl=30)
def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_latest_pipeline_run(path: Path):
    if not path.exists():
        return None, f"Pipeline database not found at {path}."

    connection = None
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        row = connection.execute(
            """
            SELECT id, run_time, status, records_processed, message
            FROM pipeline_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error as exc:
        return None, f"Could not read pipeline history: {exc}"
    finally:
        if connection is not None:
            connection.close()

    if row is None:
        return None, "No pipeline runs have been recorded yet."

    return {
        "id": row[0],
        "run_time": row[1],
        "status": row[2],
        "records_processed": row[3],
        "message": row[4],
    }, None


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


silver_data = load_csv(SILVER_DATA)
gold_data = load_csv(GOLD_DATA)
predictions = load_csv(PREDICTIONS_DATA)
anomalies = load_csv(ANOMALIES_DATA)
feature_importance = load_csv(FEATURE_IMPORTANCE_DATA)
final_release, final_release_error = load_final_release_metadata(
    FINAL_RELEASE_MANIFEST,
    FINAL_HOLDOUT_METRICS,
)
latest_pipeline_run, pipeline_run_error = load_latest_pipeline_run(PIPELINE_DATABASE)

if "timestamp" in silver_data.columns:
    silver_data["timestamp"] = pd.to_datetime(
        silver_data["timestamp"], errors="coerce", utc=True
    )

if not gold_data.empty and "timestamp" in gold_data.columns:
    gold_data["timestamp"] = pd.to_datetime(
        gold_data["timestamp"], errors="coerce", utc=True
    )

if not predictions.empty and "timestamp" in predictions.columns:
    predictions["timestamp"] = pd.to_datetime(
        predictions["timestamp"], errors="coerce", utc=True
    )

if not anomalies.empty and "timestamp" in anomalies.columns:
    anomalies["timestamp"] = pd.to_datetime(
        anomalies["timestamp"], errors="coerce", utc=True
    )

silver_ready = has_columns(
    silver_data,
    ["timestamp", "price_eur_mwh", "load_mw", "wind_total_mw", "solar_mw"],
)
latest_timestamp = silver_data["timestamp"].max() if silver_ready else None
earliest_timestamp = silver_data["timestamp"].min() if silver_ready else None
latest_price = (
    silver_data.dropna(subset=["timestamp"])
    .sort_values("timestamp")
    .tail(1)["price_eur_mwh"]
    .iloc[0]
    if silver_ready and silver_data["timestamp"].notna().any()
    else None
)

gold_feature_count = (
    len(
        [
            column
            for column in gold_data.columns
            if column not in {"timestamp", "target_price_next_hour"}
        ]
    )
    if not gold_data.empty
    else None
)


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
                <strong>{fmt_int(len(silver_data)) if not silver_data.empty else 'N/A'}</strong>
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
            "Anomalies", fmt_int(len(anomalies)) if not anomalies.empty else "N/A"
        )

        section_header("Market Overview")
        col5, col6 = st.columns(2)

        with col5:
            st.markdown('<div class="chart-title">Electricity price trend</div>', unsafe_allow_html=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=silver_data["timestamp"],
                y=silver_data["price_eur_mwh"],
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
                x=silver_data["timestamp"],
                y=silver_data["load_mw"],
                mode="lines",
                line=dict(color="#16A3A3", width=1.4),
                name="Load MW",
            ))
            fig.add_trace(go.Scatter(
                x=silver_data["timestamp"],
                y=silver_data["wind_total_mw"] + silver_data["solar_mw"],
                mode="lines",
                line=dict(color="#2E9D68", width=1.4),
                name="Wind + Solar MW",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")

        section_header("Latest Historical Records")
        st.dataframe(
            silver_data.sort_values("timestamp", ascending=False).head(10),
            width="stretch",
            hide_index=True,
        )


elif page == "Market Intelligence":
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
            x=silver_data["timestamp"],
            y=silver_data["price_eur_mwh"],
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
                x=silver_data["timestamp"],
                y=silver_data["temperature_2m"],
                mode="lines",
                line=dict(color="#F59E0B", width=1.2),
                name="Temperature",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")

        with col2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=silver_data["timestamp"],
                y=silver_data["wind_speed_10m"],
                mode="lines",
                line=dict(color="#16A3A3", width=1.4),
                name="Wind Speed",
            ))
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")


elif page == "Forecasting":
    page_title("Forecasting", "Actual vs Predicted Price Forecast")

    if final_release is None:
        st.warning(final_release_error)
    else:
        section_header("Final Model Metrics")
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
        section_header("Actual vs Predicted")
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
            predictions.sort_values("timestamp", ascending=False).head(20),
            width="stretch",
            hide_index=True,
        )


elif page == "Anomaly Detection":
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
            section_header("Price Anomalies")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=silver_data["timestamp"],
                y=silver_data["price_eur_mwh"],
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
    page_title("Pipeline Summary", "Automated DataOps Workflow")

    section_header("Latest Pipeline Run")
    if latest_pipeline_run is None:
        st.warning(pipeline_run_error)
    else:
        stored_message = latest_pipeline_run["message"]
        try:
            operational_metadata = json.loads(stored_message)
        except (json.JSONDecodeError, TypeError):
            operational_metadata = None

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
            st.info(str(stored_message or "No pipeline message recorded."))
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

            st.info(
                str(
                    operational_metadata.get("message")
                    or "No pipeline message recorded."
                )
            )

            unresolved_gaps = operational_metadata.get("unresolved_source_gaps")
            if isinstance(unresolved_gaps, dict) and unresolved_gaps:
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

    section_header("Dataset Status")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Silver Rows", fmt_int(len(silver_data)) if not silver_data.empty else "N/A"
    )
    col2.metric(
        "Gold Rows", fmt_int(len(gold_data)) if not gold_data.empty else "N/A"
    )
    col3.metric("Model Features", fmt_int(gold_feature_count))

    if silver_ready:
        st.caption(
            f"Silver historical coverage: {fmt_timestamp(earliest_timestamp)} to "
            f"{fmt_timestamp(latest_timestamp)}."
        )
    else:
        show_data_warning("Silver dataset", SILVER_DATA)

    if has_columns(gold_data, ["timestamp"]):
        st.caption(
            f"Gold historical coverage: {fmt_timestamp(gold_data['timestamp'].min())} to "
            f"{fmt_timestamp(gold_data['timestamp'].max())}."
        )
    else:
        show_data_warning("Gold feature dataset", GOLD_DATA)

    section_header("Available Data Products")
    st.dataframe(
        pd.DataFrame(
            [
                {"Layer": "Silver", "Path": str(SILVER_DATA), "Status": "Available" if not silver_data.empty else "Missing"},
                {"Layer": "Gold", "Path": str(GOLD_DATA), "Status": "Available" if not gold_data.empty else "Missing"},
                {"Layer": "Final Model Release", "Path": str(FINAL_RELEASE_MANIFEST), "Status": "Available" if final_release is not None else "Missing"},
                {"Layer": "Final Holdout Metrics", "Path": str(FINAL_HOLDOUT_METRICS), "Status": "Available" if FINAL_HOLDOUT_METRICS.exists() else "Missing"},
                {"Layer": "Predictions", "Path": str(PREDICTIONS_DATA), "Status": "Available" if not predictions.empty else "Missing"},
                {"Layer": "Anomalies", "Path": str(ANOMALIES_DATA), "Status": "Available" if not anomalies.empty else "Missing"},
                {"Layer": "Feature Importance", "Path": str(FEATURE_IMPORTANCE_DATA), "Status": "Available" if not feature_importance.empty else "Missing"},
            ]
        ),
        width="stretch",
        hide_index=True,
    )
