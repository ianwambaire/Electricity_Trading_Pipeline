#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=0
BUCKET="${POWERFLOW_S3_BUCKET:-}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
TEMPORARY_FILE=""

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap_ec2_data.sh [--force] [--bucket NAME] [--region REGION]

Downloads missing PowerFlow production working files from S3. Existing files
are preserved unless --force is supplied. AWS credentials come from the normal
AWS CLI provider chain (the EC2 IAM role in production). Forecast-vintage files
are optional until their first collection; observed datasets and model releases
remain required.
EOF
}

cleanup() {
  if [[ -n "${TEMPORARY_FILE}" && -f "${TEMPORARY_FILE}" ]]; then
    rm -f -- "${TEMPORARY_FILE}"
  fi
}
trap cleanup EXIT

read_dotenv_value() {
  local key="$1"
  local file="$2"
  local line=""
  local value=""

  while IFS= read -r line; do
    [[ "${line}" == "${key}="* ]] || continue
    value="${line#*=}"
  done < "${file}"
  value="${value%$'\r'}"
  if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  [[ -n "${BUCKET}" ]] || BUCKET="$(
    read_dotenv_value POWERFLOW_S3_BUCKET "${PROJECT_ROOT}/.env"
  )"
  if [[ -z "${REGION}" ]]; then
    REGION="$(read_dotenv_value AWS_REGION "${PROJECT_ROOT}/.env")"
  fi
  if [[ -z "${REGION}" ]]; then
    REGION="$(read_dotenv_value AWS_DEFAULT_REGION "${PROJECT_ROOT}/.env")"
  fi
fi
REGION="${REGION:-us-east-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --bucket)
      [[ $# -ge 2 ]] || { echo "--bucket requires a value" >&2; exit 2; }
      BUCKET="$2"
      shift 2
      ;;
    --region)
      [[ $# -ge 2 ]] || { echo "--region requires a value" >&2; exit 2; }
      REGION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v aws >/dev/null 2>&1 || {
  echo "AWS CLI is required but was not found in PATH." >&2
  exit 1
}
[[ -n "${BUCKET}" ]] || {
  echo "POWERFLOW_S3_BUCKET or --bucket is required." >&2
  exit 1
}

directories=(
  data/raw/entsoe
  data/raw/entsoe/forecasts
  data/raw/weather
  data/processed
  data/features
  data/reports
  artifacts/models
  artifacts/models/releases/next24h
  database
  logs
)
for directory in "${directories[@]}"; do
  mkdir -p -- "${PROJECT_ROOT}/${directory}"
done

required_mappings=(
  "raw/entsoe/prices/prices.csv|data/raw/entsoe/prices.csv"
  "raw/entsoe/load/load.csv|data/raw/entsoe/load.csv"
  "raw/entsoe/generation/generation.csv|data/raw/entsoe/generation.csv"
  "raw/weather/open_meteo_weather.csv|data/raw/weather/open_meteo_weather.csv"
  "silver/silver_electricity_market_data.csv|data/processed/silver_electricity_market_data.csv"
  "gold/gold_model_features.csv|data/features/gold_model_features.csv"
  "models/releases/final_gold_model.joblib|artifacts/models/final_gold_model.joblib"
  "models/releases/final_gold_model_features.joblib|artifacts/models/final_gold_model_features.joblib"
  "models/releases/final_model_release_manifest.json|artifacts/models/final_model_release_manifest.json"
  "models/releases/next24h/next24h_model.joblib|artifacts/models/releases/next24h/next24h_model.joblib"
  "models/releases/next24h/next24h_feature_contract.joblib|artifacts/models/releases/next24h/next24h_feature_contract.joblib"
  "models/releases/next24h/next24h_release_manifest.json|artifacts/models/releases/next24h/next24h_release_manifest.json"
)

optional_mappings=(
  "raw/entsoe/forecasts/load/load_forecast_vintages.csv|data/raw/entsoe/forecasts/load_forecast_vintages.csv"
  "raw/entsoe/forecasts/wind-solar/wind_solar_forecast_vintages.csv|data/raw/entsoe/forecasts/wind_solar_forecast_vintages.csv"
  "raw/entsoe/forecasts/generation/generation_forecast_vintages.csv|data/raw/entsoe/forecasts/generation_forecast_vintages.csv"
  "raw/weather/operational-forecasts/open_meteo_forecast_vintages.csv|data/raw/weather/open_meteo_forecast_vintages.csv"
)

download_mapping() {
  local mapping="$1"
  local requirement="$2"
  local s3_key="${mapping%%|*}"
  local relative_path="${mapping#*|}"
  local destination="${PROJECT_ROOT}/${relative_path}"

  if [[ -f "${destination}" && "${FORCE}" -ne 1 ]]; then
    echo "Keeping existing ${relative_path}"
    return 0
  fi

  TEMPORARY_FILE="${destination}.download.$$"
  echo "Downloading s3://${BUCKET}/${s3_key} -> ${relative_path}"
  if ! aws s3 cp \
    "s3://${BUCKET}/${s3_key}" \
    "${TEMPORARY_FILE}" \
    --region "${REGION}" \
    --only-show-errors; then
    rm -f -- "${TEMPORARY_FILE}"
    TEMPORARY_FILE=""
    if [[ "${requirement}" == "optional" ]]; then
      echo "Optional forecast vintage unavailable; skipping ${relative_path}" >&2
      return 0
    fi
    echo "Required production artifact unavailable: s3://${BUCKET}/${s3_key}" >&2
    return 1
  fi
  mv -f -- "${TEMPORARY_FILE}" "${destination}"
  TEMPORARY_FILE=""
}

for mapping in "${required_mappings[@]}"; do
  download_mapping "${mapping}" required
done

for mapping in "${optional_mappings[@]}"; do
  download_mapping "${mapping}" optional
done

echo "PowerFlow EC2 data bootstrap completed successfully."
