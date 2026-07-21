import pytest

from backend_health.cli import build_parser, main


def test_run_exits_zero(tmp_path):
    assert main(["run", "--sink-dir", str(tmp_path)]) == 0


def test_run_accepts_tenant_and_config(tmp_path):
    rc = main(
        [
            "run",
            "--tenant",
            "tenant-a",
            "--config",
            "config/tenants.example.yaml",
            "--sink-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert (tmp_path / "latency_samples.jsonl").exists()


def test_run_unknown_tenant_errors(tmp_path):
    rc = main(["run", "--tenant", "nope", "--sink-dir", str(tmp_path)])
    assert rc == 1


def test_no_command_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
