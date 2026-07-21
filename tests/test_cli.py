import pytest

from backend_health.cli import build_parser, main


def test_run_exits_zero():
    assert main(["run"]) == 0


def test_run_accepts_tenant_and_config():
    assert main(["run", "--tenant", "tenant-a", "--config", "config/tenants.example.yaml"]) == 0


def test_no_command_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
