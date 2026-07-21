import pytest

from backend_health.cli import build_parser, main


def test_run_exits_zero(tmp_path):
    assert main(["run", "--sink-dir", str(tmp_path), "--state-file", str(tmp_path / "h.json")]) == 0


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
            "--state-file",
            str(tmp_path / "h.json"),
        ]
    )
    assert rc == 0
    assert (tmp_path / "latency_samples.jsonl").exists()


def test_run_unknown_tenant_errors(tmp_path):
    rc = main(["run", "--tenant", "nope", "--sink-dir", str(tmp_path)])
    assert rc == 1


def test_run_non_active_tenant_errors(tmp_path):
    config = tmp_path / "tenants.yaml"
    config.write_text("tenants:\n  - tenant_id: paused-tenant\n    status: paused\n")
    rc = main(
        [
            "run",
            "--tenant",
            "paused-tenant",
            "--config",
            str(config),
            "--sink-dir",
            str(tmp_path),
        ]
    )
    assert rc == 1


def test_run_writes_health_state(tmp_path):
    state_file = tmp_path / "health.json"
    main(["run", "--sink-dir", str(tmp_path), "--state-file", str(state_file)])
    assert state_file.exists()
    assert '"consecutive_failures": 0' in state_file.read_text()


def test_pipeline_health_empty(tmp_path):
    rc = main(["pipeline-health", "--state-file", str(tmp_path / "missing.json")])
    assert rc == 0


def test_pipeline_health_after_run(tmp_path):
    state_file = tmp_path / "health.json"
    main(["run", "--sink-dir", str(tmp_path), "--state-file", str(state_file)])
    rc = main(["pipeline-health", "--state-file", str(state_file)])
    assert rc == 0


def test_no_command_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
