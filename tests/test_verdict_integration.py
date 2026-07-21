"""End-to-end check: demo pipeline data -> daily rollup -> verdict.

BigQuery itself isn't available in this environment, so `daily_tenant_metrics`
and `tenant_health_verdict` can't be executed directly here. This test
reproduces their logic in Python against real output of the demo pipeline
(DemoMetricsSource + the real tenant registry), so the numbers in
docs/dashboard.md's worked example are grounded in actual code output, not a
hypothetical.
"""

from datetime import datetime

from backend_health.config import active_tenants, load_registry
from backend_health.nerdgraph import DemoMetricsSource
from backend_health.verdict import classify, overall_verdict, resolve_thresholds

# Chosen because it produces all three verdict states across the three demo
# tenants (see docs/dashboard.md), making it a good worked example.
WORKED_EXAMPLE_HOUR = datetime(2026, 7, 21, 18, 0, 0)

EXPECTED_VERDICTS = {
    "tenant-a": "healthy",
    "tenant-b": "action_needed",
    "tenant-c": "watch",
}


def _rollup_metrics(p95s, cpus, mems, bottleneck_count):
    """Mirrors sql/views/daily_tenant_metrics.sql over flat lists of raw
    samples — the single aggregation formula shared by both worked examples
    below, so a future change to it can't drift between them."""
    return (
        sum(p95s) / len(p95s),
        max(cpus),
        max(mems),
        bottleneck_count,
    )


def _daily_rollup(bundle):
    """Mirrors daily_tenant_metrics.sql for a single hour's bundle."""
    return _rollup_metrics(
        [s.p95_ms for s in bundle.latency],
        [r.cpu_percent for r in bundle.resources],
        [r.memory_percent for r in bundle.resources],
        len(bundle.bottlenecks),
    )


def _verdict_for(tenant, avg_p95_ms, max_cpu_percent, max_memory_percent, bottleneck_count):
    """Mirrors sql/views/tenant_health_verdict.sql's CASE logic."""
    thresholds = resolve_thresholds(tenant)
    statuses = {
        "latency_p95_ms": classify(avg_p95_ms, **thresholds["latency_p95_ms"]),
        "cpu_percent": classify(max_cpu_percent, **thresholds["cpu_percent"]),
        "memory_percent": classify(max_memory_percent, **thresholds["memory_percent"]),
        "bottleneck_count": classify(bottleneck_count, **thresholds["bottleneck_count"]),
    }
    verdict = overall_verdict(list(statuses.values()))
    reasons = [f"{metric} {status}" for metric, status in statuses.items() if status != "healthy"]
    return verdict, reasons


def test_worked_example_matches_demo_pipeline_output():
    tenants = active_tenants(load_registry("config/tenants.example.yaml"))
    source = DemoMetricsSource()

    results = {}
    for tenant in tenants:
        bundle = source.fetch(tenant, WORKED_EXAMPLE_HOUR)
        rollup = _daily_rollup(bundle)
        verdict, reasons = _verdict_for(tenant, *rollup)
        results[tenant.tenant_id] = (verdict, reasons)

    for tenant_id, expected_verdict in EXPECTED_VERDICTS.items():
        actual_verdict, _ = results[tenant_id]
        assert actual_verdict == expected_verdict, (
            f"{tenant_id}: expected {expected_verdict}, got {actual_verdict} — "
            "if this changed intentionally (threshold/demo-data change), update "
            "both this test and the worked example in docs/dashboard.md"
        )

    # tenant-b's action_needed must be explained by a reason, not just asserted
    _, tenant_b_reasons = results["tenant-b"]
    assert any("cpu_percent action_needed" in r for r in tenant_b_reasons)


# Three consecutive days for tenant-b, each rolled up from 4 hourly samples
# (0/6/12/18 UTC) — the same shape daily_tenant_metrics.sql produces from a
# full day of hourly pulls. Used as the evidence-charts worked example in
# docs/dashboard.md: CPU trends up across the window and crosses into
# action_needed territory, giving the "engineer sees pressure building before
# it's critical" story those charts are meant to support.
TREND_TENANT_ID = "tenant-b"
TREND_DAYS = (19, 20, 21)
TREND_HOURS = (0, 6, 12, 18)

EXPECTED_TREND = {
    19: {"avg_p95_ms": 354.7, "max_cpu_percent": 82.6, "max_memory_percent": 72.6, "bottleneck_count": 2},
    20: {"avg_p95_ms": 472.3, "max_cpu_percent": 91.2, "max_memory_percent": 86.1, "bottleneck_count": 7},
    21: {"avg_p95_ms": 388.3, "max_cpu_percent": 94.1, "max_memory_percent": 82.2, "bottleneck_count": 4},
}


def _daily_rollup_multi_hour(tenant, source, day):
    """Same _rollup_metrics core as _daily_rollup, but fed from several hours
    in one day — mirrors daily_tenant_metrics.sql aggregating a full day of
    hourly pulls, rather than test_worked_example's single-hour bundle."""
    p95s, cpus, mems, bottleneck_count = [], [], [], 0
    for hour in TREND_HOURS:
        bundle = source.fetch(tenant, datetime(2026, 7, day, hour, 0, 0))
        p95s.extend(s.p95_ms for s in bundle.latency)
        cpus.extend(r.cpu_percent for r in bundle.resources)
        mems.extend(r.memory_percent for r in bundle.resources)
        bottleneck_count += len(bundle.bottlenecks)
    avg_p95_ms, max_cpu_percent, max_memory_percent, bottleneck_count = _rollup_metrics(
        p95s, cpus, mems, bottleneck_count
    )
    return {
        "avg_p95_ms": round(avg_p95_ms, 1),
        "max_cpu_percent": round(max_cpu_percent, 1),
        "max_memory_percent": round(max_memory_percent, 1),
        "bottleneck_count": bottleneck_count,
    }


def test_trend_worked_example_matches_demo_pipeline_output():
    tenants = active_tenants(load_registry("config/tenants.example.yaml"))
    tenant = next(t for t in tenants if t.tenant_id == TREND_TENANT_ID)
    source = DemoMetricsSource()

    for day in TREND_DAYS:
        rollup = _daily_rollup_multi_hour(tenant, source, day)
        assert rollup == EXPECTED_TREND[day], (
            f"2026-07-{day}: expected {EXPECTED_TREND[day]}, got {rollup} — "
            "if this changed intentionally, update both this test and the "
            "evidence-charts worked example in docs/dashboard.md"
        )


def test_worked_example_is_deterministic_across_reruns():
    tenants = active_tenants(load_registry("config/tenants.example.yaml"))
    source = DemoMetricsSource()

    def run_once():
        return {
            t.tenant_id: _verdict_for(t, *_daily_rollup(source.fetch(t, WORKED_EXAMPLE_HOUR)))[0]
            for t in tenants
        }

    assert run_once() == run_once()
