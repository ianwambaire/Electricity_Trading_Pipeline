import logging
import json

import pytest

import powerflow_secrets as secrets
from scripts.check_secret_configuration import configuration_report, main as diagnostic_main


@pytest.fixture(autouse=True)
def clear_cache():
    secrets.clear_secret_cache()
    yield
    secrets.clear_secret_cache()


def test_env_backend_returns_configured_value():
    environment = {
        "POWERFLOW_SECRETS_BACKEND": "env",
        "ENTSOE_API_KEY": "env-secret-value",
    }
    assert secrets.get_secret("ENTSOE_API_KEY", environment=environment) == (
        "env-secret-value"
    )


def test_missing_env_secret_has_name_only_error():
    with pytest.raises(secrets.SecretConfigurationError) as captured:
        secrets.get_secret("ENTSOE_API_KEY", environment={})
    message = str(captured.value)
    assert "ENTSOE_API_KEY" in message
    assert "unavailable" in message


def test_ssm_lookup_uses_decryption_and_no_static_credentials(monkeypatch):
    calls = []

    class Client:
        def get_parameter(self, **kwargs):
            calls.append(kwargs)
            return {"Parameter": {"Value": "ssm-secret-value"}}

    session_arguments = []
    client_arguments = []

    class Session:
        def __init__(self, **kwargs):
            session_arguments.append(kwargs)

        def get_credentials(self):
            return type("Credentials", (), {"method": "iam-role"})()

        def client(self, service_name):
            client_arguments.append(service_name)
            return Client()

    monkeypatch.setattr(secrets.boto3, "Session", Session)
    environment = {
        "POWERFLOW_SECRETS_BACKEND": "ssm",
        "POWERFLOW_SECRETS_PREFIX": "/powerflow/production",
        "AWS_REGION": "eu-west-1",
    }

    assert secrets.get_secret("ENTSOE_API_KEY", environment=environment) == (
        "ssm-secret-value"
    )
    assert session_arguments == [{"region_name": "eu-west-1"}]
    assert client_arguments == ["ssm"]
    assert calls == [{
        "Name": "/powerflow/production/ENTSOE_API_KEY",
        "WithDecryption": True,
    }]
    assert not any("access_key" in key for key in session_arguments[0])


def test_aws_backend_rejects_static_credential_environment(monkeypatch):
    monkeypatch.setattr(
        secrets.boto3,
        "Session",
        lambda *args, **kwargs: pytest.fail("boto3 must not be called"),
    )
    with pytest.raises(secrets.SecretConfigurationError) as captured:
        secrets.get_secret(
            "ENTSOE_API_KEY",
            environment={
                "POWERFLOW_SECRETS_BACKEND": "ssm",
                "AWS_ACCESS_KEY_ID": "must-not-appear",
                "AWS_SECRET_ACCESS_KEY": "must-not-appear-either",
            },
        )
    assert "must-not-appear" not in str(captured.value)
    assert "EC2 IAM role" in str(captured.value)


def test_aws_backend_rejects_non_instance_role_credentials(monkeypatch):
    class Session:
        def __init__(self, **kwargs):
            pass

        def get_credentials(self):
            return type("Credentials", (), {"method": "shared-credentials-file"})()

        def client(self, service_name):
            pytest.fail("provider client must not be used")

    monkeypatch.setattr(secrets.boto3, "Session", Session)
    with pytest.raises(secrets.SecretConfigurationError) as captured:
        secrets.get_secret(
            "ENTSOE_API_KEY",
            environment={"POWERFLOW_SECRETS_BACKEND": "ssm"},
        )
    assert "ENTSOE_API_KEY" in str(captured.value)
    assert "requires EC2 IAM role authentication" in str(captured.value)


def test_secrets_manager_lookup(monkeypatch):
    calls = []

    class Client:
        def get_secret_value(self, **kwargs):
            calls.append(kwargs)
            return {"SecretString": "manager-secret-value"}

    class Session:
        def __init__(self, **kwargs):
            pass

        def get_credentials(self):
            return type("Credentials", (), {"method": "iam-role"})()

        def client(self, service_name):
            assert service_name == "secretsmanager"
            return Client()

    monkeypatch.setattr(secrets.boto3, "Session", Session)
    environment = {
        "POWERFLOW_SECRETS_BACKEND": "secretsmanager",
        "POWERFLOW_SECRETS_PREFIX": "/powerflow/production/",
    }

    assert secrets.get_secret("ALERT_EMAIL_PASSWORD", environment=environment) == (
        "manager-secret-value"
    )
    assert calls == [{
        "SecretId": "powerflow/production/ALERT_EMAIL_PASSWORD"
    }]


def test_aws_lookup_is_cached(monkeypatch):
    call_count = 0

    class Client:
        def get_parameter(self, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"Parameter": {"Value": "cached-value"}}

    class Session:
        def __init__(self, **kwargs):
            pass

        def get_credentials(self):
            return type("Credentials", (), {"method": "iam-role"})()

        def client(self, service_name):
            return Client()

    monkeypatch.setattr(secrets.boto3, "Session", Session)
    environment = {"POWERFLOW_SECRETS_BACKEND": "ssm"}

    first = secrets.get_secret("ENTSOE_API_KEY", environment=environment)
    second = secrets.get_secret("ENTSOE_API_KEY", environment=environment)

    assert first == second == "cached-value"
    assert call_count == 1


def test_selected_aws_backend_does_not_fall_back_to_environment(monkeypatch):
    protected_value = "must-not-be-used"

    def session(*args, **kwargs):
        raise RuntimeError(f"provider failure {protected_value}")

    monkeypatch.setattr(secrets.boto3, "Session", session)
    environment = {
        "POWERFLOW_SECRETS_BACKEND": "ssm",
        "ENTSOE_API_KEY": protected_value,
    }

    with pytest.raises(secrets.SecretConfigurationError) as captured:
        secrets.get_secret("ENTSOE_API_KEY", environment=environment)
    assert protected_value not in str(captured.value)


def test_provider_errors_and_logs_do_not_leak_secret_content(monkeypatch, caplog):
    protected_value = "provider-secret-content"

    class Client:
        def get_secret_value(self, **kwargs):
            raise RuntimeError(protected_value)

    class Session:
        def __init__(self, **kwargs):
            pass

        def get_credentials(self):
            return type("Credentials", (), {"method": "iam-role"})()

        def client(self, service_name):
            return Client()

    monkeypatch.setattr(secrets.boto3, "Session", Session)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(secrets.SecretConfigurationError) as captured:
        secrets.get_secret(
            "ALERT_EMAIL_PASSWORD",
            environment={"POWERFLOW_SECRETS_BACKEND": "secretsmanager"},
        )

    assert protected_value not in str(captured.value)
    assert protected_value not in caplog.text
    assert "ALERT_EMAIL_PASSWORD" in str(captured.value)


def test_backend_misconfiguration_is_rejected_without_secret_values():
    with pytest.raises(secrets.SecretConfigurationError) as captured:
        secrets.get_secret(
            "ENTSOE_API_KEY",
            environment={
                "POWERFLOW_SECRETS_BACKEND": "automatic",
                "ENTSOE_API_KEY": "should-not-appear",
            },
        )
    assert "should-not-appear" not in str(captured.value)
    assert "env, ssm, secretsmanager" in str(captured.value)


def test_optional_env_secret_and_safe_status():
    assert secrets.get_secret(
        "ALERT_EMAIL_PASSWORD", required=False, environment={}
    ) is None
    assert secrets.secret_is_configured(
        "ALERT_EMAIL_PASSWORD", environment={}
    ) is False


def test_diagnostic_report_contains_statuses_but_never_values(monkeypatch):
    protected_values = {
        "ENTSOE_API_KEY": "diagnostic-api-secret",
        "ALERT_EMAIL_SENDER": "private-sender@example.com",
        "ALERT_EMAIL_PASSWORD": "diagnostic-password",
        "ALERT_EMAIL_RECEIVER": "private-receiver@example.com",
    }
    monkeypatch.setenv("POWERFLOW_SECRETS_BACKEND", "env")
    for name, value in protected_values.items():
        monkeypatch.setenv(name, value)

    rendered = json.dumps(configuration_report())

    assert all(value not in rendered for value in protected_values.values())
    assert rendered.count('"status": "configured"') == 4


def test_diagnostic_backend_error_has_structured_output_without_traceback(
    monkeypatch, capsys
):
    monkeypatch.setenv("POWERFLOW_SECRETS_BACKEND", "invalid")

    with pytest.raises(SystemExit) as captured:
        diagnostic_main()

    output = capsys.readouterr()
    parsed = json.loads(output.out)
    assert captured.value.code == 2
    assert parsed["backend"] == "invalid"
    assert {item["status"] for item in parsed["secrets"]} == {"missing"}
    assert output.err == ""
