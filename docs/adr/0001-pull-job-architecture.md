# ADR 0001 — Pull-job architecture

- Status: accepted
- Relates to: README open question #2, issue #2

## Context

Backend Health pulls summary metrics from New Relic's NerdGraph API and writes
them to BigQuery on a schedule (see README "Architecture"). Before any ingestion
code is written we need to fix the language, how the job is scheduled, and the
repo layout, so that issues #3–#8 build into a stable base.

The job is small and stateless: on each run it reads a tenant registry, and for
every active tenant pulls metrics and writes rows to BigQuery. It holds no
long-lived state of its own — BigQuery is the store.

## Decision

### Language: Python 3.11+

Mature client libraries for both ends (`requests` for NerdGraph's GraphQL
endpoint, `google-cloud-bigquery` for the sink), trivial to unit-test against
recorded/mocked responses, and the common choice for this style of scheduled
ETL.

### Run form: standalone CLI, scheduled by GitHub Actions cron

The code is deployment-target-agnostic — it only needs **run-once** semantics
(`python -m backend_health run`). Scheduling lives outside the code.

The chosen scheduler is a **scheduled GitHub Actions workflow**
(`.github/workflows/backend-health-pull.yml`, `on: schedule`). Rationale:

- No extra infrastructure to stand up or pay for.
- Consistent with the frontend pillar (`performance-dashboard`), which is
  already a GitHub Actions → BigQuery pipeline.
- Secrets are injected as Actions secrets, keyed per tenant (see #4), never
  committed.

Because the run form is just "invoke the CLI once", moving to Cloud
Scheduler + Cloud Run later is a deployment change only — no code change.

### Config: YAML tenant registry

The tenant registry (`config/tenants.example.yaml`, defined in #3) is YAML so a
non-engineer can eventually edit it. Credentials are **not** in it — they are
resolved at runtime from a secret backend (#4).

### Dependency & build: `pyproject.toml` (PEP 621, setuptools)

Core dependencies stay light (`PyYAML`, `requests`) so the demo/mock path runs
without GCP libraries. `google-cloud-bigquery` is an optional extra
(`pip install -e .[bigquery]`) pulled in only for real BigQuery writes.

### Testing: pytest, run in CI

`.github/workflows/ci.yml` runs `pytest` and `ruff` on every push/PR. No test
may depend on a live New Relic or BigQuery — external calls are mocked (#5).

## Repo layout

```
backend_health/          # the package
  __main__.py            # enables `python -m backend_health`
  cli.py                 # argparse entrypoint: `run [--tenant ID] [--config PATH]`
  config.py              # load the tenant registry           (#3)
  tenants.py             # Tenant model                        (#3)
  credentials.py         # secret resolver + demo backend      (#4)
  nerdgraph.py           # NerdGraph client + demo source      (#5)
  metrics.py             # normalized metric types
  bigquery_sink.py       # BigQuery writer                     (#6/#7)
  verdict.py             # health-verdict logic                (#11)
  pipeline.py            # per-tenant orchestrator             (#7/#8)
config/tenants.example.yaml                                    # (#3)
sql/schema.sql, sql/views/                                     # (#6/#11)
docs/adr/                # architecture decision records
tests/                   # pytest, external calls mocked
.github/workflows/       # ci.yml, backend-health-pull.yml
pyproject.toml
```

## Consequences

- New tenants are onboarded by editing the registry + adding a secret — no code
  change (satisfies #3).
- GitHub Actions cron is the single scheduler; changing cadence is a one-line
  edit to the workflow.
- The optional-extra split means CI and the demo run without GCP credentials,
  while production installs the `bigquery` extra.
