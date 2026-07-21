# Pipeline reliability

How one tenant's transient failure or repeated outage is handled without
breaking the rest of the run, or going unnoticed. Addresses issue #8.

## Retries with backoff

Each tenant's NerdGraph fetch and each BigQuery table write retries
transient failures with exponential backoff (`backend_health/retry.py`):
attempt, wait, attempt, wait, final attempt. Default 3 attempts, 1s base delay
(1s, 2s). The last error is re-raised once attempts are exhausted, so a
permanent failure (bad credentials, malformed NRQL) still surfaces clearly
rather than being silently swallowed — it isn't distinguished from a
transient one, it's just given a few chances to resolve itself first.

## Per-tenant isolation

`pipeline.run` catches exceptions per tenant (`ingest_tenant`), so one
tenant's outage — even after retries are exhausted — does not stop other
tenants from ingesting in the same run. A partial write (e.g. the latency
table lands but the resource table's write then fails) is still reflected
accurately in that tenant's row count, never silently reported as zero.

## Pipeline health tracking

`backend_health/health_state.py` persists each tenant's **consecutive
failure streak** to a small JSON file (`out/pipeline_health.json` by
default) across runs — each scheduled run is a fresh process, so this file
is what lets the pipeline know "this tenant has now failed 3 runs in a row"
rather than only ever seeing one run in isolation.

In the scheduled GitHub Actions workflow, the state file survives across
runs via `actions/cache`. Cache entries are immutable per key, so the
workflow saves under a run-id-unique key and restores via a shared prefix
(`restore-keys`), which resolves to the most recently saved match — a fixed,
reused key would silently fail to update after the first run. This step
saves `if: always()`, specifically because a *failing* run is exactly when
the streak must still be persisted, or the threshold could never be reached.

Check it any time, without querying BigQuery:

```
python -m backend_health pipeline-health --state-file out/pipeline_health.json
```

A successful run resets a tenant's streak to zero.

## Alerting

When a tenant's streak reaches `--alert-threshold` (default 3) consecutive
failed runs, `pipeline.run` fires an alert once per run in which the tenant
remains at or above that threshold (`backend_health/alerts.py`):

- **`LoggingAlerter`** (default): logs a clearly-marked `ALERT:` line. Always
  active, requires no configuration — a failing tenant is visible in the
  run's own logs even with nothing else set up.
- **`WebhookAlerter`**: posts a Slack-compatible JSON payload to a webhook URL
  (`--alert-webhook`, or the `BACKEND_HEALTH_ALERT_WEBHOOK` env var / Actions
  secret). Best-effort — a webhook failure is logged, never raised, so a
  broken alert channel can never fail the ingestion run itself.

## What this pipeline's own health looks like

Two different things are both called "health" here and are worth
distinguishing:

- **Client backend health** — the New Relic metrics this tool ingests (#11
  turns this into a verdict).
- **This pipeline's health** — whether ingestion itself is working. That's
  what `pipeline-health` and the alerting above cover.
