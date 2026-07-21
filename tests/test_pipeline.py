from datetime import datetime

from backend_health.bigquery_sink import JsonlSink
from backend_health.nerdgraph import DemoMetricsSource
from backend_health.pipeline import ingest_tenant, run
from backend_health.tenants import Tenant

COLLECTED_AT = datetime(2026, 7, 21, 12, 0, 0)


def _tenant(tid: str) -> Tenant:
    return Tenant(tenant_id=tid, status="active", newrelic_account_id="1", credential_ref=tid)


def test_ingest_tenant_writes_rows(tmp_path):
    result = ingest_tenant(_tenant("tenant-a"), DemoMetricsSource(), JsonlSink(tmp_path), COLLECTED_AT)
    assert result.ok
    assert result.rows_written > 0


def test_ingest_tenant_reports_partial_rows_on_mid_write_failure(tmp_path):
    """If a later table's write fails, rows already written for earlier tables
    must still be reflected in the result, not silently reported as zero."""

    class FlakySink(JsonlSink):
        def __init__(self, directory):
            super().__init__(directory)
            self.calls = 0

        def replace(self, table, tenant_id, collected_at, rows):
            self.calls += 1
            if self.calls == 2:  # fail on the second table this tenant writes
                raise RuntimeError("simulated BigQuery write failure")
            return super().replace(table, tenant_id, collected_at, rows)

    sink = FlakySink(tmp_path)
    result = ingest_tenant(_tenant("tenant-a"), DemoMetricsSource(), sink, COLLECTED_AT)

    assert not result.ok
    assert result.rows_written > 0, "rows written before the failing table must still be counted"
    assert "simulated BigQuery write failure" in result.error


def test_run_isolates_one_tenant_failure(tmp_path):
    class FlakySource:
        def fetch(self, tenant, collected_at):
            if tenant.tenant_id == "tenant-bad":
                raise RuntimeError("simulated New Relic outage")
            return DemoMetricsSource().fetch(tenant, collected_at)

    tenants = [_tenant("tenant-a"), _tenant("tenant-bad"), _tenant("tenant-c")]
    summary = run(tenants, FlakySource(), JsonlSink(tmp_path), COLLECTED_AT)

    assert summary.ok_count == 2
    assert summary.failed_count == 1
    assert not summary.all_ok

    by_id = {r.tenant_id: r for r in summary.results}
    assert by_id["tenant-a"].ok
    assert by_id["tenant-c"].ok
    assert not by_id["tenant-bad"].ok
    assert "simulated New Relic outage" in by_id["tenant-bad"].error

    # the other two tenants' data still landed despite the failure
    assert (tmp_path / "latency_samples.jsonl").exists()


def test_run_empty_tenant_list(tmp_path):
    summary = run([], DemoMetricsSource(), JsonlSink(tmp_path), COLLECTED_AT)
    assert summary.all_ok
    assert summary.total_rows == 0
