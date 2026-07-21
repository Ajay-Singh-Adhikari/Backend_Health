from __future__ import annotations

from dataclasses import dataclass, field

VALID_STATUSES = ("active", "needs-setup", "paused")


@dataclass(frozen=True)
class Tenant:
    """A single monitored client site.

    `credential_ref` is a lookup key for the secret backend, never a secret
    itself. `codename` is an internal-only label and must never carry a real
    client/company name in this repo.
    """

    tenant_id: str
    status: str
    newrelic_account_id: str | None = None
    credential_ref: str | None = None
    codename: str | None = None
    overrides: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status == "active"
