# BigQuery schema

How every tenant's metrics land in one dataset without cross-tenant leakage.
Addresses issue #6.

## Tables

Three raw tables, defined once in `backend_health/bigquery_schema.py` (the
single source of truth) and rendered to `sql/schema.sql`:

| Table | Grain | Key columns |
|---|---|---|
| `latency_samples` | one transaction per pull | `p50_ms`, `p95_ms`, `p99_ms`, `throughput_rpm` |
| `bottlenecks` | one slow-transaction event per pull | `duration_ms`, `kind` |
| `resource_samples` | one host per pull | `cpu_percent`, `memory_percent` |

Every table:

- carries `tenant_id` (`NOT NULL`);
- is **partitioned by `DATE(collected_at)`** — queries prune to the day(s) they
  need;
- is **clustered by `tenant_id`** — a per-tenant query prunes to that tenant's
  blocks and never scans another tenant's rows by accident.

That partition + cluster pair is the isolation guarantee: one shared dataset,
many tenants, no separate-dataset-per-client sprawl.

## Aggregation: AVG, never SUM

Metric columns are **snapshots** (percentiles, CPU/memory %), not additive
counts. Summing them is meaningless. The rule is enforced in the schema layer,
not left to Looker Studio calculated fields:

- `sql/views/daily_tenant_metrics.sql` rolls the raw tables up per tenant per
  day using `AVG`/`MAX` for snapshots and `COUNT` for bottleneck events.
- The verdict view (#11) and dashboard charts (#10) read this rollup, so they
  inherit the correct aggregation.

## Regenerating the DDL

`sql/schema.sql` is generated — never hand-edit it:

```
python -m backend_health.bigquery_schema > sql/schema.sql
```

A test (`test_schema_sql_file_is_in_sync_with_module`) fails CI if the file
drifts from the module. `{{dataset}}` is substituted with the target dataset at
deploy time.
