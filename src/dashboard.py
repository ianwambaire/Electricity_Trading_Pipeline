from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


SILVER_DATA = Path("data/processed/silver_electricity_market_data.csv")
GOLD_DATA = Path("data/features/gold_model_features.csv")
PREDICTIONS_DATA = Path("data/reports/actual_vs_predicted.csv")
ANOMALIES_DATA = Path("data/reports/detected_anomalies.csv")
FEATURE_IMPORTANCE_DATA = Path("data/reports/feature_importance.csv")


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

    section[data-testid="stSidebar"] {
        background-color: #060B14;
        border-right: 1px solid #1a2744;
        padding-top: 0;
    }

    .sidebar-brand {
        background: linear-gradient(135deg, #0f1f3d 0%, #0a1628 100%);
        border-bottom: 1px solid #1a2744;
        padding: 20px 16px 18px 16px;
        margin-bottom: 16px;
    }

    .brand-logo {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.4rem;
        font-weight: 600;
        color: #F9FAFB;
        letter-spacing: 0.08em;
    }

    .bolt {
        color: #2563EB;
        font-size: 1.5rem;
    }

    .brand-tagline {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        color: #4B6A9B;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        margin-top: 4px;
    }

    .nav-section-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.6rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #2563EB;
        padding: 0 16px;
        margin: 12px 0 8px 0;
    }

    div[data-testid="stRadio"] label {
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 0.85rem;
        color: #7A90B8;
        padding: 6px 12px;
        border-radius: 4px;
    }

    div[data-testid="stRadio"] label:hover {
        color: #F9FAFB;
        background-color: #0f1f3d;
    }

    div[data-testid="metric-container"] {
        background: linear-gradient(160deg, #0d1b30 0%, #0a1220 100%);
        border: 1px solid #1a2744;
        border-top: 2px solid #2563EB;
        padding: 16px 18px;
        border-radius: 6px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    }

    div[data-testid="metric-container"] label {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 0.65rem !important;
        letter-spacing: 0.15em !important;
        text-transform: uppercase !important;
        color: #4B6A9B !important;
    }

    div[data-testid="metric-container"] [data-testid="metric-value"] {
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 1.6rem !important;
        font-weight: 600 !important;
        color: #F9FAFB !important;
    }

    .section-divider {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 1.5rem 0 1rem 0;
    }

    .section-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: #2563EB;
        white-space: nowrap;
    }

    .section-line {
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, #1a2744 0%, transparent 100%);
    }

    .chart-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #7A90B8;
        margin-bottom: 0.5rem;
    }

    h1 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-size: 1.65rem !important;
        font-weight: 700 !important;
        color: #F9FAFB !important;
    }

    h2, h3 {
        font-family: 'IBM Plex Mono', monospace !important;
        color: #4B6A9B !important;
    }

    #MainMenu, footer, header { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="IBM Plex Mono", color="#7A90B8", size=10),
    xaxis=dict(gridcolor="#111827", linecolor="#1a2744"),
    yaxis=dict(gridcolor="#111827", linecolor="#1a2744"),
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
)

CHART_COLORS = ["#2563EB", "#06B6D4", "#8B5CF6", "#10B981", "#F59E0B", "#EF4444"]


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


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
        subtitle_html = f"""
        <p style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#2D4A7A;
        margin-bottom:1.5rem;letter-spacing:0.04em;">{subtitle}</p>
        """

    st.markdown(
        f"""
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
        letter-spacing:0.2em;text-transform:uppercase;color:#2563EB;margin-bottom:6px;">
        {eyebrow}</div>
        <h1 style="margin-bottom:0.25rem;">{title}</h1>
        {subtitle_html}
        """,
        unsafe_allow_html=True,
    )


silver_data = load_csv(SILVER_DATA)
gold_data = load_csv(GOLD_DATA)
predictions = load_csv(PREDICTIONS_DATA)
anomalies = load_csv(ANOMALIES_DATA)
feature_importance = load_csv(FEATURE_IMPORTANCE_DATA)

if silver_data.empty:
    st.error("Run the ENTSO-E pipeline first: python src/orchestration/run_entsoe_pipeline.py")
    st.stop()

silver_data["timestamp"] = pd.to_datetime(silver_data["timestamp"])

if not gold_data.empty and "timestamp" in gold_data.columns:
    gold_data["timestamp"] = pd.to_datetime(gold_data["timestamp"])

if not predictions.empty and "timestamp" in predictions.columns:
    predictions["timestamp"] = pd.to_datetime(predictions["timestamp"])

if not anomalies.empty and "timestamp" in anomalies.columns:
    anomalies["timestamp"] = pd.to_datetime(anomalies["timestamp"])


latest_timestamp = silver_data["timestamp"].max()
latest_price = silver_data.sort_values("timestamp").tail(1)["price_eur_mwh"].iloc[0]


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
            "Forecasting",
            "Anomaly Detection",
            "Model Insights",
            "Pipeline Summary",
        ],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown(
        f"""
        <div style="font-family:'IBM Plex Mono',monospace; font-size:0.62rem; color:#2D4A7A; line-height:1.8;">
            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                <span>RECORDS</span>
                <span style="color:#4B6A9B">{fmt_int(len(silver_data))}</span>
            </div>
            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                <span>MARKET</span>
                <span style="color:#4B6A9B">DE_LU</span>
            </div>
            <div style="display:flex;justify-content:space-between;">
                <span>SYSTEM</span>
                <span style="color:#10B981">LIVE</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


if page == "Executive Overview":
    page_title(
        "Executive Overview",
        "Market Dashboard",
        "GERMANY-LUXEMBOURG ELECTRICITY TRADING INTELLIGENCE PLATFORM",
    )

    section_header("Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Hourly Records", fmt_int(len(silver_data)))
    col2.metric("Latest Price", f"{fmt(latest_price)} EUR/MWh")
    col3.metric("Avg Load", f"{fmt(silver_data['load_mw'].mean())} MW")
    col4.metric("Anomalies", fmt_int(len(anomalies)))

    section_header("Market Overview")
    col5, col6 = st.columns(2)

    with col5:
        st.markdown('<div class="chart-title">ELECTRICITY PRICE TREND</div>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=silver_data["timestamp"],
            y=silver_data["price_eur_mwh"],
            mode="lines",
            line=dict(color="#2563EB", width=1.3),
            name="Price EUR/MWh",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    with col6:
        st.markdown('<div class="chart-title">LOAD AND RENEWABLE GENERATION</div>', unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=silver_data["timestamp"],
            y=silver_data["load_mw"],
            mode="lines",
            line=dict(color="#06B6D4", width=1.2),
            name="Load MW",
        ))
        fig.add_trace(go.Scatter(
            x=silver_data["timestamp"],
            y=silver_data["wind_total_mw"] + silver_data["solar_mw"],
            mode="lines",
            line=dict(color="#10B981", width=1.2),
            name="Wind + Solar MW",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

    section_header("Latest Market Records")
    st.dataframe(
        silver_data.sort_values("timestamp", ascending=False).head(10),
        use_container_width=True,
        hide_index=True,
    )


elif page == "Market Intelligence":
    page_title("Market Intelligence", "Price and Generation Analysis")

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
        line=dict(color="#2563EB", width=1.3),
        name="Electricity Price",
    ))
    apply_chart_theme(fig)
    st.plotly_chart(fig, use_container_width=True)

    section_header("Generation Mix")
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

    gen_avg = silver_data[generation_cols].mean().reset_index()
    gen_avg.columns = ["source", "average_mw"]

    fig = px.bar(
        gen_avg.sort_values("average_mw", ascending=False),
        x="source",
        y="average_mw",
        color="source",
        color_discrete_sequence=CHART_COLORS,
    )
    apply_chart_theme(fig)
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

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
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=silver_data["timestamp"],
            y=silver_data["wind_speed_10m"],
            mode="lines",
            line=dict(color="#06B6D4", width=1.2),
            name="Wind Speed",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)


elif page == "Forecasting":
    page_title("Forecasting", "Actual vs Predicted Price Forecast")

    if predictions.empty:
        st.warning("No forecast results found. Run: python src/models/prediction_visualization.py")
    else:
        section_header("Model Metrics")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Best Model", "XGBoost")
        col2.metric("MAE", "9.10")
        col3.metric("RMSE", "18.91")
        col4.metric("R² Score", "0.90")

        section_header("Actual vs Predicted")
        plot_data = predictions.tail(500)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=plot_data["timestamp"],
            y=plot_data["actual_price"],
            mode="lines",
            line=dict(color="#2563EB", width=1.5),
            name="Actual Price",
        ))
        fig.add_trace(go.Scatter(
            x=plot_data["timestamp"],
            y=plot_data["predicted_price"],
            mode="lines",
            line=dict(color="#10B981", width=1.5),
            name="Predicted Price",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

        section_header("Forecast Records")
        st.dataframe(
            predictions.sort_values("timestamp", ascending=False).head(20),
            use_container_width=True,
            hide_index=True,
        )


elif page == "Anomaly Detection":
    page_title("Anomaly Detection", "Unusual Market Event Monitoring")

    if anomalies.empty:
        st.warning("No anomalies found. Run: python src/models/anomaly_detection.py")
    else:
        section_header("Anomaly Summary")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Detected Anomalies", fmt_int(len(anomalies)))
        col2.metric("Max Anomaly Price", fmt(anomalies["price_eur_mwh"].max()))
        col3.metric("Min Anomaly Price", fmt(anomalies["price_eur_mwh"].min()))
        col4.metric("Avg Anomaly Load", f"{fmt(anomalies['load_mw'].mean())} MW")

        section_header("Price Anomalies")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=silver_data["timestamp"],
            y=silver_data["price_eur_mwh"],
            mode="lines",
            line=dict(color="#2563EB", width=1),
            name="Price",
        ))
        fig.add_trace(go.Scatter(
            x=anomalies["timestamp"],
            y=anomalies["price_eur_mwh"],
            mode="markers",
            marker=dict(color="#EF4444", size=6),
            name="Anomaly",
        ))
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

        section_header("Top Anomaly Events")
        st.dataframe(
            anomalies.sort_values("price_eur_mwh", ascending=False).head(20),
            use_container_width=True,
            hide_index=True,
        )


elif page == "Model Insights":
    page_title("Model Insights", "Feature Importance and Model Drivers")

    if feature_importance.empty:
        st.warning("No feature importance file found. Run: python src/models/feature_importance.py")
    else:
        section_header("Top Feature Drivers")
        top_features = feature_importance.head(15)

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
        st.plotly_chart(fig, use_container_width=True)

        section_header("Feature Importance Table")
        st.dataframe(
            feature_importance,
            use_container_width=True,
            hide_index=True,
        )

        section_header("Interpretation")
        st.info(
            "The most influential variables are price history, rolling market prices, renewable share, "
            "hour-of-day effects, generation mix, and weather-related variables."
        )


elif page == "Pipeline Summary":
    page_title("Pipeline Summary", "Automated DataOps Workflow")

    section_header("Pipeline Architecture")
    st.code(
        """
ENTSO-E API
    ↓
Open-Meteo API
    ↓
Raw Data Layer
    ↓
Silver Cleaned Dataset
    ↓
Gold Feature Dataset
    ↓
XGBoost Model Training
    ↓
MLflow Experiment Tracking
    ↓
Forecast Visualization
    ↓
Anomaly Detection
        """,
        language="text",
    )

    section_header("Dataset Status")
    col1, col2, col3 = st.columns(3)
    col1.metric("Silver Rows", fmt_int(len(silver_data)))
    col2.metric("Gold Rows", fmt_int(len(gold_data)))
    col3.metric("Feature Count", fmt_int(gold_data.shape[1] if not gold_data.empty else 0))

    section_header("Available Data Products")
    st.dataframe(
        pd.DataFrame(
            [
                {"Layer": "Silver", "Path": str(SILVER_DATA), "Status": "Available"},
                {"Layer": "Gold", "Path": str(GOLD_DATA), "Status": "Available"},
                {"Layer": "Predictions", "Path": str(PREDICTIONS_DATA), "Status": "Available" if not predictions.empty else "Missing"},
                {"Layer": "Anomalies", "Path": str(ANOMALIES_DATA), "Status": "Available" if not anomalies.empty else "Missing"},
                {"Layer": "Feature Importance", "Path": str(FEATURE_IMPORTANCE_DATA), "Status": "Available" if not feature_importance.empty else "Missing"},
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )