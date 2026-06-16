import subprocess
import sys


def run_step(step_name, command):
    print(f"\n==============================")
    print(f"Running: {step_name}")
    print(f"==============================")

    result = subprocess.run(command, shell=True)

    if result.returncode != 0:
        print(f"\nFAILED: {step_name}")
        sys.exit(result.returncode)

    print(f"\nCOMPLETED: {step_name}")


def main():
    run_step("Fetch ENTSO-E Data", "python src/ingestion/fetch_entsoe_data.py")
    run_step("Fetch Weather Data", "python src/ingestion/fetch_weather_data.py")
    run_step("Build Silver Dataset", "python src/processing/build_silver_dataset.py")
    run_step("Build Gold Dataset", "python src/processing/build_gold_dataset.py")
    run_step("Train Forecasting Model", "python src/models/train_gold_model.py")
    run_step("Generate Prediction Visualization", "python src/models/prediction_visualization.py")
    run_step("Detect Market Anomalies", "python src/models/anomaly_detection.py")

    print("\nFULL ELECTRICITY TRADING PIPELINE COMPLETED SUCCESSFULLY")


if __name__ == "__main__":
    main()