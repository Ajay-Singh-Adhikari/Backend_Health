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
