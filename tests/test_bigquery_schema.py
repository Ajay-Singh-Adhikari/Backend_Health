from datetime import datetime
from pathlib import Path

from backend_health.bigquery_schema import (
    TABLES,
    render_schema_sql,
    to_rows,
)
from backend_health.metrics import (
    Bottleneck,
    LatencySample,
    MetricsBundle,
    ResourceSample,
)

COLLECTED_AT = datetime(2026, 7, 21, 12, 0, 0)


def test_every_table_partitioned_and_clustered_by_tenant():
    for table in TABLES:
        assert table.partition_by == "DATE(collected_at)"
        assert table.cluster_by == "tenant_id"
        col_names = [c.name for c in table.columns]
        assert "tenant_id" in col_names
        assert "collected_at" in col_names


def test_rendered_ddl_has_partition_and_cluster_clauses():
    sql = render_schema_sql("my_dataset")
    assert sql.count("CREATE TABLE IF NOT EXISTS") == len(TABLES)
    assert sql.count("PARTITION BY DATE(collected_at)") == len(TABLES)
    assert sql.count("CLUSTER BY tenant_id") == len(TABLES)
    assert "`my_dataset.latency_samples`" in sql


def test_schema_sql_file_is_in_sync_with_module():
    on_disk = Path("sql/schema.sql").read_text()
    assert on_disk == render_schema_sql(), (
        "sql/schema.sql is stale; regenerate with "
        "`python -m backend_health.bigquery_schema > sql/schema.sql`"
    )


def test_to_rows_maps_bundle():
    bundle = MetricsBundle(
        tenant_id="tenant-a",
        collected_at=COLLECTED_AT,
        latency=[
            LatencySample("tenant-a", COLLECTED_AT, "GET /x", 10.0, 20.0, 30.0, 100.0)
        ],
        bottlenecks=[
            Bottleneck("tenant-a", COLLECTED_AT, "POST /y", 2500.0, "slow_transaction")
        ],
        resources=[ResourceSample("tenant-a", COLLECTED_AT, "web-1", 55.0, 60.0)],
    )
    rows = to_rows(bundle)

    assert set(rows) == {"latency_samples", "bottlenecks", "resource_samples"}
    lat = rows["latency_samples"][0]
    assert lat["transaction_name"] == "GET /x"
    assert lat["collected_at"] == COLLECTED_AT.isoformat()
    assert lat["p95_ms"] == 20.0
    assert rows["bottlenecks"][0]["kind"] == "slow_transaction"
    assert rows["resource_samples"][0]["host"] == "web-1"


def test_to_rows_uses_sample_timestamp_not_bundle():
    later = datetime(2026, 7, 21, 13, 30, 0)
    bundle = MetricsBundle(
        tenant_id="tenant-a",
        collected_at=COLLECTED_AT,
        latency=[LatencySample("tenant-a", later, "GET /x", 1.0, 2.0, 3.0, 4.0)],
        bottlenecks=[],
        resources=[],
    )
    rows = to_rows(bundle)
    assert rows["latency_samples"][0]["collected_at"] == later.isoformat()


def test_to_rows_empty_bundle():
    bundle = MetricsBundle("tenant-a", COLLECTED_AT, [], [], [])
    rows = to_rows(bundle)
    assert rows == {"latency_samples": [], "bottlenecks": [], "resource_samples": []}


def test_daily_view_uses_avg_not_sum():
    view = Path("sql/views/daily_tenant_metrics.sql").read_text()
    assert "AVG(" in view
    assert "SUM(" not in view
    assert "FULL OUTER JOIN" in view
