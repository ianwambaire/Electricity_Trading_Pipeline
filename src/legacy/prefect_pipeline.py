from prefect import flow, task
from ingest_data import ingest_data
from clean_data import clean_data, save_clean_data
from validate_data import validate_data
from store_data import initialize_database, store_clean_data, log_pipeline_run


@task(retries=2, retry_delay_seconds=5)
def ingest_task():
    return ingest_data()


@task
def clean_task(raw_data):
    return clean_data(raw_data)


@task
def validate_task(cleaned_data):
    return validate_data(cleaned_data)


@task
def save_task(cleaned_data):
    save_clean_data(cleaned_data)


@task
def store_task(cleaned_data):
    initialize_database()
    store_clean_data(cleaned_data)


@flow(name="Electricity Trading Data Pipeline")
def electricity_trading_pipeline():
    raw_data = ingest_task()
    cleaned_data = clean_task(raw_data)

    validation_passed = validate_task(cleaned_data)

    if validation_passed:
        save_task(cleaned_data)
        store_task(cleaned_data)
        log_pipeline_run("SUCCESS", len(cleaned_data), "Prefect pipeline completed successfully.")
    else:
        initialize_database()
        log_pipeline_run("FAILED", len(cleaned_data), "Prefect validation failed.")


if __name__ == "__main__":
    electricity_trading_pipeline()