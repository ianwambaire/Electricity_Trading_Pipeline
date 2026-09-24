import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import auth
from scripts import check_auth_configuration, generate_auth_password_hash


PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery staple"
PASSWORD_HASH = auth.generate_password_hash(
    PASSWORD,
    iterations=auth.MINIMUM_PBKDF2_ITERATIONS,
    salt=b"test-auth-salt-01",
)


def _users_payload(role="admin", *, password_hash=PASSWORD_HASH):
    return json.dumps(
        {
            "ian_admin": {
                "password_hash": password_hash,
                "role": role,
                "display_name": "Ian",
            }
        }
    )


def _environment(**overrides):
    environment = {
        "POWERFLOW_AUTH_ENABLED": "true",
        "POWERFLOW_SECRETS_BACKEND": "env",
        "POWERFLOW_AUTH_USERS_JSON": _users_payload(),
        "POWERFLOW_SESSION_TIMEOUT_MINUTES": "60",
        "POWERFLOW_MAX_LOGIN_ATTEMPTS": "5",
        "POWERFLOW_LOGIN_LOCKOUT_MINUTES": "10",
    }
    environment.update(overrides)
    return environment


def _settings(**overrides):
    return auth.load_auth_settings(_environment(**overrides))


def _users(role="admin"):
    return auth.load_user_registry(
        _environment(POWERFLOW_AUTH_USERS_JSON=_users_payload(role))
    )


def _configure_role(monkeypatch, role):
    for name, value in _environment(
        POWERFLOW_AUTH_USERS_JSON=_users_payload(role)
    ).items():
        monkeypatch.setenv(name, value)


def _login(app):
    app.text_input[0].set_value("ian_admin")
    app.text_input[1].set_value(PASSWORD)
    app.button[0].click().run(timeout=30)
    return app


def _write_forecasting_fixture(tmp_path):
    issue = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=1)
    reports = tmp_path / "data/reports"
    reports.mkdir(parents=True)
    release_id = "next24h-hgb-internal-release"
    acquisition_time = (issue + pd.Timedelta(minutes=17)).isoformat()
    pd.DataFrame(
        {
            "forecast_issue_time": [issue] * 24,
            "target_timestamp": [
                issue + pd.Timedelta(hours=h) for h in range(1, 25)
            ],
            "horizon_hours": range(1, 25),
            "predicted_price_eur_mwh": [float(h) for h in range(1, 25)],
            "model_release": [release_id] * 24,
        }
    ).to_csv(reports / "next24h_forecast.csv", index=False)
    pd.DataFrame(
        {
            "forecast_issue_time": [issue],
            "target_timestamp": [issue + pd.Timedelta(hours=1)],
            "issued_at_utc": [issue + pd.Timedelta(minutes=20)],
        }
    ).to_csv(reports / "next24h_forecast_history.csv", index=False)
    (reports / "next24h_forecast_provenance.json").write_text(
        json.dumps(
            {
                "forecast_issue_time": issue.isoformat(),
                "market_latest_complete_hour": issue.isoformat(),
                "weather_acquired_at_utc": acquisition_time,
                "source_candidate_path": "/internal/release/candidate/path",
            }
        ),
        encoding="utf-8",
    )

    raw = tmp_path / "data/raw/entsoe"
    raw.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp": pd.date_range(end=issue, periods=168, freq="h", tz="UTC"),
            "price_eur_mwh": range(1, 169),
            "source_resolution": "PT60M",
        }
    ).to_csv(raw / "prices.csv", index=False)
    silver = tmp_path / "data/processed"
    silver.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp": [issue],
            "price_eur_mwh": [168.0],
            "load_mw": [40_000.0],
            "wind_total_mw": [5_000.0],
            "solar_mw": [1_000.0],
            "temperature_2m": [15.0],
        }
    ).to_csv(silver / "silver_electricity_market_data.csv", index=False)
    return release_id, acquisition_time


def _rendered_text(app):
    values = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.error):
        values.extend(str(element.value) for element in collection)
    for metric in app.metric:
        values.extend((str(metric.label), str(metric.value)))
    for dataframe in app.dataframe:
        values.append(" ".join(map(str, dataframe.value.columns)))
        values.append(dataframe.value.to_string(index=False))
    return "\n".join(values)


def test_authentication_disabled_defaults_to_local_development_admin():
    settings = auth.load_auth_settings({})
    assert settings.enabled is False
    assert settings.session_timeout_minutes == 60
    assert auth.allowed_pages_for_role("admin") == auth.ALL_DASHBOARD_PAGES


def test_authentication_enabled_loads_valid_hashed_users():
    settings = _settings()
    users = _users()
    assert settings.enabled is True
    assert len(users) == 1
    assert users["ian_admin"]["password_hash"] != PASSWORD


def test_enabled_authentication_missing_configuration_fails_closed():
    with pytest.raises(auth.AuthConfigurationError) as captured:
        auth.load_user_registry(
            {
                "POWERFLOW_AUTH_ENABLED": "true",
                "POWERFLOW_SECRETS_BACKEND": "env",
            }
        )
    assert auth.AUTH_USERS_SECRET in str(captured.value)


def test_valid_password_succeeds_without_storing_plaintext():
    session = {}
    result = auth.attempt_login(
        session, "ian_admin", PASSWORD, _users(), _settings(), now=NOW
    )
    assert result.authenticated is True
    assert session["authenticated"] is True
    assert session["role"] == "admin"
    assert PASSWORD not in session.values()
    assert "password" not in session


@pytest.mark.parametrize("username,password", [("ian_admin", "wrong"), ("unknown", PASSWORD)])
def test_wrong_password_and_unknown_user_use_same_generic_message(username, password):
    result = auth.attempt_login(
        {}, username, password, _users(), _settings(), now=NOW
    )
    assert result.authenticated is False
    assert result.message == auth.GENERIC_LOGIN_FAILURE


def test_analyst_and_admin_page_access_is_centralized():
    analyst = auth.AuthUser("analyst", "analyst", "Analyst")
    admin = auth.AuthUser("admin", "admin", "Admin")

    assert "Forecasting" in auth.allowed_pages_for_role("analyst")
    assert "Pipeline Summary" in auth.allowed_pages_for_role("analyst")
    assert "Model Insights" not in auth.allowed_pages_for_role("analyst")
    assert "Model Insights" in auth.allowed_pages_for_role("admin")
    with pytest.raises(auth.AuthorizationError):
        auth.require_page_access(analyst, "Model Insights")
    auth.require_page_access(admin, "Model Insights")
    assert not auth.can_access_section(analyst, "operational_incidents")
    assert auth.can_access_section(admin, "operational_incidents")
    assert auth.can_access_section(analyst, "data_quality")
    for page in auth.ALL_DASHBOARD_PAGES:
        if page in auth.allowed_pages_for_role("analyst"):
            auth.require_page_access(analyst, page)
        else:
            with pytest.raises(auth.AuthorizationError):
                auth.require_page_access(analyst, page)
        auth.require_page_access(admin, page)


def test_logout_clears_all_authentication_state():
    session = {}
    auth.attempt_login(session, "ian_admin", PASSWORD, _users(), _settings(), now=NOW)
    session["_powerflow_login_password"] = "must-be-removed"

    auth.clear_authentication_state(session)

    assert session["authenticated"] is False
    assert session["username"] is None
    assert session["role"] is None
    assert "must-be-removed" not in session.values()


def test_session_timeout_and_activity_refresh():
    session = {}
    auth.attempt_login(session, "ian_admin", PASSWORD, _users(), _settings(), now=NOW)
    settings = _settings(POWERFLOW_SESSION_TIMEOUT_MINUTES="30")

    assert not auth.session_has_timed_out(
        session, settings, now=NOW + timedelta(minutes=29)
    )
    assert auth.session_has_timed_out(
        session, settings, now=NOW + timedelta(minutes=30)
    )

    refreshed = NOW + timedelta(minutes=10)
    auth.refresh_session_activity(session, now=refreshed)
    assert session["last_activity_time"] == refreshed


def test_failed_attempt_counting_and_lockout_expiry():
    session = {}
    settings = _settings(
        POWERFLOW_MAX_LOGIN_ATTEMPTS="2",
        POWERFLOW_LOGIN_LOCKOUT_MINUTES="10",
    )
    users = _users()

    first = auth.attempt_login(session, "ian_admin", "wrong", users, settings, now=NOW)
    second = auth.attempt_login(session, "ian_admin", "wrong", users, settings, now=NOW)
    blocked = auth.attempt_login(session, "ian_admin", PASSWORD, users, settings, now=NOW)

    assert first.message == auth.GENERIC_LOGIN_FAILURE
    assert session["failed_attempt_count"] == 2
    assert second.locked is True
    assert blocked.locked is True
    assert blocked.authenticated is False

    recovered = auth.attempt_login(
        session,
        "ian_admin",
        PASSWORD,
        users,
        settings,
        now=NOW + timedelta(minutes=10),
    )
    assert recovered.authenticated is True
    assert session["failed_attempt_count"] == 0
    assert session["lockout_until"] is None


@pytest.mark.parametrize(
    "value",
    ["not-json", "[]", "{}"],
)
def test_malformed_users_json_is_rejected_safely(value):
    with pytest.raises(auth.AuthConfigurationError) as captured:
        auth.load_user_registry(_environment(POWERFLOW_AUTH_USERS_JSON=value))
    assert value not in str(captured.value)


def test_unsupported_role_and_plaintext_password_are_rejected():
    unsupported = json.dumps(
        {
            "user": {
                "password_hash": PASSWORD_HASH,
                "role": "owner",
                "display_name": "User",
            }
        }
    )
    plaintext = json.dumps(
        {
            "user": {
                "password": PASSWORD,
                "password_hash": PASSWORD_HASH,
                "role": "admin",
                "display_name": "User",
            }
        }
    )
    for value in (unsupported, plaintext):
        with pytest.raises(auth.AuthConfigurationError) as captured:
            auth.load_user_registry(_environment(POWERFLOW_AUTH_USERS_JSON=value))
        assert PASSWORD not in str(captured.value)


def test_password_hash_verification_and_generated_hash_round_trip():
    generated = auth.generate_password_hash(PASSWORD)
    assert generated.startswith("pbkdf2_sha256$")
    assert PASSWORD not in generated
    assert auth.verify_password(PASSWORD, generated)
    assert not auth.verify_password("wrong", generated)


def test_password_hash_script_uses_getpass_and_outputs_only_hash(monkeypatch, capsys):
    responses = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(generate_auth_password_hash.getpass, "getpass", lambda _prompt: next(responses))

    generate_auth_password_hash.main()

    output = capsys.readouterr().out.strip()
    assert PASSWORD not in output
    assert auth.verify_password(PASSWORD, output)


def test_diagnostic_output_contains_counts_but_no_usernames_or_hashes(monkeypatch):
    for name, value in _environment().items():
        monkeypatch.setenv(name, value)

    report = check_auth_configuration.configuration_report()
    rendered = json.dumps(report, sort_keys=True)

    assert report["auth_enabled"] is True
    assert report["configured_user_count"] == 1
    assert report["role_counts"] == {"admin": 1, "analyst": 0}
    assert "ian_admin" not in rendered
    assert PASSWORD_HASH not in rendered
    assert PASSWORD not in rendered


def test_secret_values_do_not_appear_in_configuration_errors_or_logs(caplog):
    protected = "never-log-this-secret"
    malformed = json.dumps({"user": {"password": protected}})
    with pytest.raises(auth.AuthConfigurationError) as captured:
        auth.load_user_registry(_environment(POWERFLOW_AUTH_USERS_JSON=malformed))
    assert protected not in str(captured.value)
    assert protected not in caplog.text


def test_streamlit_fails_closed_before_rendering_dashboard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POWERFLOW_AUTH_ENABLED", "true")
    monkeypatch.setenv("POWERFLOW_SECRETS_BACKEND", "env")
    monkeypatch.delenv("POWERFLOW_AUTH_USERS_JSON", raising=False)

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)

    assert not app.exception
    assert not app.radio
    assert any("configuration is unavailable or invalid" in error.value for error in app.error)


def test_invalid_auth_enabled_flag_fails_closed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POWERFLOW_AUTH_ENABLED", "sometimes")

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)

    assert not app.exception
    assert not app.radio
    assert any("configuration is invalid" in error.value for error in app.error)


@pytest.mark.parametrize(
    ("role", "model_insights_visible"),
    [("analyst", False), ("admin", True)],
)
def test_streamlit_login_and_role_filtered_navigation(
    monkeypatch, tmp_path, role, model_insights_visible
):
    monkeypatch.chdir(tmp_path)
    _configure_role(monkeypatch, role)

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    assert not app.radio
    assert [field.label for field in app.text_input] == ["Username", "Password"]

    _login(app)

    assert not app.exception
    assert app.radio
    assert ("Model Insights" in app.radio[0].options) is model_insights_visible
    assert any("Signed in as" in markdown.value for markdown in app.markdown)
    assert any(button.label == "Logout" for button in app.button)


def test_streamlit_logout_returns_to_login(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _configure_role(monkeypatch, "admin")

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    _login(app)
    next(button for button in app.button if button.label == "Logout").click().run(timeout=30)

    assert not app.exception
    assert not app.radio
    assert [field.label for field in app.text_input] == ["Username", "Password"]


def test_analyst_pipeline_summary_omits_admin_only_sections(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _configure_role(monkeypatch, "analyst")

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    _login(app)
    app.radio[0].set_value("Pipeline Summary").run(timeout=30)
    rendered = "\n".join(markdown.value for markdown in app.markdown)

    assert not app.exception
    assert "System Health / Data Quality" in rendered
    assert "Recent Data-Quality Check History" in rendered
    assert "Data-Source Health" in rendered
    assert "Latest Pipeline Run" not in rendered
    assert "Recent Pipeline Execution History" not in rendered
    assert "Recent Operational Incidents" not in rendered
    assert "Pipeline Performance" not in rendered
    assert "Dataset Status" not in rendered
    assert "Available Data Products" not in rendered
    assert all(
        "Last Known Issue" not in dataframe.value.columns
        for dataframe in app.dataframe
    )
    assert all("data/" not in warning.value for warning in app.warning)


@pytest.mark.parametrize("role", ["analyst", "admin"])
def test_forecasting_release_and_provenance_are_role_scoped(
    monkeypatch, tmp_path, role
):
    release_id, acquisition_time = _write_forecasting_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    _configure_role(monkeypatch, role)

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    _login(app)
    app.radio[0].set_value("Forecasting").run(timeout=30)
    rendered = _rendered_text(app)
    metric_labels = {metric.label for metric in app.metric}
    dataframe_columns = [set(dataframe.value.columns) for dataframe in app.dataframe]

    assert not app.exception
    assert "Market" in metric_labels
    assert "Forecast Freshness" in metric_labels
    assert "Forecast Issue (UTC)" in metric_labels
    assert "System Health" in metric_labels
    assert "Rolling Next 24-Hour Production Forecast" in rendered
    assert "Market Context" in rendered
    assert "Model Input Context" in rendered
    assert "Realized Next24h Performance" in rendered
    assert "Forecast generated at:" in rendered
    assert "Histogram Gradient Boosting" in rendered
    assert app.get("download_button")

    if role == "analyst":
        assert "Forecast Model" in metric_labels
        assert "Next24h Release" not in metric_labels
        assert release_id not in rendered
        assert acquisition_time not in rendered
        assert "/internal/release/candidate/path" not in rendered
        assert "data/" not in rendered
        assert "artifacts/" not in rendered
        assert all("model_release" not in columns for columns in dataframe_columns)
    else:
        assert "Next24h Release" in metric_labels
        assert release_id in rendered
        assert acquisition_time in rendered
        assert any("model_release" in columns for columns in dataframe_columns)


def test_admin_pipeline_summary_retains_technical_sections(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _configure_role(monkeypatch, "admin")

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    _login(app)
    app.radio[0].set_value("Pipeline Summary").run(timeout=30)
    rendered = _rendered_text(app)

    assert not app.exception
    assert "Latest Pipeline Run" in rendered
    assert "Recent Pipeline Execution History" in rendered
    assert "Recent Operational Incidents" in rendered
    assert "Pipeline Performance" in rendered
    assert "Dataset Status" in rendered
    assert "Available Data Products" in rendered
    assert any(
        "Last Known Issue" in dataframe.value.columns
        for dataframe in app.dataframe
    )
    assert "data/processed/silver_electricity_market_data.csv" in rendered


@pytest.mark.parametrize(
    "page",
    [
        "Executive Overview",
        "Market Intelligence",
        "Anomaly Detection",
    ],
)
def test_analyst_pages_do_not_expose_missing_dataset_paths(
    monkeypatch, tmp_path, page
):
    monkeypatch.chdir(tmp_path)
    _configure_role(monkeypatch, "analyst")

    app = AppTest.from_file(str(PROJECT_ROOT / "src" / "dashboard.py"))
    app.run(timeout=30)
    _login(app)
    app.radio[0].set_value(page).run(timeout=30)
    rendered = _rendered_text(app)

    assert not app.exception
    assert "data/" not in rendered
    assert "artifacts/" not in rendered
