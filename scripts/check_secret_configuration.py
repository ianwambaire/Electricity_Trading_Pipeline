"""Report secret availability without printing protected values."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from powerflow_secrets import (  # noqa: E402
    SecretConfigurationError,
    secret_is_configured,
    secrets_backend,
)


PRODUCTION_SECRET_NAMES = (
    "ENTSOE_API_KEY",
    "ALERT_EMAIL_SENDER",
    "ALERT_EMAIL_PASSWORD",
    "ALERT_EMAIL_RECEIVER",
)


def configuration_report(names=PRODUCTION_SECRET_NAMES) -> dict:
    backend = secrets_backend()
    return {
        "backend": backend,
        "secrets": [
            {
                "secret_name": name,
                "status": "configured" if secret_is_configured(name) else "missing",
            }
            for name in names
        ],
    }


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    try:
        report = configuration_report()
    except SecretConfigurationError:
        report = {
            "backend": str(os.getenv("POWERFLOW_SECRETS_BACKEND", "env")),
            "secrets": [
                {"secret_name": name, "status": "missing"}
                for name in PRODUCTION_SECRET_NAMES
            ],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(2) from None
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
