# Per-tenant credentials

How each tenant's New Relic API key is stored and resolved. Addresses issue #4.

## Principle

A tenant's NerdGraph key is **never** in this repo, in the tenant registry, in
BigQuery, or in a dashboard. The registry holds only a `credential_ref` — a
lookup key. At runtime the pipeline resolves `credential_ref` to the actual key
through a credential backend, uses it for that tenant's API calls, and never
persists or logs it.

## Backends

`backend_health/credentials.py` defines a `CredentialBackend` protocol
(`get_api_key(credential_ref) -> str`) with these implementations, selected by
`BACKEND_HEALTH_CREDENTIALS_MODE` (default `demo`):

| Mode | Backend | Use |
|---|---|---|
| `demo` | `DemoCredentialBackend` | Returns obviously-fake `demo-key-<ref>` values. Lets the pipeline run end-to-end with no real secrets. |
| `env` | `EnvCredentialBackend` | Reads a per-tenant environment variable. How GitHub Actions secrets reach the job. |

### `env` variable naming

`credential_ref` is upper-cased with non-alphanumerics replaced by `_`, then
prefixed with `BACKEND_HEALTH_NRKEY_`:

```
credential_ref "tenant-a"  ->  BACKEND_HEALTH_NRKEY_TENANT_A
```

Because normalization upper-cases and collapses non-alphanumerics to `_`, keep
`credential_ref` values distinct *after* normalization (e.g. `tenant-a` and
`tenant.a` both map to `..._TENANT_A`). Using the `tenant_id`, which the
registry already forces to be unique, avoids this.

In the scheduled workflow, store each key as an Actions secret and map it in:

```yaml
env:
  BACKEND_HEALTH_CREDENTIALS_MODE: env
  BACKEND_HEALTH_NRKEY_TENANT_A: ${{ secrets.BACKEND_HEALTH_NRKEY_TENANT_A }}
```

A production deployment can add a `secretmanager` backend (e.g. GCP Secret
Manager) implementing the same protocol, with no change to callers.

## Rotation and revocation

- **Rotate:** create a new key in New Relic, update the secret (Actions secret
  or Secret Manager version), then delete the old key. `credential_ref` is
  unchanged, so the registry needs no edit.
- **Revoke (client offboarded):** set the tenant `status: paused` in the
  registry so it is skipped, then delete the secret and the New Relic key.

## Committed-secret backstop

`scripts/check_no_secrets.py` scans every tracked file for New Relic
key-shaped strings and fails CI if one is found. It runs as a step in
`ci.yml`. If it ever fires: remove the string, rotate the leaked key, and move
it into the credential backend.
