import json
from datetime import datetime

import pytest

from backend_health.bigquery_sink import JsonlSink, get_sink

WINDOW_A = datetime(2026, 7, 21, 12, 0, 0)
WINDOW_B = datetime(2026, 7, 21, 13, 0, 0)


def test_jsonl_sink_writes_rows(tmp_path):
    sink = JsonlSink(tmp_path)
    n = sink.replace(
        "latency_samples", "tenant-a", WINDOW_A, [{"tenant_id": "tenant-a", "collected_at": WINDOW_A.isoformat(), "v": 1}]
    )
    assert n == 1
    lines = (tmp_path / "latency_samples.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["v"] == 1


def test_jsonl_sink_replace_is_idempotent(tmp_path):
    sink = JsonlSink(tmp_path)

    def row(v):
        return {"tenant_id": "tenant-a", "collected_at": WINDOW_A.isoformat(), "v": v}

    sink.replace("t", "tenant-a", WINDOW_A, [row(1)])
    sink.replace("t", "tenant-a", WINDOW_A, [row(2)])  # re-run same window

    lines = (tmp_path / "t.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["v"] == 2


def test_jsonl_sink_keeps_other_windows_and_tenants(tmp_path):
    sink = JsonlSink(tmp_path)

    def row(tenant, window, v):
        return {"tenant_id": tenant, "collected_at": window.isoformat(), "v": v}

    sink.replace("t", "tenant-a", WINDOW_A, [row("tenant-a", WINDOW_A, 1)])
    sink.replace("t", "tenant-a", WINDOW_B, [row("tenant-a", WINDOW_B, 2)])
    sink.replace("t", "tenant-b", WINDOW_A, [row("tenant-b", WINDOW_A, 3)])
    sink.replace("t", "tenant-a", WINDOW_A, [row("tenant-a", WINDOW_A, 99)])

    lines = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    values = {(r["tenant_id"], r["collected_at"]): r["v"] for r in lines}
    assert values[("tenant-a", WINDOW_A.isoformat())] == 99
    assert values[("tenant-a", WINDOW_B.isoformat())] == 2
    assert values[("tenant-b", WINDOW_A.isoformat())] == 3
    assert len(lines) == 3


def test_get_sink_demo(tmp_path):
    assert isinstance(get_sink("demo", directory=tmp_path), JsonlSink)


def test_get_sink_bigquery_requires_dataset():
    with pytest.raises(ValueError, match="requires a dataset"):
        get_sink("bigquery")


def test_get_sink_unknown_mode():
    with pytest.raises(ValueError, match="unknown sink mode"):
        get_sink("bogus")
