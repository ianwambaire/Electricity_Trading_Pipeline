import os
import hashlib
import json
import math
import re
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()

DEFAULT_ALERT_COOLDOWN_HOURS = 12.0


def alert_cooldown_hours(environment=None) -> float:
    """Return the validated recurring-failure email cooldown."""
    environment = os.environ if environment is None else environment
    raw_value = environment.get(
        "POWERFLOW_ALERT_COOLDOWN_HOURS",
        str(DEFAULT_ALERT_COOLDOWN_HOURS),
    )
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError("POWERFLOW_ALERT_COOLDOWN_HOURS must be numeric.") from error
    if not math.isfinite(value) or not 1 <= value <= 168:
        raise ValueError("POWERFLOW_ALERT_COOLDOWN_HOURS must be between 1 and 168.")
    return value


def sanitize_failure_message(message: str) -> str:
    """Remove credential-like values and unstable identifiers from alert text."""
    safe = re.sub(r"(?i)\bBearer\s+[^\s&,;]+", "Bearer [REDACTED]", str(message))
    safe = re.sub(
        r"(?i)\b(password|secret|token|api[_-]?key|access[_-]?key|authorization)"
        r"\s*[:=]\s*[^\s&,;]+",
        r"\1=[REDACTED]",
        safe,
    )
    safe = re.sub(r"(?i)(://)[^\s/:@]+:[^\s@]+@", r"\1[REDACTED]@", safe)
    return " ".join(safe.split())[:1000]


def failure_fingerprint(component: str, category: str, message: str) -> str:
    """Hash stable, sanitized failure fields without persisting their contents."""
    normalized = sanitize_failure_message(message)
    normalized = re.sub(
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})\b",
        "[TIMESTAMP]",
        normalized,
    )
    normalized = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "[IDENTIFIER]",
        normalized,
    )
    payload = json.dumps(
        {
            "component": str(component).strip().casefold(),
            "category": str(category).strip().casefold(),
            "message": normalized.casefold(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def send_failure_alert(subject: str, message: str) -> str:
    sender = os.getenv("ALERT_EMAIL_SENDER")
    password = os.getenv("ALERT_EMAIL_PASSWORD")
    receiver = os.getenv("ALERT_EMAIL_RECEIVER")

    if not sender or not password or not receiver:
        print("Email alert settings missing. Skipping notification.")
        return "NOT_CONFIGURED"

    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = sender
    email["To"] = receiver
    email.set_content(message)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.send_message(email)

        print("Failure alert email sent successfully.")
        return "SENT"

    except Exception:
        # SMTP exception text may contain addresses or authentication details.
        print("Failed to send email alert; check protected service logs.")
        return "FAILED"
