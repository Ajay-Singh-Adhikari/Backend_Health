# Multi-tenant design

How Backend Health serves many client sites from one pipeline without a code
change per client. Addresses issue #3.

## Tenant

A **tenant** is one monitored client site. Each has its own New Relic account,
its own credentials, and its own rows in BigQuery. The model lives in
`backend_health/tenants.py`:

| Field | Required | Purpose |
|---|---|---|
| `tenant_id` | yes | Opaque, stable, unique. Public. Never a real client name. |
| `status` | yes | `active` / `needs-setup` / `paused` (see `docs/tenants.md`). |
| `newrelic_account_id` | active only | Which New Relic account to query. |
| `credential_ref` | active only | Lookup key for the secret backend (#4). **Not** a secret. |
| `codename` | no | Internal-only label. Never a real client name in this repo. |
| `overrides` | no | Per-tenant verdict-threshold overrides (#11). |

## Registry

The registry is a YAML file (`config/tenants.example.yaml`), loaded and
validated by `backend_health/config.py`. Chosen over a database table because a
non-engineer can edit YAML in a PR, and it versions cleanly.

Validation (fails the run loudly, rather than silently skipping a tenant):

- every entry has a non-empty, unique `tenant_id`;
- `status` is one of the three valid values;
- an `active` tenant has both `newrelic_account_id` and `credential_ref`.

Verify what the registry loads:

```
python -m backend_health tenants --config config/tenants.example.yaml
```

## Isolation model

One set of pipeline code, strict per-tenant separation of everything else:

- **Credentials** — resolved at runtime by `credential_ref` from the secret
  backend (#4). No tenant's key is ever in this repo or in another tenant's run.
- **Data** — every BigQuery row carries `tenant_id`; tables are partitioned by
  date and clustered by `tenant_id` (#6). A per-tenant query never scans across
  tenants by accident.
- **Failure** — one tenant's outage or bad key fails only that tenant's slice of
  the run, never the others (#8).
- **Dashboards** — a single dashboard with a tenant selector reads one tenant's
  data at a time (#9), rather than one copied dashboard per client.

## Onboarding a tenant (config level)

1. Store the tenant's NerdGraph key in the secret backend under a new
   `credential_ref` (#4).
2. Add one entry to the registry with an opaque `tenant_id`, the New Relic
   account ID, and that `credential_ref`.
3. The next scheduled run (#7) picks it up — no code change.

Full operational runbook: `docs/onboarding.md` (#12).
