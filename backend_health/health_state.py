from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATE_FILE = "out/pipeline_health.json"


@dataclass
class TenantHealth:
    tenant_id: str
    consecutive_failures: int
    last_status: str  # "ok" or "failed"
    last_error: str | None = None


class PipelineHealthState:
    """Tracks each tenant's consecutive-failure streak across runs.

    Persisted as JSON so a fresh process (each scheduled run is a new GitHub
    Actions job) can tell whether a tenant has been failing repeatedly, not
    just in the current run. This is what makes "N consecutive runs failed"
    alerting possible without a database.
    """

    def __init__(self, state: dict[str, dict] | None = None):
        self._state = state or {}

    @classmethod
    def load(cls, path: str | Path) -> "PipelineHealthState":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            return cls(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable state must never break a scheduled run;
            # start clean rather than crash the pipeline over bookkeeping.
            return cls()

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._state, indent=2, sort_keys=True))

    def record(self, tenant_id: str, ok: bool, error: str | None = None) -> TenantHealth:
        prior = self._state.get(tenant_id, {})
        streak = 0 if ok else prior.get("consecutive_failures", 0) + 1
        entry = {
            "consecutive_failures": streak,
            "last_status": "ok" if ok else "failed",
            "last_error": None if ok else error,
        }
        self._state[tenant_id] = entry
        return TenantHealth(tenant_id, streak, entry["last_status"], entry["last_error"])

    def get(self, tenant_id: str) -> TenantHealth | None:
        entry = self._state.get(tenant_id)
        if entry is None:
            return None
        return TenantHealth(
            tenant_id,
            entry.get("consecutive_failures", 0),
            entry.get("last_status", "unknown"),
            entry.get("last_error"),
        )

    def all(self) -> list[TenantHealth]:
        return [self.get(tid) for tid in sorted(self._state)]
