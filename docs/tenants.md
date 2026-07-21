# Tenant / New Relic inventory

Answers README open question #1 ("Is New Relic already active anywhere, with API/license access available?") and feeds the multi-tenant registry design (#3).

Every client site that Backend Health monitors is a **tenant**. This document is the human-readable audit of each tenant's New Relic status. The machine-readable version the pipeline actually reads lives in `config/tenants.example.yaml` (added in #3).

> **Privacy:** never put real client/company names in this file — it is public. Use stable, opaque tenant IDs (`tenant-a`, `tenant-b`, …). The mapping from tenant ID to the real client is kept privately, outside this repo.

## Status legend

| Status | Meaning | What this project becomes for that tenant |
|---|---|---|
| `active` | New Relic PHP agent already running; account ID + API key available | "Wire up an existing tool's API" — ready for the pipeline |
| `needs-setup` | No New Relic yet; requires agent install + licensing/budget | Bigger initiative before the pipeline can pull anything |
| `paused` | Was active, monitoring intentionally stopped | Excluded from scheduled runs |

## Inventory

> The rows below are **demo tenants** used to build and exercise the pipeline end-to-end without real credentials. They model the "New Relic is active across sites" scenario. Replace them with the real audit as each client site is confirmed (see `docs/onboarding.md`, added in #12).

| Tenant ID | New Relic status | NR account ID | API key access | Plan tier | Notes |
|---|---|---|---|---|---|
| `tenant-a` | `active` | `DEMO-1000001` | demo key in secret store | demo | High-traffic site; used to exercise per-tenant latency thresholds |
| `tenant-b` | `active` | `DEMO-1000002` | demo key in secret store | demo | Low-traffic site; used to exercise "normal latency differs per tenant" |
| `tenant-c` | `active` | `DEMO-1000003` | demo key in secret store | demo | Used to exercise resource-pressure (CPU/memory) verdicts |

No real credentials appear in this repo. Demo account IDs above are non-functional placeholders; the demo API keys they refer to are resolved by the credential backend in demo mode (see `docs/credentials.md`, added in #4).

## How a real tenant gets added here

1. Confirm the site has the New Relic PHP agent running (or flag it `needs-setup`).
2. Capture its NerdGraph **user key** into the secret store — never into this file (#4).
3. Add a row above with an opaque tenant ID and the New Relic account ID.
4. Add the matching entry to `config/tenants.example.yaml` (#3).

Full step-by-step is the onboarding runbook (#12).
