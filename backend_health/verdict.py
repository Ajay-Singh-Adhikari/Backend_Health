from __future__ import annotations

from backend_health.config import load_registry
from backend_health.tenants import Tenant

DEFAULT_CONFIG = "config/tenants.example.yaml"

# Metrics are read from daily_tenant_metrics (the rollup view from #6). Latency
# uses the day's AVG p95 (typical experience, in keeping with "snapshot
# metrics average, not sum"); CPU and memory use the day's MAX (a sustained
# spike is exactly what resource-pressure monitoring should catch, an average
# would mask it); bottlenecks use the raw daily COUNT (a genuine count, not a
# snapshot). Each has a `watch` and `action` threshold: at or above `action` is
# action_needed, at or above `watch` (but below `action`) is watch, else
# healthy. "Higher is worse" for every metric here.
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "latency_p95_ms": {"watch": 500.0, "action": 1500.0},
    "cpu_percent": {"watch": 70.0, "action": 90.0},
    "memory_percent": {"watch": 75.0, "action": 90.0},
    "bottleneck_count": {"watch": 1, "action": 3},
}

METRIC_KEYS = tuple(DEFAULT_THRESHOLDS)
_INT_METRICS = {"bottleneck_count"}
_BOUND_KEYS = {"watch", "action"}

STATUS_ORDER = ("healthy", "watch", "action_needed")


class ThresholdOverrideError(ValueError):
    """Raised when a tenant's `overrides` names a metric or bound that doesn't exist.

    Silently ignoring an unrecognized key would let a typo'd override (e.g.
    `latency_p95` instead of `latency_p95_ms`) apply with zero effect and no
    indication anything was wrong.
    """


def resolve_thresholds(tenant: Tenant) -> dict[str, dict[str, float]]:
    """Merge a tenant's registry `overrides` onto the defaults, per metric.

    A tenant may override just one of `watch`/`action` for a metric; the other
    side falls back to the default (e.g. tenant-a overrides only `watch` for
    latency in config/tenants.example.yaml).
    """
    overrides = tenant.overrides or {}
    unknown_metrics = set(overrides) - set(DEFAULT_THRESHOLDS)
    if unknown_metrics:
        raise ThresholdOverrideError(
            f"tenant '{tenant.tenant_id}' overrides unknown metric(s) {sorted(unknown_metrics)}; "
            f"expected one of {sorted(DEFAULT_THRESHOLDS)}"
        )

    resolved = {}
    for metric, default in DEFAULT_THRESHOLDS.items():
        override = overrides.get(metric, {})
        unknown_bounds = set(override) - _BOUND_KEYS
        if unknown_bounds:
            raise ThresholdOverrideError(
                f"tenant '{tenant.tenant_id}' overrides unknown bound(s) {sorted(unknown_bounds)} "
                f"for metric '{metric}'; expected one of {sorted(_BOUND_KEYS)}"
            )
        resolved[metric] = {**default, **override}
    return resolved


def classify(value: float, watch: float, action: float) -> str:
    """Mirrors the CASE logic in the generated SQL view.

    Kept here as the reference implementation, exercised in tests, since the
    SQL itself can't be executed without a live BigQuery project.
    """
    if value >= action:
        return "action_needed"
    if value >= watch:
        return "watch"
    return "healthy"


def overall_verdict(statuses: list[str]) -> str:
    """The worst of several per-metric statuses."""
    worst = max((STATUS_ORDER.index(s) for s in statuses), default=0)
    return STATUS_ORDER[worst]


def _sql_string_literal(value: str) -> str:
    """Escape a value for interpolation into a single-quoted SQL string literal.

    tenant_id is an internal registry identifier, not arbitrary user input, but
    nothing stops it from containing a `'` — escaping here is what keeps a
    stray apostrophe from producing broken or injectable generated SQL rather
    than a byte-for-byte-matching but invalid query.
    """
    return "'" + value.replace("'", "\\'") + "'"


def _struct_literal(tenant_id: str, thresholds: dict[str, dict[str, float]]) -> str:
    fields = [f"{_sql_string_literal(tenant_id)} AS tenant_id"]
    for metric, bounds in thresholds.items():
        prefix = _column_prefix(metric)
        for bound in ("watch", "action"):
            value = bounds[bound]
            rendered = str(int(value)) if metric in _INT_METRICS else f"{float(value):.1f}"
            fields.append(f"{rendered} AS {prefix}_{bound}")
    return "STRUCT(" + ", ".join(fields) + ")"


def _column_prefix(metric: str) -> str:
    return {
        "latency_p95_ms": "latency",
        "cpu_percent": "cpu",
        "memory_percent": "memory",
        "bottleneck_count": "bottleneck",
    }[metric]


def render_verdict_view_sql(tenants: list[Tenant], dataset: str = "{{dataset}}") -> str:
    """Generate the CREATE OR REPLACE VIEW SQL for tenant_health_verdict.

    Thresholds are baked in as a UNNEST(ARRAY<STRUCT<...>>) literal, resolved
    per tenant from the registry (defaults + overrides). A '__default__'
    sentinel row covers any tenant with metrics but no explicit row here (e.g.
    added to the registry after this view was last regenerated), via
    COALESCE-to-default in the join — so a tenant is never silently dropped
    from the verdict for lack of a threshold row.
    """
    structs = [_struct_literal(t.tenant_id, resolve_thresholds(t)) for t in tenants]
    structs.append(_struct_literal("__default__", DEFAULT_THRESHOLDS))
    thresholds_array = ",\n    ".join(structs)

    coalesce_cols = []
    case_cols = []
    reason_exprs = []
    for metric in METRIC_KEYS:
        prefix = _column_prefix(metric)
        coalesce_cols.append(
            f"    COALESCE(t.{prefix}_watch, d.{prefix}_watch) AS {prefix}_watch"
        )
        coalesce_cols.append(
            f"    COALESCE(t.{prefix}_action, d.{prefix}_action) AS {prefix}_action"
        )
        value_col = _metric_value_column(metric)
        case_cols.append(
            f"    CASE\n"
            f"      WHEN {value_col} >= {prefix}_action THEN 'action_needed'\n"
            f"      WHEN {value_col} >= {prefix}_watch THEN 'watch'\n"
            f"      ELSE 'healthy'\n"
            f"    END AS {prefix}_status"
        )
        reason_exprs.append(
            f"      IF({prefix}_status != 'healthy', CONCAT('{metric} ', {prefix}_status), NULL)"
        )

    status_cols = ", ".join(f"{_column_prefix(m)}_status" for m in METRIC_KEYS)

    header = (
        "-- Generated from backend_health/verdict.py. Do not edit by hand;\n"
        "-- run `python -m backend_health.verdict > sql/views/tenant_health_verdict.sql`\n"
        "-- to regenerate after changing thresholds or the tenant registry.\n"
    )
    # Python 3.11 disallows backslashes inside f-string expression braces, so
    # these joins are precomputed rather than inlined into the f-string below.
    coalesce_block = ",\n".join(coalesce_cols)
    case_block = ",\n".join(case_cols)
    reason_block = ",\n".join(reason_exprs)

    return f"""{header}
CREATE OR REPLACE VIEW `{dataset}.tenant_health_verdict` AS
WITH thresholds AS (
  SELECT * FROM UNNEST([
    {thresholds_array}
  ])
),
resolved AS (
  SELECT
    m.tenant_id,
    m.day,
    m.avg_p95_ms,
    m.max_cpu_percent,
    m.max_memory_percent,
    m.bottleneck_count,
{coalesce_block}
  FROM `{dataset}.daily_tenant_metrics` m
  LEFT JOIN thresholds t ON t.tenant_id = m.tenant_id
  CROSS JOIN (SELECT * EXCEPT (tenant_id) FROM thresholds WHERE tenant_id = '__default__') d
),
classified AS (
  SELECT
    *,
{case_block}
  FROM resolved
)
SELECT
  tenant_id,
  day,
  CASE
    WHEN 'action_needed' IN UNNEST([{status_cols}]) THEN 'action_needed'
    WHEN 'watch' IN UNNEST([{status_cols}]) THEN 'watch'
    ELSE 'healthy'
  END AS verdict,
  ARRAY(
    SELECT reason FROM UNNEST([
{reason_block}
    ]) AS reason
    WHERE reason IS NOT NULL
  ) AS reasons,
  avg_p95_ms,
  max_cpu_percent,
  max_memory_percent,
  bottleneck_count
FROM classified;
"""


def _metric_value_column(metric: str) -> str:
    return {
        "latency_p95_ms": "avg_p95_ms",
        "cpu_percent": "max_cpu_percent",
        "memory_percent": "max_memory_percent",
        "bottleneck_count": "bottleneck_count",
    }[metric]


def render_latest_verdict_view_sql(dataset: str = "{{dataset}}") -> str:
    """Generate the view the status card (#9) should actually read.

    One row per tenant: its most recent verdict, whatever day that is. A
    Looker Studio date-range filter is global, not per-tenant — if one
    tenant's pipeline lags or fails for a day (#8), a "last N days" filter
    would show that tenant blank rather than its last known verdict, which is
    worse for an on-call engineer than a status marked stale. This view has no
    tenant-specific content, so unlike tenant_health_verdict it needs no
    per-tenant data to render — it's still generated for consistency with the
    rest of this module's SQL and to keep the dataset placeholder convention
    uniform across every generated view.
    """
    header = (
        "-- Generated from backend_health/verdict.py. Do not edit by hand;\n"
        "-- run `python -m backend_health.verdict --latest > "
        "sql/views/latest_tenant_verdict.sql` to regenerate.\n"
    )
    return f"""{header}
CREATE OR REPLACE VIEW `{dataset}.latest_tenant_verdict` AS
SELECT * EXCEPT (row_num)
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY day DESC) AS row_num
  FROM `{dataset}.tenant_health_verdict`
)
WHERE row_num = 1;
"""


if __name__ == "__main__":
    import sys

    if "--latest" in sys.argv:
        print(render_latest_verdict_view_sql(), end="")
    else:
        tenants = load_registry(DEFAULT_CONFIG)
        print(render_verdict_view_sql(tenants), end="")
