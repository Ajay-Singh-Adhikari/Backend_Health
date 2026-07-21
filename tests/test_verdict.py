from pathlib import Path

from backend_health.config import load_registry
from backend_health.tenants import Tenant
import pytest

from backend_health.verdict import (
    DEFAULT_THRESHOLDS,
    ThresholdOverrideError,
    classify,
    overall_verdict,
    render_verdict_view_sql,
    resolve_thresholds,
)


def _tenant(tenant_id: str, overrides: dict | None = None) -> Tenant:
    return Tenant(
        tenant_id=tenant_id,
        status="active",
        newrelic_account_id="1",
        credential_ref=tenant_id,
        overrides=overrides or {},
    )


def test_classify_boundaries():
    assert classify(499.9, watch=500, action=1500) == "healthy"
    assert classify(500.0, watch=500, action=1500) == "watch"  # >= watch, boundary inclusive
    assert classify(1500.0, watch=500, action=1500) == "action_needed"
    assert classify(9999, watch=500, action=1500) == "action_needed"


def test_overall_verdict_is_the_worst_status():
    assert overall_verdict(["healthy", "healthy"]) == "healthy"
    assert overall_verdict(["healthy", "watch"]) == "watch"
    assert overall_verdict(["watch", "action_needed", "healthy"]) == "action_needed"
    assert overall_verdict([]) == "healthy"


def test_resolve_thresholds_uses_defaults_with_no_overrides():
    resolved = resolve_thresholds(_tenant("tenant-x"))
    assert resolved == DEFAULT_THRESHOLDS


def test_resolve_thresholds_partial_override_keeps_other_bound():
    tenant = _tenant("tenant-a", overrides={"latency_p95_ms": {"watch": 800}})
    resolved = resolve_thresholds(tenant)
    assert resolved["latency_p95_ms"]["watch"] == 800
    assert resolved["latency_p95_ms"]["action"] == DEFAULT_THRESHOLDS["latency_p95_ms"]["action"]
    # other metrics untouched
    assert resolved["cpu_percent"] == DEFAULT_THRESHOLDS["cpu_percent"]


def test_resolve_thresholds_rejects_unknown_metric_typo():
    tenant = _tenant("tenant-a", overrides={"latency_p95": {"watch": 800}})  # missing _ms
    with pytest.raises(ThresholdOverrideError, match="unknown metric"):
        resolve_thresholds(tenant)


def test_resolve_thresholds_rejects_unknown_bound_typo():
    tenant = _tenant("tenant-a", overrides={"latency_p95_ms": {"maximum": 800}})  # not watch/action
    with pytest.raises(ThresholdOverrideError, match="unknown bound"):
        resolve_thresholds(tenant)


def test_render_includes_every_tenant_and_default_sentinel():
    tenants = [_tenant("tenant-a"), _tenant("tenant-b")]
    sql = render_verdict_view_sql(tenants, dataset="my_ds")
    assert "'tenant-a' AS tenant_id" in sql
    assert "'tenant-b' AS tenant_id" in sql
    assert "'__default__' AS tenant_id" in sql
    assert "`my_ds.tenant_health_verdict`" in sql
    assert "`my_ds.daily_tenant_metrics`" in sql


def test_render_applies_tenant_override():
    tenant = _tenant("tenant-a", overrides={"latency_p95_ms": {"watch": 800}})
    sql = render_verdict_view_sql([tenant], dataset="ds")
    assert "800.0 AS latency_watch" in sql


def test_render_uses_coalesce_for_default_fallback():
    sql = render_verdict_view_sql([_tenant("tenant-a")], dataset="ds")
    assert "COALESCE(t.latency_watch, d.latency_watch)" in sql
    assert "CROSS JOIN" in sql


def test_render_escapes_single_quote_in_tenant_id():
    tenant = _tenant("o'brien-tenant")
    sql = render_verdict_view_sql([tenant], dataset="ds")
    assert "'o\\'brien-tenant' AS tenant_id" in sql
    # unescaped would break out of the string literal — must not appear
    assert "'o'brien-tenant'" not in sql


def test_render_bottleneck_thresholds_are_integers_not_floats():
    sql = render_verdict_view_sql([_tenant("tenant-a")], dataset="ds")
    assert "1 AS bottleneck_watch" in sql
    assert "3 AS bottleneck_action" in sql
    assert "1.0 AS bottleneck_watch" not in sql


def test_verdict_sql_file_is_in_sync_with_module():
    tenants = load_registry("config/tenants.example.yaml")
    on_disk = Path("sql/views/tenant_health_verdict.sql").read_text()
    assert on_disk == render_verdict_view_sql(tenants), (
        "sql/views/tenant_health_verdict.sql is stale; regenerate with "
        "`python -m backend_health.verdict > sql/views/tenant_health_verdict.sql`"
    )
