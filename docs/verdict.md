# Health-verdict logic

How raw metrics become the single Healthy / Watch / Action Needed status the
dashboard shows (issue #11), so the Looker Studio card (#9) is a thin read of
a view, not its own calculated-field logic.

## Metrics and thresholds

Four metrics feed the verdict, each read from `daily_tenant_metrics` (#6) and
each with a `watch` and `action` threshold ("higher is worse", boundary is
inclusive — a value **at** a threshold already counts):

| Metric | Column read | Default watch | Default action | Why this aggregate |
|---|---|---|---|---|
| Latency (p95) | `avg_p95_ms` | 500ms | 1500ms | The day's *typical* p95 — a single-minute blip average out, matching "snapshot metrics aggregate as AVG". |
| CPU | `max_cpu_percent` | 70% | 90% | The day's *peak* — resource pressure is about spikes; an average would mask one. |
| Memory | `max_memory_percent` | 75% | 90% | Same reasoning as CPU. |
| Bottlenecks | `bottleneck_count` | 1/day | 3/day | A genuine count of slow-transaction events, not a snapshot — compared directly. |

The overall verdict for a tenant-day is the **worst** of the four per-metric
statuses. `reasons` lists which metric(s) triggered it (e.g. `["cpu_percent
watch"]`), so the dashboard can show *why*, not just *what*.

## Tenant-overridable thresholds

A tenant's `overrides` in the registry (`config/tenants.example.yaml`, from
#3) can replace either bound for any metric — `tenant-a` raises its latency
`watch` threshold to 800ms because it's a high-traffic site where 500ms is
its normal, not a warning sign. `backend_health/verdict.resolve_thresholds`
merges override onto default per metric, so overriding one bound (e.g. just
`watch`) leaves the other (e.g. `action`) at its default.

## Generated view

`backend_health/verdict.py` is the single source of truth — the same
generate-and-drift-guard pattern as the BigQuery schema (#6):

```
python -m backend_health.verdict > sql/views/tenant_health_verdict.sql
```

A test fails CI if the checked-in file drifts from the module. Thresholds are
baked into the view as a `UNNEST(ARRAY<STRUCT<...>>)` literal, one struct per
tenant plus a `__default__` sentinel row. The view resolves each tenant's
thresholds via `COALESCE(t.<bound>, d.<bound>)` — so a tenant with metrics but
no explicit threshold row (e.g. added to the registry after the view was last
regenerated) still gets a verdict from the defaults, rather than silently
being dropped.

The `classify()` and `overall_verdict()` functions in `verdict.py` mirror the
SQL `CASE` logic exactly and are exercised in tests — the reference
implementation for semantics that can't be tested against a live BigQuery
project here.

## Regenerating after a threshold or registry change

Whenever `DEFAULT_THRESHOLDS` changes, a tenant's `overrides` change, or a
tenant is added/removed from the registry, regenerate the view and commit
both files together — the drift-guard test will otherwise fail CI.
