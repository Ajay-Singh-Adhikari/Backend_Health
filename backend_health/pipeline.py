from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from backend_health.bigquery_schema import to_rows
from backend_health.bigquery_sink import Sink
from backend_health.nerdgraph import MetricsSource
from backend_health.tenants import Tenant

log = logging.getLogger("backend_health.pipeline")


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
    tenant: Tenant, source: MetricsSource, sink: Sink, collected_at: datetime
) -> TenantResult:
    """Pull one tenant's metrics and write them to the sink for `collected_at`."""
    bundle = source.fetch(tenant, collected_at)
    rows_written = 0
    for table, rows in to_rows(bundle).items():
        rows_written += sink.replace(table, tenant.tenant_id, collected_at, rows)
    return TenantResult(tenant.tenant_id, ok=True, rows_written=rows_written)


def run(
    tenants: list[Tenant], source: MetricsSource, sink: Sink, collected_at: datetime
) -> RunSummary:
    """Ingest every tenant, isolating per-tenant failures so one cannot abort the run."""
    summary = RunSummary()
    for tenant in tenants:
        try:
            result = ingest_tenant(tenant, source, sink, collected_at)
            log.info("tenant %s: wrote %d rows", tenant.tenant_id, result.rows_written)
        except Exception as exc:
            log.exception("tenant %s ingestion failed", tenant.tenant_id)
            result = TenantResult(tenant.tenant_id, ok=False, error=str(exc))
        summary.results.append(result)
    return summary
