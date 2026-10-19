#!/usr/bin/env python3
"""Report PowerFlow authentication readiness without exposing user credentials."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from auth import (  # noqa: E402
    AuthConfigurationError,
    load_auth_settings,
    load_user_registry,
    validate_cognito_streamlit_configuration,
)


def configuration_report(st_module=None) -> dict:
    settings = load_auth_settings()
    users = {}
    readable = False
    oidc_readable = False
    if settings.enabled and settings.provider == "legacy":
        users = load_user_registry()
        readable = True
    elif settings.enabled and settings.provider == "cognito":
        if st_module is None:
            import streamlit as st_module

        validate_cognito_streamlit_configuration(st_module)
        oidc_readable = True
    role_counts = Counter(record["role"] for record in users.values())
    return {
        "auth_enabled": settings.enabled,
        "auth_provider": settings.provider,
        "backend": settings.backend,
        "oidc_configuration_readable": oidc_readable,
        "users_configuration_readable": readable,
        "configured_user_count": len(users),
        "role_counts": {
            "admin": role_counts.get("admin", 0),
            "analyst": role_counts.get("analyst", 0),
        },
        "session_timeout_minutes": settings.session_timeout_minutes,
        "max_login_attempts": settings.max_login_attempts,
        "login_lockout_minutes": settings.login_lockout_minutes,
    }


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    try:
        report = configuration_report()
    except AuthConfigurationError:
        try:
            settings = load_auth_settings()
            backend = settings.backend
            enabled = settings.enabled
            provider = settings.provider
            timeout = settings.session_timeout_minutes
            attempts = settings.max_login_attempts
            lockout = settings.login_lockout_minutes
        except AuthConfigurationError:
            backend = "invalid"
            enabled = True
            provider = "invalid"
            timeout = None
            attempts = None
            lockout = None
        report = {
            "auth_enabled": enabled,
            "auth_provider": provider,
            "backend": backend,
            "oidc_configuration_readable": False,
            "users_configuration_readable": False,
            "configured_user_count": 0,
            "role_counts": {"admin": 0, "analyst": 0},
            "session_timeout_minutes": timeout,
            "max_login_attempts": attempts,
            "login_lockout_minutes": lockout,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(2) from None
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
