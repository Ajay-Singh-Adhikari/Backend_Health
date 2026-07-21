from __future__ import annotations

import os
import re
from typing import Protocol, runtime_checkable


class MissingCredentialError(RuntimeError):
    """Raised when a tenant's API key cannot be resolved from the backend."""


@runtime_checkable
class CredentialBackend(Protocol):
    """Resolves a tenant's `credential_ref` to a NerdGraph API key at runtime.

    Implementations must never persist or log the returned key.
    """

    def get_api_key(self, credential_ref: str) -> str: ...


class DemoCredentialBackend:
    """Returns deterministic, non-functional demo keys.

    Used to exercise the pipeline end-to-end without real secrets. The values
    are obviously fake (`demo-key-...`) and are not New Relic keys.
    """

    def get_api_key(self, credential_ref: str) -> str:
        if not credential_ref:
            raise MissingCredentialError("empty credential_ref")
        return f"demo-key-{credential_ref}"


class EnvCredentialBackend:
    """Resolves keys from environment variables.

    This is how GitHub Actions secrets reach the job: a secret per tenant,
    exposed as an env var. The variable name is `{prefix}{REF}` with the
    credential_ref upper-cased and non-alphanumerics replaced by `_`
    (e.g. ref `tenant-a` -> `BACKEND_HEALTH_NRKEY_TENANT_A`).
    """

    def __init__(self, prefix: str = "BACKEND_HEALTH_NRKEY_", environ: dict | None = None):
        self.prefix = prefix
        self._environ = environ if environ is not None else os.environ

    def var_name(self, credential_ref: str) -> str:
        if not credential_ref:
            raise MissingCredentialError("empty credential_ref")
        suffix = re.sub(r"[^A-Z0-9]", "_", credential_ref.upper())
        return f"{self.prefix}{suffix}"

    def get_api_key(self, credential_ref: str) -> str:
        name = self.var_name(credential_ref)
        value = self._environ.get(name)
        if not value:
            raise MissingCredentialError(
                f"environment variable {name} is not set for credential_ref '{credential_ref}'"
            )
        return value


_BACKENDS = {
    "demo": DemoCredentialBackend,
    "env": EnvCredentialBackend,
}

DEFAULT_MODE = "demo"
MODE_ENV_VAR = "BACKEND_HEALTH_CREDENTIALS_MODE"


def get_backend(mode: str | None = None) -> CredentialBackend:
    """Return the credential backend for `mode` (defaults to the env var, then demo)."""
    mode = mode or os.environ.get(MODE_ENV_VAR, DEFAULT_MODE)
    try:
        return _BACKENDS[mode]()
    except KeyError:
        raise ValueError(
            f"unknown credentials mode {mode!r}; expected one of {sorted(_BACKENDS)}"
        ) from None
