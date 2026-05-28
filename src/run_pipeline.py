import time
from ingest_data import ingest_data
from clean_data import clean_data, save_clean_data
from validate_data import validate_data
from store_data import initialize_database, store_clean_data, log_pipeline_run
from utils.logger import get_logger


logger = get_logger(__name__)


def run_pipeline():
    records_processed = 0

    try:
        logger.info("Pipeline started.")

        logger.info("Starting data ingestion.")
        raw_data = ingest_data()
        logger.info(f"Data ingestion completed. Rows loaded: {len(raw_data)}")

        logger.info("Starting data cleaning.")
        cleaned_data = clean_data(raw_data)
        records_processed = len(cleaned_data)
        logger.info(f"Data cleaning completed. Rows after cleaning: {records_processed}")

        logger.info("Starting data validation.")
        validation_passed = validate_data(cleaned_data)

        initialize_database()

        if not validation_passed:
            log_pipeline_run(
                status="FAILED",
                records_processed=records_processed,
                message="Data validation failed."
            )
            logger.error("Pipeline failed because validation did not pass.")
            return False

        logger.info("Saving cleaned data.")
        save_clean_data(cleaned_data)

        logger.info("Storing cleaned data in database.")
        store_clean_data(cleaned_data)

        log_pipeline_run(
            status="SUCCESS",
            records_processed=records_processed,
            message="Pipeline completed successfully."
        )

        logger.info("Pipeline completed successfully.")
        return True

    except Exception as error:
        initialize_database()

        log_pipeline_run(
            status="FAILED",
            records_processed=records_processed,
            message=str(error)
        )

        logger.exception(f"Pipeline failed: {error}")
        return False


def run_pipeline_with_retries(max_retries=3, delay_seconds=5):
    for attempt in range(1, max_retries + 1):
        logger.info(f"Pipeline attempt {attempt} of {max_retries}")

        success = run_pipeline()

        if success:
            return True

        if attempt < max_retries:
            logger.warning(f"Retrying pipeline in {delay_seconds} seconds.")
            time.sleep(delay_seconds)

    logger.error("Pipeline failed after all retry attempts.")
    return False


if __name__ == "__main__":
    run_pipeline_with_retries()