from __future__ import annotations

from dataclasses import dataclass

from backend_health.metrics import MetricsBundle

DATASET_PLACEHOLDER = "{{dataset}}"


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    required: bool = False


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    partition_by: str
    cluster_by: str


# Every table carries tenant_id, is partitioned by ingestion day, and clustered
# by tenant_id so a per-tenant query prunes to that tenant's slice cheaply and
# never scans another tenant's rows by accident. Metric columns are snapshots
# (percentiles, CPU/mem %), so downstream aggregation is AVG, never SUM.
TABLES: tuple[Table, ...] = (
    Table(
        name="latency_samples",
        columns=(
            Column("tenant_id", "STRING", required=True),
            Column("collected_at", "TIMESTAMP", required=True),
            Column("transaction_name", "STRING", required=True),
            Column("p50_ms", "FLOAT64"),
            Column("p95_ms", "FLOAT64"),
            Column("p99_ms", "FLOAT64"),
            Column("throughput_rpm", "FLOAT64"),
        ),
        partition_by="DATE(collected_at)",
        cluster_by="tenant_id",
    ),
    Table(
        name="bottlenecks",
        columns=(
            Column("tenant_id", "STRING", required=True),
            Column("collected_at", "TIMESTAMP", required=True),
            Column("transaction_name", "STRING", required=True),
            Column("duration_ms", "FLOAT64"),
            Column("kind", "STRING", required=True),
        ),
        partition_by="DATE(collected_at)",
        cluster_by="tenant_id",
    ),
    Table(
        name="resource_samples",
        columns=(
            Column("tenant_id", "STRING", required=True),
            Column("collected_at", "TIMESTAMP", required=True),
            Column("host", "STRING", required=True),
            Column("cpu_percent", "FLOAT64"),
            Column("memory_percent", "FLOAT64"),
        ),
        partition_by="DATE(collected_at)",
        cluster_by="tenant_id",
    ),
)

TABLES_BY_NAME = {table.name: table for table in TABLES}


def _render_table(table: Table, dataset: str) -> str:
    lines = [f"CREATE TABLE IF NOT EXISTS `{dataset}.{table.name}` ("]
    col_lines = []
    for col in table.columns:
        suffix = " NOT NULL" if col.required else ""
        col_lines.append(f"  {col.name} {col.type}{suffix}")
    lines.append(",\n".join(col_lines))
    lines.append(")")
    lines.append(f"PARTITION BY {table.partition_by}")
    lines.append(f"CLUSTER BY {table.cluster_by};")
    return "\n".join(lines)


def render_schema_sql(dataset: str = DATASET_PLACEHOLDER) -> str:
    """Render the CREATE TABLE DDL for all tables. Source of truth for schema.sql."""
    header = (
        "-- Generated from backend_health/bigquery_schema.py. Do not edit by hand;\n"
        "-- run `python -m backend_health.bigquery_schema` to regenerate.\n"
    )
    body = "\n\n".join(_render_table(table, dataset) for table in TABLES)
    return f"{header}\n{body}\n"


def to_rows(bundle: MetricsBundle) -> dict[str, list[dict]]:
    """Map a MetricsBundle to insertable rows keyed by table name."""
    collected_at = bundle.collected_at.isoformat()
    return {
        "latency_samples": [
            {
                "tenant_id": s.tenant_id,
                "collected_at": collected_at,
                "transaction_name": s.transaction,
                "p50_ms": s.p50_ms,
                "p95_ms": s.p95_ms,
                "p99_ms": s.p99_ms,
                "throughput_rpm": s.throughput_rpm,
            }
            for s in bundle.latency
        ],
        "bottlenecks": [
            {
                "tenant_id": b.tenant_id,
                "collected_at": collected_at,
                "transaction_name": b.transaction,
                "duration_ms": b.duration_ms,
                "kind": b.kind,
            }
            for b in bundle.bottlenecks
        ],
        "resource_samples": [
            {
                "tenant_id": r.tenant_id,
                "collected_at": collected_at,
                "host": r.host,
                "cpu_percent": r.cpu_percent,
                "memory_percent": r.memory_percent,
            }
            for r in bundle.resources
        ],
    }


if __name__ == "__main__":
    print(render_schema_sql(), end="")
