"""Application-level authentication and role checks for the PowerFlow dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, MutableMapping

from powerflow_secrets import SecretConfigurationError, get_secret, secrets_backend


AUTH_USERS_SECRET = "POWERFLOW_AUTH_USERS_JSON"
AUTH_PROVIDER_ENV = "POWERFLOW_AUTH_PROVIDER"
SUPPORTED_AUTH_PROVIDERS = ("legacy", "cognito")
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = 600_000
MINIMUM_PBKDF2_ITERATIONS = 100_000
MAXIMUM_PBKDF2_ITERATIONS = 2_000_000
GENERIC_LOGIN_FAILURE = "Sign-in failed. Check your credentials and try again."
LOCKED_LOGIN_FAILURE = "Sign-in temporarily unavailable. Try again later."
SUPPORTED_ROLES = ("analyst", "admin")
DEFAULT_VERIFIED_ROLE = "analyst"
TRUSTED_ADMIN_GROUP = "powerflow-admins"
COGNITO_PROVIDER_NAME = "cognito"
COGNITO_ISSUER = (
    "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex"
)
COGNITO_APP_CLIENT_ID = "5qa93km3lf2bbu3ffnrpea4r3g"
COGNITO_METADATA_URL = f"{COGNITO_ISSUER}/.well-known/openid-configuration"
COGNITO_ALLOWED_CALLBACKS = frozenset(
    {
        "http://localhost:8501/oauth2callback",
        "https://powerflowenergy.dev/oauth2callback",
    }
)

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
    "dataset_paths",
    "forecast_release_metadata",
    "forecast_provenance_metadata",
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
    provider: str
    session_timeout_minutes: int
    max_login_attempts: int
    login_lockout_minutes: int
    backend: str


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str
    display_name: str
    auth_provider: str = "legacy"


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
    provider = str(environment.get(AUTH_PROVIDER_ENV, "legacy")).strip().lower()
    if provider not in SUPPORTED_AUTH_PROVIDERS:
        raise AuthConfigurationError(
            f"{AUTH_PROVIDER_ENV} must be legacy or cognito."
        )
    return AuthSettings(
        enabled=_parse_bool(
            "POWERFLOW_AUTH_ENABLED",
            environment.get("POWERFLOW_AUTH_ENABLED"),
            default=False,
        ),
        provider=provider,
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


def role_for_verified_identity(
    *,
    email_verified: bool,
    groups: object = None,
) -> str:
    """Map verified OIDC claims to a server-controlled dashboard role.

    The Cognito flow passes only claims from Streamlit's verified OIDC identity.
    Unverified identities fail closed, every verified identity defaults to
    Analyst, and Admin requires membership in the single trusted Cognito group
    managed outside the public registration flow.
    """
    if email_verified is not True:
        raise AuthorizationError(
            "A verified identity is required for dashboard access."
        )
    if not isinstance(groups, (list, tuple, set, frozenset)):
        groups = ()
    normalized_groups = {
        group.strip()
        for group in groups
        if isinstance(group, str) and group.strip()
    }
    if TRUSTED_ADMIN_GROUP in normalized_groups:
        return "admin"
    return DEFAULT_VERIFIED_ROLE


def _config_value(mapping: object, key: str) -> object:
    if isinstance(mapping, Mapping):
        return mapping.get(key)
    getter = getattr(mapping, "get", None)
    if callable(getter):
        return getter(key)
    return None


def _configured_secret(value: object, *, minimum_length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value.strip()) >= minimum_length
        and not value.strip().startswith("REPLACE_")
    )


def validate_cognito_streamlit_configuration(st) -> None:
    """Validate the non-secret OIDC contract without revealing secret values."""
    try:
        auth_section = st.secrets["auth"]
        provider_section = _config_value(auth_section, COGNITO_PROVIDER_NAME)
    except Exception:
        raise AuthConfigurationError(
            "Cognito authentication configuration is unavailable."
        ) from None

    redirect_uri = _config_value(auth_section, "redirect_uri")
    cookie_secret = _config_value(auth_section, "cookie_secret")
    client_id = _config_value(provider_section, "client_id")
    client_secret = _config_value(provider_section, "client_secret")
    metadata_url = _config_value(provider_section, "server_metadata_url")
    if (
        redirect_uri not in COGNITO_ALLOWED_CALLBACKS
        or client_id != COGNITO_APP_CLIENT_ID
        or metadata_url != COGNITO_METADATA_URL
        or not _configured_secret(cookie_secret, minimum_length=32)
        or not _configured_secret(client_secret, minimum_length=16)
    ):
        raise AuthConfigurationError(
            "Cognito authentication configuration is invalid."
        )

    if not all(callable(getattr(st, name, None)) for name in ("login", "logout")):
        raise AuthConfigurationError(
            "The installed Streamlit runtime does not support native OIDC."
        )
    try:
        import authlib

        version = tuple(int(part) for part in authlib.__version__.split(".")[:3])
    except (ImportError, ModuleNotFoundError, TypeError, ValueError):
        raise AuthConfigurationError(
            "The native OIDC runtime dependency is unavailable."
        ) from None
    if version < (1, 3, 2):
        raise AuthConfigurationError(
            "The native OIDC runtime dependency is unsupported."
        )


def cognito_user_from_claims(
    claims: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> AuthUser:
    """Build an authorized user from Streamlit's validated Cognito claims."""
    if not isinstance(claims, Mapping) or claims.get("is_logged_in") is not True:
        raise AuthorizationError("A valid Cognito identity is required.")
    if claims.get("provider") != COGNITO_PROVIDER_NAME:
        raise AuthorizationError("The OIDC identity provider is invalid.")
    issuer = claims.get("iss")
    audience = claims.get("aud")
    if not isinstance(issuer, str) or not hmac.compare_digest(
        issuer, COGNITO_ISSUER
    ):
        raise AuthorizationError("The OIDC identity issuer is invalid.")
    if not isinstance(audience, str) or not hmac.compare_digest(
        audience, COGNITO_APP_CLIENT_ID
    ):
        raise AuthorizationError("The OIDC identity audience is invalid.")
    if claims.get("token_use") != "id":
        raise AuthorizationError("The OIDC identity token type is invalid.")

    now = _utc_now() if now is None else now.astimezone(timezone.utc)
    expires_at = claims.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        raise AuthorizationError("The OIDC identity expiration is invalid.")
    if float(expires_at) <= now.timestamp():
        raise AuthorizationError("The OIDC identity has expired.")

    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthorizationError("The OIDC identity subject is invalid.")
    if not isinstance(email, str) or not email.strip():
        raise AuthorizationError("The OIDC identity email is invalid.")

    groups_claim = claims.get("cognito:groups")
    # Cognito defines this claim as an array. Any other shape is treated as no
    # trusted group membership so it can never elevate a user to Admin.
    groups = groups_claim if isinstance(groups_claim, list) else []
    role = role_for_verified_identity(
        email_verified=claims.get("email_verified") is True,
        groups=groups,
    )
    display_name = claims.get("name")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = email
    return AuthUser(
        username=subject.strip(),
        role=role,
        display_name=display_name.strip(),
        auth_provider=COGNITO_PROVIDER_NAME,
    )


def _render_authentication_brand(st) -> tuple[object, object]:
    brand_column, form_column = st.columns([1.12, 0.88], gap="large")
    with brand_column:
        st.markdown(
            """
            <section class="auth-brand-panel" aria-label="PowerFlow introduction">
                <div class="auth-wordmark"><span aria-hidden="true">⚡</span> PowerFlow</div>
                <div class="auth-kicker">Electricity market operations</div>
                <h1>Decisions backed by a dependable market pipeline.</h1>
                <p class="auth-description">
                    Secure access to DE-LU market intelligence, forecasts,
                    anomaly monitoring, and production pipeline health.
                </p>
                <div class="auth-context" role="note">
                    <span>Restricted workspace</span>
                    <span aria-hidden="true">·</span>
                    <span>Germany–Luxembourg</span>
                </div>
            </section>
            """,
            unsafe_allow_html=True,
        )
    return brand_column, form_column


def _render_legacy_login(st, settings: AuthSettings, users) -> None:
    _, form_column = _render_authentication_brand(st)

    with form_column:
        st.markdown(
            """
            <div class="auth-form-heading">
                <div class="auth-kicker">Secure account access</div>
                <h2>Welcome back</h2>
                <p>Sign in with the PowerFlow account assigned to you.</p>
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
            st.text_input(
                "Username",
                key=_LOGIN_USERNAME_WIDGET,
                placeholder="Enter your username",
            )
            st.text_input(
                "Password",
                type="password",
                key=_LOGIN_PASSWORD_WIDGET,
                placeholder="Enter your password",
            )
            st.form_submit_button(
                "Sign in",
                on_click=submit_login,
                use_container_width=True,
            )
        message = st.session_state.get(_LOGIN_MESSAGE)
        if message:
            st.error(message)
        st.markdown(
            """
            <div class="auth-support-note">
                <strong>Need access?</strong> Registration is not enabled yet.
                Contact the PowerFlow administrator for an assigned account or
                help recovering access.
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_cognito_login(st) -> None:
    _, form_column = _render_authentication_brand(st)
    with form_column:
        st.markdown(
            """
            <div class="auth-form-heading">
                <div class="auth-kicker">Secure account access</div>
                <h2>Continue to PowerFlow</h2>
                <p>
                    Sign in with email and password or Google through the
                    PowerFlow secure identity service.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Continue to secure sign in",
            use_container_width=True,
            type="primary",
        ):
            st.login(COGNITO_PROVIDER_NAME)
        st.markdown(
            """
            <div class="auth-support-note">
                <strong>Account access</strong> Registration, email
                verification, and recovery are handled in the secure sign-in
                portal when enabled by the PowerFlow administrator.
            </div>
            """,
            unsafe_allow_html=True,
        )


def _require_cognito_authentication(st) -> AuthUser:
    try:
        validate_cognito_streamlit_configuration(st)
    except AuthConfigurationError:
        st.error("Cognito authentication configuration is unavailable or invalid.")
        st.stop()

    try:
        claims = dict(st.user)
    except Exception:
        st.error("Cognito authentication is temporarily unavailable.")
        st.stop()
    if claims.get("is_logged_in") is not True:
        _render_cognito_login(st)
        st.stop()

    try:
        return cognito_user_from_claims(claims)
    except AuthorizationError:
        st.error(
            "Your authenticated identity could not be verified for PowerFlow. "
            "Sign out and try again, or contact the PowerFlow administrator."
        )
        st.button(
            "Return to sign in",
            on_click=st.logout,
            use_container_width=True,
        )
        st.stop()


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
        return AuthUser(
            "local-development",
            "admin",
            "Local development",
            auth_provider="local",
        )

    if settings.provider == COGNITO_PROVIDER_NAME:
        return _require_cognito_authentication(st)

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

    _render_legacy_login(st, settings, users)
    st.stop()


def render_authenticated_user(st, user: AuthUser) -> None:
    """Render a compact sidebar identity and an explicit logout action."""
    if user.username == "local-development":
        return
    safe_name = html.escape(user.display_name)
    safe_role = html.escape(user.role.title())
    initial = html.escape(
        (user.display_name.strip() or user.username.strip() or "P")[0].upper()
    )
    st.markdown(
        f"""
        <div class="sidebar-profile" aria-label="Signed-in profile">
            <div class="sidebar-profile-avatar" aria-hidden="true">{initial}</div>
            <div class="sidebar-profile-copy">
                <div class="sidebar-profile-label">Signed in</div>
                <div class="sidebar-profile-name">{safe_name}</div>
                <div class="sidebar-profile-role">{safe_role} access</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def logout() -> None:
        if user.auth_provider == COGNITO_PROVIDER_NAME:
            st.logout()
        else:
            clear_authentication_state(st.session_state)

    st.button(
        "Sign out",
        on_click=logout,
        use_container_width=True,
        type="secondary",
    )
