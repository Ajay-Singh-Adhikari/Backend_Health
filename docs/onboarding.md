# Onboarding a real client

Everything up to this point — the pipeline, the schema, the dashboard guide —
has been built and exercised entirely against **demo** tenants
(`config/tenants.example.yaml`, `DemoCredentialBackend`, `JsonlSink`) because
no real New Relic or GCP access was available while building it. This is the
runbook for replacing that demo path with a real client, end to end.

The registry, credential-resolution, and CLI steps below (Steps 2, 3, 6, and
the `pipeline-health` command in Step 8) were actually run against a
throwaway registry file with a synthetic tenant before being written down —
the commands and the `MissingCredentialError` message you'll see are real
output, not invented. The BigQuery DDL and Looker Studio steps (4, 5, 7), and
the alert-webhook check in Step 8, could not be — this environment has no
live GCP project, Looker Studio access, or webhook to post to, the same
constraint noted throughout #6–#11 — so those are standard, documented
usage, not something executed and confirmed here. Verify them the first time
you actually run them, same as any new runbook.

## Step 0: What "onboarding" means here

One client site = one **tenant** (`docs/multi-tenant.md`). Onboarding a real
client is: confirm their New Relic access, give them an opaque tenant ID,
store their credential, add one registry entry, and point the scheduled job
at real infrastructure instead of the demo path. No code changes.

## Step 1: Confirm New Relic access

Follow `docs/tenants.md`'s process: is the New Relic PHP agent already
running on this client's site? If yes, get the NerdGraph account ID and a
user API key — this is "wire up an existing tool's API" work. If no, this is
the bigger initiative the README's open question #1 describes (install the
agent, sort licensing) — do that first; the rest of this runbook assumes
access already exists. Record the outcome as a new row in `docs/tenants.md`
with an opaque tenant ID, same as the existing demo rows.

## Step 2: Create the real tenant registry

`config/tenants.example.yaml` is the tracked demo/test fixture — CI and the
test suite depend on it staying exactly as-is. Real tenants go in
`config/tenants.yaml`, which is gitignored (added alongside this runbook)
specifically so a real client's registry entries never need to be committed:

```
cp config/tenants.example.yaml config/tenants.yaml
```

Then edit `config/tenants.yaml`, adding one entry per real client:

```yaml
  - tenant_id: real-client-1        # opaque — never the real client/company name
    codename: internal label only   # also opaque, never a real client name
    newrelic_account_id: "3800123"  # their real New Relic account ID
    status: active
    credential_ref: real-client-1   # a lookup key, not the key itself
```

Verify it loads:

```
python -m backend_health tenants --config config/tenants.yaml
```

## Step 3: Store the real credential

Per `docs/credentials.md`: the registry's `credential_ref` is a lookup key,
never the key itself. For the scheduled GitHub Actions workflow, store the
client's NerdGraph user key as a repo/org secret named
`BACKEND_HEALTH_NRKEY_<CREDENTIAL_REF>` (uppercased, non-alphanumerics as
`_`) — for `credential_ref: real-client-1`, that's
`BACKEND_HEALTH_NRKEY_REAL_CLIENT_1`.

## Step 4: Provision the real BigQuery dataset

Create the dataset, then apply the generated DDL, substituting `{{dataset}}`
with the real `project.dataset`:

```
sed "s/{{dataset}}/my-project.backend_health/g" sql/schema.sql | bq query --use_legacy_sql=false
sed "s/{{dataset}}/my-project.backend_health/g" sql/views/daily_tenant_metrics.sql | bq query --use_legacy_sql=false
sed "s/{{dataset}}/my-project.backend_health/g" sql/views/tenant_health_verdict.sql | bq query --use_legacy_sql=false
sed "s/{{dataset}}/my-project.backend_health/g" sql/views/latest_tenant_verdict.sql | bq query --use_legacy_sql=false
```

(Or paste each into the BigQuery console — any way to run standard SQL DDL
works; there's nothing Python-specific about this step.)

## Step 5: Give the pipeline real GCP + credentials-mode config

Install the optional BigQuery extra (`pip install -e '.[bigquery]'` — kept
optional, per ADR 0001, precisely so the demo path never needed it) and
authenticate the environment running the job (a GCP service account key or,
preferably, Workload Identity Federation for GitHub Actions — avoid a
long-lived JSON key in a secret if the option is available).

In the scheduled workflow (`.github/workflows/backend-health-pull.yml`),
switch from the demo defaults to the real path:

```yaml
- name: Run pull job
  env:
    BACKEND_HEALTH_CREDENTIALS_MODE: env
    BACKEND_HEALTH_NRKEY_REAL_CLIENT_1: ${{ secrets.BACKEND_HEALTH_NRKEY_REAL_CLIENT_1 }}
  run: >
    python -m backend_health run
    --config config/tenants.yaml
    --source nerdgraph
    --sink bigquery
    --dataset my-project.backend_health
```

(`config/tenants.yaml` isn't in the repo per Step 2 — check it out via a
private path, a deploy step, or a secret-backed config fetch; how depends on
your CI setup and is a deliberate "not decided here" per the README's
remaining open question about the pull job's exact deployment shape.)

## Step 6: Verify before trusting the cron

Run once manually (`workflow_dispatch`, or locally with real env vars set)
scoped to just the new tenant before letting the schedule pick it up:

```
python -m backend_health run --tenant real-client-1 --config config/tenants.yaml \
  --source nerdgraph --sink bigquery --dataset my-project.backend_health
```

If the credential isn't wired up yet, this is exactly the error you'll see
(verified above while writing this runbook) — it tells you precisely which
env var is missing, rather than a generic auth failure:

```
backend_health.credentials.MissingCredentialError: environment variable
BACKEND_HEALTH_NRKEY_REAL_CLIENT_1 is not set for credential_ref 'real-client-1'
```

Then confirm rows landed:

```sql
SELECT * FROM `my-project.backend_health.latency_samples`
WHERE tenant_id = 'real-client-1' ORDER BY collected_at DESC LIMIT 10;
```

## Step 7: Build the dashboard

Follow `docs/dashboard.md` end to end, pointing both BigQuery data sources
(`latest_tenant_verdict`, `daily_tenant_metrics`) at the real dataset.
Confirm the tenant selector picks up `real-client-1` and the status card
shows a real verdict, not a demo one.

## Step 8: Confirm reliability is live for the new tenant

After the first few scheduled runs, check:

```
python -m backend_health pipeline-health --state-file out/pipeline_health.json
```

(or wherever `--state-file` points in the real deployment) and confirm
`real-client-1` appears with `last_status: ok`. If `BACKEND_HEALTH_ALERT_WEBHOOK`
is configured, a deliberately-broken credential should trigger a webhook alert
once the failure streak crosses the threshold (#8) — worth testing once
before relying on it.

## Checklist

- [ ] New Relic access confirmed and recorded in `docs/tenants.md`
- [ ] `config/tenants.yaml` created (not committed) with the new tenant's opaque ID
- [ ] Real NerdGraph key stored as `BACKEND_HEALTH_NRKEY_<CREDENTIAL_REF>`
- [ ] Real BigQuery dataset provisioned with all four generated SQL files applied
- [ ] `google-cloud-bigquery` installed; GCP auth configured for the job
- [ ] Scheduled workflow switched to `--source nerdgraph --sink bigquery --config config/tenants.yaml`
- [ ] A manual `--tenant real-client-1` run verified end-to-end before trusting the cron
- [ ] Dashboard rebuilt against the real dataset, tenant selector confirmed
- [ ] `pipeline-health` confirms the tenant is reporting `ok`, and alerting tested once
