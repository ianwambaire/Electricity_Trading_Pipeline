"""Static safety checks for the EC2 FastAPI deployment configuration."""

from __future__ import annotations

import configparser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = PROJECT_ROOT / "deploy" / "powerflow-api.service"
NGINX_PATH = PROJECT_ROOT / "deploy" / "nginx" / "powerflow-api-location.conf"
RUNBOOK_PATH = PROJECT_ROOT / "docs" / "api_ec2_deployment.md"


def _service_config() -> configparser.ConfigParser:
    # systemd permits repeated directives such as Environment=.
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(SERVICE_PATH.read_text(encoding="utf-8"))
    return parser


def test_api_systemd_unit_is_loopback_only_and_non_root() -> None:
    config = _service_config()
    service = config["Service"]

    assert service["User"] == "ec2-user"
    assert service["Group"] == "ec2-user"
    assert service["WorkingDirectory"] == "/home/ec2-user/Electricity_Trading_Pipeline"
    command = service["ExecStart"]
    assert command.startswith(
        "/home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/uvicorn "
    )
    assert "api.app:app" in command
    assert "--host 127.0.0.1" in command
    assert "--port 8000" in command
    assert "0.0.0.0" not in command
    assert service["Restart"] == "on-failure"
    assert config["Unit"]["After"] == "network-online.target"
    assert config["Install"]["WantedBy"] == "multi-user.target"


def test_api_systemd_unit_sets_required_pythonpath() -> None:
    unit = SERVICE_PATH.read_text(encoding="utf-8")

    assert (
        "Environment=PYTHONPATH=/home/ec2-user/Electricity_Trading_Pipeline/src"
        in unit
    )
    assert "EnvironmentFile=" not in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectHome=read-only" in unit


def test_nginx_api_fragment_preserves_prefix_and_forwarding_headers() -> None:
    nginx = NGINX_PATH.read_text(encoding="utf-8")

    assert "location /api/" in nginx
    assert "proxy_pass http://127.0.0.1:8000/;" in nginx
    assert "proxy_set_header Host $host;" in nginx
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in nginx
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in nginx
    assert "Access-Control-Allow" not in nginx
    assert "listen " not in nginx
    assert nginx.count("{") == nginx.count("}") == 1


def test_runbook_keeps_direct_port_private_and_checks_existing_services() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "sudo nginx -t" in runbook
    assert "systemctl status powerflow-api.service" in runbook
    assert "http://127.0.0.1:8000/health" in runbook
    assert "https://YOUR_POWERFLOW_HOST/api/health" in runbook
    assert "EC2_PUBLIC_IP:8000" in runbook
    assert "no inbound TCP rule for port 8000" in runbook
    assert "powerflow-streamlit.service" in runbook
    assert "powerflow-prefect-worker.service" in runbook
