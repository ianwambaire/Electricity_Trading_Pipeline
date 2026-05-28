import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


DATABASE_PATH = Path("database/electricity_trading.db")


st.set_page_config(
    page_title="Electricity Trading Pipeline Dashboard",
    page_icon="⚡",
    layout="wide"
)


def load_table(table_name: str) -> pd.DataFrame:
    connection = sqlite3.connect(DATABASE_PATH)
    data = pd.read_sql_query(f"SELECT * FROM {table_name}", connection)
    connection.close()
    return data


st.title("⚡ Electricity Trading Data Pipeline Dashboard")

st.write(
    "This dashboard monitors electricity market data, pipeline execution, "
    "data quality checks, model performance, and machine learning predictions."
)

if not DATABASE_PATH.exists():
    st.error("Database not found. Run the pipeline first using: python src/run_pipeline.py")
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


market_data["timestamp"] = pd.to_datetime(market_data["timestamp"])


# Sidebar
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Go to",
    [
        "Overview",
        "Market Analytics",
        "Pipeline Monitoring",
        "Data Quality",
        "Model Performance",
        "Predictions"
    ]
)


# Overview Page
if page == "Overview":
    st.header("System Overview")

    total_records = len(market_data)
    average_price = market_data["market_price"].mean()
    average_demand = market_data["demand_mw"].mean()
    average_supply = market_data["supply_mw"].mean()

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total Records", total_records)
    col2.metric("Average Price", f"{average_price:.2f}")
    col3.metric("Average Demand MW", f"{average_demand:.2f}")
    col4.metric("Average Supply MW", f"{average_supply:.2f}")

    st.subheader("Latest Market Data")
    st.dataframe(market_data.tail(10), use_container_width=True)

    st.subheader("Price Trend")
    fig = px.line(
        market_data,
        x="timestamp",
        y="market_price",
        title="Electricity Market Price Over Time"
    )
    st.plotly_chart(fig, use_container_width=True)


# Market Analytics Page
elif page == "Market Analytics":
    st.header("Market Analytics")

    col1, col2 = st.columns(2)

    with col1:
        fig = px.line(
            market_data,
            x="timestamp",
            y="market_price",
            title="Market Price Trend"
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = px.line(
            market_data,
            x="timestamp",
            y=["demand_mw", "supply_mw"],
            title="Demand vs Supply"
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Price by Energy Source")
    fig = px.bar(
        market_data,
        x="energy_source",
        y="market_price",
        title="Market Price by Energy Source",
        color="energy_source"
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Supply-Demand Gap")
    fig = px.line(
        market_data,
        x="timestamp",
        y="supply_demand_gap",
        title="Supply-Demand Gap Over Time"
    )
    st.plotly_chart(fig, use_container_width=True)


# Pipeline Monitoring Page
elif page == "Pipeline Monitoring":
    st.header("Pipeline Monitoring")

    if pipeline_runs.empty:
        st.warning("No pipeline runs found.")
    else:
        latest_run = pipeline_runs.sort_values("run_time").tail(1).iloc[0]

        col1, col2, col3 = st.columns(3)

        col1.metric("Latest Status", latest_run["status"])
        col2.metric("Records Processed", latest_run["records_processed"])
        col3.metric("Last Run Time", latest_run["run_time"])

        st.subheader("Pipeline Run History")
        st.dataframe(
            pipeline_runs.sort_values("run_time", ascending=False),
            use_container_width=True
        )

        fig = px.bar(
            pipeline_runs,
            x="run_time",
            y="records_processed",
            color="status",
            title="Records Processed per Pipeline Run"
        )
        st.plotly_chart(fig, use_container_width=True)


# Data Quality Page
elif page == "Data Quality":
    st.header("Data Quality Results")

    if data_quality.empty:
        st.warning("No data quality results found.")
    else:
        passed_checks = len(data_quality[data_quality["status"] == "PASSED"])
        failed_checks = len(data_quality[data_quality["status"] == "FAILED"])

        col1, col2, col3 = st.columns(3)

        col1.metric("Total Checks", len(data_quality))
        col2.metric("Passed Checks", passed_checks)
        col3.metric("Failed Checks", failed_checks)

        st.subheader("Latest Data Quality Checks")
        st.dataframe(
            data_quality.sort_values("check_time", ascending=False),
            use_container_width=True
        )

        fig = px.pie(
            data_quality,
            names="status",
            title="Data Quality Status Distribution"
        )
        st.plotly_chart(fig, use_container_width=True)


# Model Performance Page
elif page == "Model Performance":
    st.header("Model Performance")

    if model_registry.empty:
        st.warning("No model records found. Run: python src/train_model.py")
    else:
        latest_model = model_registry.sort_values("training_date").tail(1).iloc[0]

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Model Version", latest_model["version"])
        col2.metric("MAE", f"{latest_model['mae']:.2f}")
        col3.metric("RMSE", f"{latest_model['rmse']:.2f}")
        col4.metric("R² Score", f"{latest_model['r2_score']:.2f}")

        st.subheader("Model Registry")
        st.dataframe(
            model_registry.sort_values("training_date", ascending=False),
            use_container_width=True
        )

        fig = px.line(
            model_registry,
            x="training_date",
            y=["mae", "rmse", "r2_score"],
            title="Model Metrics Over Time"
        )
        st.plotly_chart(fig, use_container_width=True)


# Predictions Page
elif page == "Predictions":
    st.header("Electricity Price Predictions")

    if predictions.empty:
        st.warning("No predictions found. Run: python src/predict.py")
    else:
        latest_prediction = predictions.sort_values("prediction_time").tail(1).iloc[0]

        col1, col2 = st.columns(2)

        col1.metric("Latest Predicted Price", f"{latest_prediction['predicted_price']:.2f}")
        col2.metric("Model Version", latest_prediction["model_version"])

        st.subheader("Prediction History")
        st.dataframe(
            predictions.sort_values("prediction_time", ascending=False),
            use_container_width=True
        )

        fig = px.line(
            predictions,
            x="prediction_time",
            y="predicted_price",
            title="Predicted Electricity Prices Over Time"
        )
        st.plotly_chart(fig, use_container_width=True)