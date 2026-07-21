from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from backend_health.alerts import Alerter, LoggingAlerter
from backend_health.bigquery_schema import to_rows
from backend_health.bigquery_sink import Sink
from backend_health.health_state import PipelineHealthState
from backend_health.nerdgraph import MetricsSource
from backend_health.retry import retry_with_backoff
from backend_health.tenants import Tenant

log = logging.getLogger("backend_health.pipeline")

DEFAULT_ALERT_THRESHOLD = 3
DEFAULT_RETRY_ATTEMPTS = 3


@dataclass
class TenantResult:
    tenant_id: str
    ok: bool
    rows_written: int = 0
    error: str | None = None


@dataclass
class RunSummary:
    results: list[TenantResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def total_rows(self) -> int:
        return sum(r.rows_written for r in self.results)

    @property
    def all_ok(self) -> bool:
        return self.failed_count == 0


def ingest_tenant(
    tenant: Tenant,
    source: MetricsSource,
    sink: Sink,
    collected_at: datetime,
    *,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
) -> TenantResult:
    """Pull one tenant's metrics and write them to the sink for `collected_at`.

    Both the fetch and each table write retry transient failures with backoff
    (retry_attempts=1 disables retrying — useful in tests). A tenant writes to
    three tables (latency/bottlenecks/resources); if a later table's write
    raises after retries are exhausted, earlier tables for this tenant have
    already landed — the returned result always reflects rows actually
    written, even on failure, so a partial write is never misreported as
    "0 rows written".
    """
    rows_written = 0
    try:
        bundle = retry_with_backoff(
            lambda: source.fetch(tenant, collected_at),
            attempts=retry_attempts,
            label=f"fetch metrics for {tenant.tenant_id}",
        )
        for table, rows in to_rows(bundle).items():
            rows_written += retry_with_backoff(
                lambda t=table, r=rows: sink.replace(t, tenant.tenant_id, collected_at, r),
                attempts=retry_attempts,
                label=f"write {table} for {tenant.tenant_id}",
            )
    except Exception as exc:
        log.exception("tenant %s ingestion failed", tenant.tenant_id)
        return TenantResult(tenant.tenant_id, ok=False, rows_written=rows_written, error=str(exc))
    return TenantResult(tenant.tenant_id, ok=True, rows_written=rows_written)


def run(
    tenants: list[Tenant],
    source: MetricsSource,
    sink: Sink,
    collected_at: datetime,
    *,
    health_state: PipelineHealthState | None = None,
    alerter: Alerter | None = None,
    alert_threshold: int = DEFAULT_ALERT_THRESHOLD,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
) -> RunSummary:
    """Ingest every tenant, isolating per-tenant failures so one cannot abort the run.

    After each tenant, its consecutive-failure streak is updated in
    `health_state` (persisted by the caller across runs). Crossing
    `alert_threshold` consecutive failures fires `alerter.notify(...)` once per
    run in which the tenant is still failing at or above the threshold.
    """
    health_state = health_state if health_state is not None else PipelineHealthState()
    alerter = alerter or LoggingAlerter()

    summary = RunSummary()
    for tenant in tenants:
        result = ingest_tenant(tenant, source, sink, collected_at, retry_attempts=retry_attempts)
        if result.ok:
            log.info("tenant %s: wrote %d rows", tenant.tenant_id, result.rows_written)
        else:
            log.error("tenant %s: failed: %s", tenant.tenant_id, result.error)
        summary.results.append(result)

        health = health_state.record(tenant.tenant_id, result.ok, result.error)
        if not result.ok and health.consecutive_failures >= alert_threshold:
            alerter.notify(tenant.tenant_id, health.consecutive_failures, result.error)

    return summary
