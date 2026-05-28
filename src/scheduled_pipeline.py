from prefect import flow, task

from api_ingestion.run_api_ingestion import run_api_ingestion_pipeline
from run_pipeline import run_pipeline
from train_model import main as train_model
from predict import main as run_prediction


@task(retries=2, retry_delay_seconds=10)
def api_ingestion_task():
    run_api_ingestion_pipeline()


@task(retries=2, retry_delay_seconds=10)
def data_pipeline_task():
    success = run_pipeline()

    if not success:
        raise Exception("Data pipeline failed.")


@task(retries=1, retry_delay_seconds=10)
def train_model_task():
    train_model()


@task(retries=1, retry_delay_seconds=10)
def prediction_task():
    run_prediction()


@flow(name="Scheduled Electricity Trading Pipeline")
def scheduled_electricity_pipeline():
    api_ingestion_task()
    data_pipeline_task()
    train_model_task()
    prediction_task()


if __name__ == "__main__":
    scheduled_electricity_pipeline()