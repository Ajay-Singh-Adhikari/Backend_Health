# Looker Studio dashboard: setup guide

Looker Studio is a manual, click-through UI — nothing here can be created by
code, so this is a precise setup guide rather than a shipped dashboard file.
Addresses issue #9 (verdict-first status card). Evidence charts (#10) are a
separate section further down, added once #10 lands.

Follows the dashboard philosophy in the README: verdict first, evidence
second; nothing included just because the data exists; an engineer should be
able to tell status without running a command.

## Data sources to connect

Add both as **BigQuery** data sources in Looker Studio, pointed at the
project/dataset the pipeline writes to (#7):

1. `tenant_health_verdict` (#11) — the status card reads this.
2. `daily_tenant_metrics` (#6) — the evidence charts (#10) read this.

## Tenant selector

Add a **Drop-down list** control bound to the `tenant_id` field (from either
data source — they share the field name). This is what lets one report serve
every tenant instead of a copy-pasted report per client. Place it at the top,
above the status card, so it scopes everything below it.

## Status card

1. Add a **Scorecard** (or Table, if you want the `reasons` visible at a
   glance rather than on click) bound to `tenant_health_verdict`.
2. Metric: `verdict`. **Critical:** `verdict` is a `STRING` — it must be
   configured as a **Dimension**, not a Metric. Looker Studio silently wraps
   string fields used as Metrics in a `COUNT` aggregation, which would show a
   meaningless number instead of the status text. This is the exact footgun
   called out in the README's practical notes from the DB Health build.
3. Filter to the latest `day` per tenant (e.g. a date-range control defaulted
   to "Last 1 day", or a calculated field selecting `MAX(day)`). Watch for
   Looker Studio's "Auto: exclude today" default date range — it silently
   drops today's data and would make the card look one day stale.
4. Add conditional formatting on the `verdict` dimension's value:
   - `healthy` → green
   - `watch` → yellow/amber
   - `action_needed` → red
5. Add a second small table or tooltip showing the `reasons` array (unnest it
   or display as text) — this is *why* the verdict is what it is, satisfying
   "verdict first, evidence second" without needing a separate chart yet.

## Worked example (real, not hypothetical)

Looker Studio can't be exercised without a live GCP project, so this example
was produced by actually running the demo pipeline
(`DemoMetricsSource` + the real `config/tenants.example.yaml` registry)
through the same rollup and verdict logic the BigQuery views implement, for
2026-07-21T18:00 UTC. It's asserted byte-for-byte in
`tests/test_verdict_integration.py`, so it stays true as the code evolves —
if it ever needs to change, that test fails first and both are updated
together.

| Tenant | avg p95 | max CPU | max memory | bottlenecks | Verdict | Reasons |
|---|---|---|---|---|---|---|
| `tenant-a` | 360.4ms | 66.3% | 66.8% | 0 | 🟢 Healthy | — |
| `tenant-b` | 317.3ms | 94.1% | 70.3% | 1 | 🔴 Action Needed | cpu_percent action_needed, bottleneck_count watch |
| `tenant-c` | 385.7ms | 87.7% | 82.9% | 0 | 🟡 Watch | cpu_percent watch, memory_percent watch |

With the tenant selector on `tenant-b`, the card should show a red
**Action Needed** status — driven by CPU, not latency, which is exactly the
kind of detail "verdict first, evidence second" is meant to surface via the
reasons, not a wall of raw charts.

## Checklist before sharing with engineers

- [ ] Tenant selector switches the card correctly for all three demo tenants
- [ ] `verdict` configured as a Dimension (not silently `COUNT`-wrapped)
- [ ] Date range does not silently exclude today
- [ ] Conditional formatting colors match Healthy/Watch/Action Needed
- [ ] `reasons` visible without leaving the status card view
