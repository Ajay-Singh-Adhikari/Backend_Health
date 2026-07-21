import pytest

from backend_health.credentials import (
    DemoCredentialBackend,
    EnvCredentialBackend,
    MissingCredentialError,
    get_backend,
)


def test_demo_backend_returns_fake_key():
    backend = DemoCredentialBackend()
    key = backend.get_api_key("tenant-a")
    assert key == "demo-key-tenant-a"
    assert not key.startswith("NRAK-")


def test_demo_backend_rejects_empty_ref():
    with pytest.raises(MissingCredentialError):
        DemoCredentialBackend().get_api_key("")


def test_env_backend_var_name_normalization():
    backend = EnvCredentialBackend(environ={})
    assert backend.var_name("tenant-a") == "BACKEND_HEALTH_NRKEY_TENANT_A"


def test_env_backend_reads_value():
    backend = EnvCredentialBackend(environ={"BACKEND_HEALTH_NRKEY_TENANT_A": "secret"})
    assert backend.get_api_key("tenant-a") == "secret"


def test_env_backend_missing_raises():
    backend = EnvCredentialBackend(environ={})
    with pytest.raises(MissingCredentialError, match="BACKEND_HEALTH_NRKEY_TENANT_A"):
        backend.get_api_key("tenant-a")


def test_get_backend_default_is_demo():
    assert isinstance(get_backend("demo"), DemoCredentialBackend)


def test_get_backend_unknown_mode():
    with pytest.raises(ValueError, match="unknown credentials mode"):
        get_backend("bogus")
