# Backend Health

Backend Health is the fourth monitoring pillar in the performance stack, covering **API latency, bottlenecks, and resource pressure (CPU/memory)** at the backend/server level — the one thing a WordPress plugin or browser-based test fundamentally cannot see.

It complements the three pillars that already exist:

| Concern | Tool | Repo |
|---|---|---|
| Frontend performance | GTmetrix + Lighthouse | `coloredcow/performance-dashboard` |
| DB health | ProPerf plugin (custom) | `coloredcow/performance-adapter-wp` |
| Backend health | New Relic (APM) | this repo |

## Why a separate repo

Backend Health data doesn't fit either existing repo:

- **`performance-adapter-wp`** is WordPress-specific by design — it reads WordPress's own DB (options table, WooCommerce tables, plugins, hooks). New Relic APM data instruments the PHP runtime/server itself and has nothing WordPress-specific about it.
- **`performance-dashboard`** is, despite being described elsewhere as a "platform-agnostic fundamentals layer," currently a fully hardcoded single-platform pipeline (GitHub Actions → GTmetrix + Lighthouse → BigQuery → Looker Studio) with no CI abstraction, no storage sink abstraction, and no metrics-provider plugin interface. Retrofitting it into a real platform-agnostic layer is separate architecture work, not something to bundle in here.

This follows the same precedent DB Health already set: get its own repo rather than being merged into `performance-dashboard`.

## Architecture

Same shape as ProPerf: **pull metrics on a schedule → push to BigQuery → visualize in Looker Studio.**

A scheduled job pulls summary metrics from New Relic's **NerdGraph** API (GraphQL-based; the older REST API v2 is deprecated and won't be targeted) and writes them into BigQuery. Whether that job is a standalone script, a Cloud Function, or another lightweight service is an open implementation decision — it will not be wedged into either of the two existing repos above.

## Metrics tracked

- **API latency** — response time per endpoint/transaction
- **Bottlenecks** — slow transaction traces (New Relic APM auto-detects slow queries and N+1 patterns out of the box)
- **Resource pressure** — CPU/memory at the host level

## Related but out of scope: Code Health

Came up in the same discussion, not part of Backend Health:

- **Expensive queries** — fits ProPerf instead (MySQL's `performance_schema.events_statements_summary_by_digest`, same pattern ProPerf already uses for `information_schema` table-size queries).
- **Slow components** (which plugin/hook/template) — likely covered for free by New Relic APM transaction traces if adopted, or by the Query Monitor plugin for single-page profiling.
- **Poor loops** (N+1 patterns in source) — static analysis concern, belongs in a CI linter (PHPStan/Psalm), not in any dashboard.

## Open questions

1. **Is New Relic already active anywhere** (client sites) with API/license access available?
   - If yes → this is a "wire up an existing tool's API" task.
   - If no → bigger initiative: install the New Relic PHP agent, sort budget/licensing, decide what to track, then build the pull-to-BigQuery pipeline.
2. Repo structure/implementation approach for the scheduled pull job — not yet decided.
3. Dashboard design in Looker Studio should follow the same conventions as the DB Health page (see below) rather than dumping raw charts.

## Dashboard philosophy

Carried over from the ProPerf "Database Health" Looker Studio page:

- **Verdict first, evidence second.** A single traffic-light status card (Healthy / Watch / Action Needed) at the top, backed by trend charts that explain *why* — not a wall of disconnected charts.
- **Don't include a chart just because the data exists.** Only include what changes what an engineer does next.
- **Goal:** an engineer should be able to tell backend health status without running any commands or querying anything manually.

Practical Looker Studio notes carried over from that build:
- Calculated-field renames control axis/legend labels — there's no separate axis-title text box.
- Watch for "Auto: exclude today" date ranges causing off-by-one staleness.
- Snapshot metrics (not additive counts) should aggregate as AVG, not SUM.
- Text-valued calculated fields must be used as Dimensions, not Metrics, or they get silently wrapped in a Count aggregation.
