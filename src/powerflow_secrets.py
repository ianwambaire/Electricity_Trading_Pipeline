"""Production-safe secret lookup with explicit, non-fallback backends."""

from __future__ import annotations

import base64
import os
import re
from functools import lru_cache
from typing import Mapping

import boto3


SUPPORTED_SECRET_BACKENDS = ("env", "ssm", "secretsmanager")
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_SECRET_PREFIX = "/powerflow/production"
_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_STATIC_AWS_CREDENTIAL_KEYS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


class SecretConfigurationError(ValueError):
    """Raised without including protected values or provider error details."""


def secrets_backend(environment: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environment is None else environment
    backend = str(environment.get("POWERFLOW_SECRETS_BACKEND", "env")).strip().lower()
    if backend not in SUPPORTED_SECRET_BACKENDS:
        supported = ", ".join(SUPPORTED_SECRET_BACKENDS)
        raise SecretConfigurationError(
            f"POWERFLOW_SECRETS_BACKEND must be one of: {supported}."
        )
    return backend


def _validate_secret_name(name: str) -> str:
    normalized = str(name).strip()
    if not _SECRET_NAME_PATTERN.fullmatch(normalized):
        raise SecretConfigurationError("Secret name has an invalid format.")
    return normalized


def _aws_region(environment: Mapping[str, str]) -> str:
    return str(
        environment.get("AWS_REGION")
        or environment.get("AWS_DEFAULT_REGION")
        or DEFAULT_AWS_REGION
    ).strip()


def _reject_static_aws_credentials(
    environment: Mapping[str, str],
    secret_name: str,
) -> None:
    if any(str(environment.get(key, "")).strip() for key in _STATIC_AWS_CREDENTIAL_KEYS):
        raise SecretConfigurationError(
            f"Secret {secret_name} cannot use static AWS credential environment "
            "variables; use the EC2 IAM role."
        )


def _secret_identifier(
    name: str,
    backend: str,
    environment: Mapping[str, str],
) -> str:
    override = str(environment.get(f"POWERFLOW_SECRET_ID_{name}", "")).strip()
    if override:
        return override
    prefix = str(
        environment.get("POWERFLOW_SECRETS_PREFIX", DEFAULT_SECRET_PREFIX)
    ).strip()
    prefix = prefix.rstrip("/")
    if backend == "ssm" and not prefix.startswith("/"):
        prefix = f"/{prefix}"
    if backend == "secretsmanager":
        prefix = prefix.lstrip("/")
    return f"{prefix}/{name}"


@lru_cache(maxsize=128)
def _load_aws_secret(
    backend: str,
    identifier: str,
    region: str,
    secret_name: str,
) -> str:
    """Fetch one secret only when boto3 resolved an EC2 instance-role identity."""
    try:
        session = boto3.Session(region_name=region)
        credentials = session.get_credentials()
        if credentials is None or getattr(credentials, "method", None) != "iam-role":
            raise SecretConfigurationError(
                f"Secret {secret_name} requires EC2 IAM role authentication."
            )
        if backend == "ssm":
            client = session.client("ssm")
            response = client.get_parameter(Name=identifier, WithDecryption=True)
            value = response.get("Parameter", {}).get("Value")
        else:
            client = session.client("secretsmanager")
            response = client.get_secret_value(SecretId=identifier)
            value = response.get("SecretString")
            if value is None and response.get("SecretBinary") is not None:
                binary = response["SecretBinary"]
                if isinstance(binary, str):
                    binary = base64.b64decode(binary)
                value = bytes(binary).decode("utf-8")
    except SecretConfigurationError:
        raise
    except Exception:
        raise SecretConfigurationError(
            f"Secret {secret_name} is unavailable from backend {backend}."
        ) from None

    if value is None or not str(value).strip():
        raise SecretConfigurationError(
            f"Secret {secret_name} is unavailable from backend {backend}."
        )
    return str(value)


def get_secret(
    name: str,
    *,
    required: bool = True,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve a secret from the explicitly configured backend.

    The env backend preserves local compatibility. AWS backends intentionally
    ignore same-named environment values so a failed production lookup cannot
    silently fall back to a long-lived local credential.
    """
    name = _validate_secret_name(name)
    environment = os.environ if environment is None else environment
    backend = secrets_backend(environment)
    if backend == "env":
        value = environment.get(name)
        if value is not None and str(value).strip():
            return str(value)
        if not required:
            return None
        raise SecretConfigurationError(
            f"Secret {name} is unavailable from backend env."
        )

    _reject_static_aws_credentials(environment, name)
    return _load_aws_secret(
        backend,
        _secret_identifier(name, backend, environment),
        _aws_region(environment),
        name,
    )


def secret_is_configured(
    name: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return only availability state, never the protected value."""
    try:
        return get_secret(name, required=True, environment=environment) is not None
    except SecretConfigurationError:
        return False


def clear_secret_cache() -> None:
    """Clear process-local AWS lookup results, primarily for tests/rotation."""
    _load_aws_secret.cache_clear()
