import textwrap

import pytest

from backend_health.config import (
    RegistryError,
    active_tenants,
    get_tenant,
    load_registry,
)


def _write(tmp_path, body: str):
    path = tmp_path / "tenants.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_loads_example_registry():
    tenants = load_registry("config/tenants.example.yaml")
    assert {t.tenant_id for t in tenants} == {"tenant-a", "tenant-b", "tenant-c"}
    assert all(t.is_active for t in tenants)
    assert active_tenants(tenants) == tenants


def test_overrides_parsed():
    tenants = load_registry("config/tenants.example.yaml")
    tenant_a = get_tenant(tenants, "tenant-a")
    assert tenant_a.overrides["latency_p95_ms"]["action"] == 1500


def test_active_requires_account_and_credential(tmp_path):
    path = _write(
        tmp_path,
        """
        tenants:
          - tenant_id: tenant-x
            status: active
        """,
    )
    with pytest.raises(RegistryError, match="requires both"):
        load_registry(path)


def test_needs_setup_may_omit_account(tmp_path):
    path = _write(
        tmp_path,
        """
        tenants:
          - tenant_id: tenant-x
            status: needs-setup
        """,
    )
    tenants = load_registry(path)
    assert active_tenants(tenants) == []


def test_invalid_status_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        tenants:
          - tenant_id: tenant-x
            status: bogus
        """,
    )
    with pytest.raises(RegistryError, match="invalid status"):
        load_registry(path)


def test_duplicate_ids_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        tenants:
          - tenant_id: dup
            status: paused
          - tenant_id: dup
            status: paused
        """,
    )
    with pytest.raises(RegistryError, match="duplicate tenant_id"):
        load_registry(path)


def test_missing_tenants_key_rejected(tmp_path):
    path = _write(tmp_path, "other: 1\n")
    with pytest.raises(RegistryError, match="top-level 'tenants' list"):
        load_registry(path)


def test_unknown_tenant_lookup(tmp_path):
    tenants = load_registry("config/tenants.example.yaml")
    with pytest.raises(RegistryError, match="unknown tenant_id"):
        get_tenant(tenants, "nope")
