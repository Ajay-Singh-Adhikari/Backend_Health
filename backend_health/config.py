from __future__ import annotations

from pathlib import Path

import yaml

from backend_health.tenants import VALID_STATUSES, Tenant


class RegistryError(ValueError):
    """Raised when the tenant registry is malformed or internally inconsistent."""


def load_registry(path: str | Path) -> list[Tenant]:
    """Load and validate the tenant registry from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise RegistryError(f"tenant registry not found: {path}")

    data = yaml.safe_load(path.read_text()) or {}
    raw_tenants = data.get("tenants")
    if not isinstance(raw_tenants, list):
        raise RegistryError("registry must have a top-level 'tenants' list")

    tenants = [_parse_tenant(entry, index=i) for i, entry in enumerate(raw_tenants)]
    _check_unique_ids(tenants)
    return tenants


def active_tenants(tenants: list[Tenant]) -> list[Tenant]:
    return [t for t in tenants if t.is_active]


def get_tenant(tenants: list[Tenant], tenant_id: str) -> Tenant:
    for tenant in tenants:
        if tenant.tenant_id == tenant_id:
            return tenant
    raise RegistryError(f"unknown tenant_id: {tenant_id}")


def _parse_tenant(entry: object, index: int) -> Tenant:
    if not isinstance(entry, dict):
        raise RegistryError(f"tenant #{index} must be a mapping, got {type(entry).__name__}")

    tenant_id = entry.get("tenant_id")
    if not tenant_id or not isinstance(tenant_id, str):
        raise RegistryError(f"tenant #{index} is missing a non-empty string 'tenant_id'")

    status = entry.get("status")
    if status not in VALID_STATUSES:
        raise RegistryError(
            f"tenant '{tenant_id}' has invalid status {status!r}; "
            f"expected one of {VALID_STATUSES}"
        )

    account_id = entry.get("newrelic_account_id")
    credential_ref = entry.get("credential_ref")
    if status == "active" and not (account_id and credential_ref):
        raise RegistryError(
            f"active tenant '{tenant_id}' requires both 'newrelic_account_id' "
            "and 'credential_ref'"
        )

    return Tenant(
        tenant_id=tenant_id,
        status=status,
        newrelic_account_id=account_id,
        credential_ref=credential_ref,
        codename=entry.get("codename"),
        overrides=entry.get("overrides") or {},
    )


def _check_unique_ids(tenants: list[Tenant]) -> None:
    seen: set[str] = set()
    for tenant in tenants:
        if tenant.tenant_id in seen:
            raise RegistryError(f"duplicate tenant_id: {tenant.tenant_id}")
        seen.add(tenant.tenant_id)
