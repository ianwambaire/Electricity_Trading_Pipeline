"""Application-level authentication and role checks for the PowerFlow dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, MutableMapping

from powerflow_secrets import SecretConfigurationError, get_secret, secrets_backend


AUTH_USERS_SECRET = "POWERFLOW_AUTH_USERS_JSON"
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = 600_000
MINIMUM_PBKDF2_ITERATIONS = 100_000
MAXIMUM_PBKDF2_ITERATIONS = 2_000_000
GENERIC_LOGIN_FAILURE = "Sign-in failed. Check your credentials and try again."
LOCKED_LOGIN_FAILURE = "Sign-in temporarily unavailable. Try again later."
SUPPORTED_ROLES = ("analyst", "admin")

ALL_DASHBOARD_PAGES = (
    "Executive Overview",
    "Market Intelligence",
    "Forecasting",
    "Anomaly Detection",
    "Model Insights",
    "Pipeline Summary",
)
ROLE_PAGE_ACCESS = {
    "analyst": tuple(page for page in ALL_DASHBOARD_PAGES if page != "Model Insights"),
    "admin": ALL_DASHBOARD_PAGES,
}
ADMIN_ONLY_SECTIONS = {
    "pipeline_run_details",
    "pipeline_execution_history",
    "operational_incidents",
    "pipeline_performance",
    "dataset_status",
    "release_provenance",
}

AUTH_SESSION_KEYS = (
    "authenticated",
    "username",
    "role",
    "display_name",
    "login_time",
    "last_activity_time",
    "failed_attempt_count",
    "lockout_until",
)
_LOGIN_USERNAME_WIDGET = "_powerflow_login_username"
_LOGIN_PASSWORD_WIDGET = "_powerflow_login_password"
_LOGIN_MESSAGE = "_powerflow_login_message"
_LOGIN_LOCKED = "_powerflow_login_locked"


class AuthConfigurationError(ValueError):
    """Raised for safe authentication configuration failures."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated role attempts a forbidden action."""


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    session_timeout_minutes: int
    max_login_attempts: int
    login_lockout_minutes: int
    backend: str


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str
    display_name: str


@dataclass(frozen=True)
class LoginResult:
    authenticated: bool
    message: str | None = None
    locked: bool = False


def _parse_bool(name: str, value: str | None, *, default: bool) -> bool:
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise AuthConfigurationError(f"{name} must be true or false.")


def _positive_integer(
    name: str,
    value: str | None,
    *,
    default: int,
    maximum: int = 10_080,
) -> int:
    try:
        parsed = default if value is None or not str(value).strip() else int(value)
    except (TypeError, ValueError):
        raise AuthConfigurationError(f"{name} must be a positive integer.") from None
    if parsed < 1 or parsed > maximum:
        raise AuthConfigurationError(
            f"{name} must be between 1 and {maximum}."
        )
    return parsed


def load_auth_settings(
    environment: Mapping[str, str] | None = None,
) -> AuthSettings:
    """Load non-secret authentication policy with conservative validation."""
    environment = os.environ if environment is None else environment
    try:
        backend = secrets_backend(environment)
    except SecretConfigurationError as exc:
        raise AuthConfigurationError(str(exc)) from None
    return AuthSettings(
        enabled=_parse_bool(
            "POWERFLOW_AUTH_ENABLED",
            environment.get("POWERFLOW_AUTH_ENABLED"),
            default=False,
        ),
        session_timeout_minutes=_positive_integer(
            "POWERFLOW_SESSION_TIMEOUT_MINUTES",
            environment.get("POWERFLOW_SESSION_TIMEOUT_MINUTES"),
            default=60,
        ),
        max_login_attempts=_positive_integer(
            "POWERFLOW_MAX_LOGIN_ATTEMPTS",
            environment.get("POWERFLOW_MAX_LOGIN_ATTEMPTS"),
            default=5,
            maximum=100,
        ),
        login_lockout_minutes=_positive_integer(
            "POWERFLOW_LOGIN_LOCKOUT_MINUTES",
            environment.get("POWERFLOW_LOGIN_LOCKOUT_MINUTES"),
            default=10,
        ),
        backend=backend,
    )


def _encode_component(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_component(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _parse_password_hash(encoded: str) -> tuple[int, bytes, bytes]:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        salt = _decode_component(salt_text)
        digest = _decode_component(digest_text)
    except (AttributeError, TypeError, ValueError):
        raise AuthConfigurationError("Password hash configuration is invalid.") from None
    if scheme != PASSWORD_HASH_SCHEME:
        raise AuthConfigurationError("Password hash configuration is invalid.")
    if not MINIMUM_PBKDF2_ITERATIONS <= iterations <= MAXIMUM_PBKDF2_ITERATIONS:
        raise AuthConfigurationError("Password hash configuration is invalid.")
    if len(salt) < 16 or len(digest) != hashlib.sha256().digest_size:
        raise AuthConfigurationError("Password hash configuration is invalid.")
    return iterations, salt, digest


def generate_password_hash(
    password: str,
    *,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    """Generate a salted PBKDF2-HMAC-SHA256 representation for configuration."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must not be empty.")
    if not MINIMUM_PBKDF2_ITERATIONS <= iterations <= MAXIMUM_PBKDF2_ITERATIONS:
        raise ValueError("PBKDF2 iteration count is outside the supported range.")
    salt = secrets.token_bytes(16) if salt is None else bytes(salt)
    if len(salt) < 16:
        raise ValueError("Password salt must contain at least 16 bytes.")
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return "$".join(
        (
            PASSWORD_HASH_SCHEME,
            str(iterations),
            _encode_component(salt),
            _encode_component(digest),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password using constant-time digest comparison."""
    try:
        iterations, salt, expected = _parse_password_hash(encoded_hash)
    except AuthConfigurationError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(candidate, expected)


def load_user_registry(
    environment: Mapping[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Read and validate hashed users without returning plaintext credentials."""
    try:
        raw = get_secret(
            AUTH_USERS_SECRET,
            required=True,
            environment=environment,
        )
    except SecretConfigurationError:
        raise AuthConfigurationError(
            f"Authentication configuration {AUTH_USERS_SECRET} is unavailable."
        ) from None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raise AuthConfigurationError(
            f"Authentication configuration {AUTH_USERS_SECRET} is invalid."
        ) from None
    if not isinstance(payload, dict) or not payload:
        raise AuthConfigurationError(
            f"Authentication configuration {AUTH_USERS_SECRET} is invalid."
        )

    users: dict[str, dict[str, str]] = {}
    for username, record in payload.items():
        if not isinstance(username, str) or not username.strip() or not isinstance(record, dict):
            raise AuthConfigurationError(
                f"Authentication configuration {AUTH_USERS_SECRET} is invalid."
            )
        if "password" in record or "plaintext_password" in record:
            raise AuthConfigurationError(
                f"Authentication configuration {AUTH_USERS_SECRET} is invalid."
            )
        password_hash = record.get("password_hash")
        role = str(record.get("role", "")).strip().lower()
        display_name = str(record.get("display_name", "")).strip()
        if not isinstance(password_hash, str) or role not in SUPPORTED_ROLES or not display_name:
            raise AuthConfigurationError(
                f"Authentication configuration {AUTH_USERS_SECRET} is invalid."
            )
        _parse_password_hash(password_hash)
        users[username.strip()] = {
            "password_hash": password_hash,
            "role": role,
            "display_name": display_name,
        }
    return users


def authenticate_credentials(
    username: str,
    password: str,
    users: Mapping[str, Mapping[str, str]],
) -> AuthUser | None:
    """Authenticate without distinguishing an unknown user from a bad password."""
    supplied_username = str(username).strip()
    matched_username = next(
        (
            candidate
            for candidate in users
            if hmac.compare_digest(candidate, supplied_username)
        ),
        None,
    )
    record = users.get(matched_username) if matched_username is not None else None
    # Perform one real PBKDF2 operation even for unknown users to reduce timing
    # clues without disclosing which configured hash supplied the comparison.
    comparison_hash = (
        str(record["password_hash"])
        if record is not None
        else str(next(iter(users.values()))["password_hash"])
    )
    if not verify_password(password, comparison_hash) or record is None:
        return None
    return AuthUser(
        username=matched_username,
        role=str(record["role"]),
        display_name=str(record["display_name"]),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def initialize_session_state(session: MutableMapping) -> None:
    defaults = {
        "authenticated": False,
        "username": None,
        "role": None,
        "display_name": None,
        "login_time": None,
        "last_activity_time": None,
        "failed_attempt_count": 0,
        "lockout_until": None,
    }
    for key, value in defaults.items():
        session.setdefault(key, value)


def clear_authentication_state(session: MutableMapping) -> None:
    """Remove authentication and login-widget state, including entered passwords."""
    for key in (
        *AUTH_SESSION_KEYS,
        _LOGIN_USERNAME_WIDGET,
        _LOGIN_PASSWORD_WIDGET,
        _LOGIN_MESSAGE,
        _LOGIN_LOCKED,
    ):
        session.pop(key, None)
    initialize_session_state(session)


def current_user(session: Mapping) -> AuthUser | None:
    if not session.get("authenticated"):
        return None
    role = str(session.get("role") or "")
    if role not in SUPPORTED_ROLES:
        return None
    return AuthUser(
        username=str(session.get("username") or ""),
        role=role,
        display_name=str(session.get("display_name") or ""),
    )


def session_has_timed_out(
    session: Mapping,
    settings: AuthSettings,
    *,
    now: datetime | None = None,
) -> bool:
    if not session.get("authenticated"):
        return False
    now = _utc_now() if now is None else now.astimezone(timezone.utc)
    last_activity = session.get("last_activity_time")
    if not isinstance(last_activity, datetime):
        return True
    last_activity = last_activity.astimezone(timezone.utc)
    return now - last_activity >= timedelta(minutes=settings.session_timeout_minutes)


def refresh_session_activity(
    session: MutableMapping,
    *,
    now: datetime | None = None,
) -> None:
    if session.get("authenticated"):
        session["last_activity_time"] = _utc_now() if now is None else now.astimezone(timezone.utc)


def attempt_login(
    session: MutableMapping,
    username: str,
    password: str,
    users: Mapping[str, Mapping[str, str]],
    settings: AuthSettings,
    *,
    now: datetime | None = None,
) -> LoginResult:
    """Apply session-scoped attempt counting and lockout to one login attempt."""
    initialize_session_state(session)
    now = _utc_now() if now is None else now.astimezone(timezone.utc)
    lockout_until = session.get("lockout_until")
    if isinstance(lockout_until, datetime):
        lockout_until = lockout_until.astimezone(timezone.utc)
        if now < lockout_until:
            return LoginResult(False, LOCKED_LOGIN_FAILURE, locked=True)
        session["lockout_until"] = None
        session["failed_attempt_count"] = 0

    user = authenticate_credentials(username, password, users)
    if user is None:
        failed_attempts = int(session.get("failed_attempt_count") or 0) + 1
        session["failed_attempt_count"] = failed_attempts
        if failed_attempts >= settings.max_login_attempts:
            session["lockout_until"] = now + timedelta(
                minutes=settings.login_lockout_minutes
            )
            return LoginResult(False, LOCKED_LOGIN_FAILURE, locked=True)
        return LoginResult(False, GENERIC_LOGIN_FAILURE)

    session.update(
        {
            "authenticated": True,
            "username": user.username,
            "role": user.role,
            "display_name": user.display_name,
            "login_time": now,
            "last_activity_time": now,
            "failed_attempt_count": 0,
            "lockout_until": None,
        }
    )
    return LoginResult(True)


def allowed_pages_for_role(role: str) -> tuple[str, ...]:
    return ROLE_PAGE_ACCESS.get(str(role).lower(), ())


def require_page_access(user: AuthUser, page: str) -> None:
    if page not in allowed_pages_for_role(user.role):
        raise AuthorizationError("This dashboard section is not available for your role.")


def can_access_section(user: AuthUser, section: str) -> bool:
    return section not in ADMIN_ONLY_SECTIONS or user.role == "admin"


def _render_login(st, settings: AuthSettings, users) -> None:
    st.markdown(
        """
        <div class="page-heading">
            <div class="page-eyebrow">PowerFlow</div>
            <h1>Sign in</h1>
            <p class="page-subtitle">Use your assigned PowerFlow dashboard account.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def submit_login() -> None:
        password = str(st.session_state.get(_LOGIN_PASSWORD_WIDGET, ""))
        result = attempt_login(
            st.session_state,
            str(st.session_state.get(_LOGIN_USERNAME_WIDGET, "")),
            password,
            users,
            settings,
        )
        st.session_state[_LOGIN_MESSAGE] = result.message
        st.session_state[_LOGIN_LOCKED] = result.locked
        st.session_state.pop(_LOGIN_PASSWORD_WIDGET, None)

    with st.form("powerflow_login_form"):
        st.text_input("Username", key=_LOGIN_USERNAME_WIDGET)
        st.text_input("Password", type="password", key=_LOGIN_PASSWORD_WIDGET)
        st.form_submit_button(
            "Sign in",
            on_click=submit_login,
            use_container_width=True,
        )
    message = st.session_state.get(_LOGIN_MESSAGE)
    if message:
        st.error(message)
    st.caption(
        "Access is controlled by application-level authentication. Contact the "
        "PowerFlow administrator if you cannot sign in."
    )


def require_authentication(st=None) -> AuthUser:
    """Enforce fail-closed Streamlit authentication before dashboard data loads."""
    if st is None:
        import streamlit as st

    try:
        settings = load_auth_settings()
    except AuthConfigurationError:
        st.error("Dashboard authentication configuration is invalid.")
        st.stop()
    if not settings.enabled:
        return AuthUser("local-development", "admin", "Local development")

    try:
        users = load_user_registry()
    except AuthConfigurationError:
        st.error("Dashboard authentication is enabled but user configuration is unavailable or invalid.")
        st.stop()

    initialize_session_state(st.session_state)
    if session_has_timed_out(st.session_state, settings):
        clear_authentication_state(st.session_state)
        st.session_state[_LOGIN_MESSAGE] = "Your session expired. Sign in again."

    user = current_user(st.session_state)
    if user is not None:
        refresh_session_activity(st.session_state)
        return user

    _render_login(st, settings, users)
    st.stop()


def render_authenticated_user(st, user: AuthUser) -> None:
    """Render a compact sidebar identity and an explicit logout action."""
    if user.username == "local-development":
        return
    st.markdown('<div class="nav-section-label">Signed in as</div>', unsafe_allow_html=True)
    st.markdown(f"**{user.display_name}**  \nRole: {user.role.title()}")

    def logout() -> None:
        clear_authentication_state(st.session_state)

    st.button("Logout", on_click=logout, use_container_width=True)
