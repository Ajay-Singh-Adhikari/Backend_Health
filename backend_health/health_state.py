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
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable state must never break a scheduled run;
            # start clean rather than crash the pipeline over bookkeeping.
            return cls()
        if not isinstance(data, dict):
            # Valid JSON but the wrong shape (e.g. a list) is just as much a
            # "don't crash the run over bookkeeping" case as invalid JSON.
            return cls()
        return cls(data)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._state, indent=2, sort_keys=True))

    @staticmethod
    def _coerce_entry(entry: object) -> dict:
        """A malformed per-tenant entry (wrong type) is treated as absent,
        for the same reason a malformed state file is: bookkeeping must never
        crash a scheduled run."""
        return entry if isinstance(entry, dict) else {}

    def record(self, tenant_id: str, ok: bool, error: str | None = None) -> TenantHealth:
        prior = self._coerce_entry(self._state.get(tenant_id))
        streak = 0 if ok else prior.get("consecutive_failures", 0) + 1
        entry = {
            "consecutive_failures": streak,
            "last_status": "ok" if ok else "failed",
            "last_error": None if ok else error,
        }
        self._state[tenant_id] = entry
        return TenantHealth(tenant_id, streak, entry["last_status"], entry["last_error"])

    def get(self, tenant_id: str) -> TenantHealth | None:
        if tenant_id not in self._state:
            return None
        entry = self._coerce_entry(self._state.get(tenant_id))
        return TenantHealth(
            tenant_id,
            entry.get("consecutive_failures", 0),
            entry.get("last_status", "unknown"),
            entry.get("last_error"),
        )

    def all(self) -> list[TenantHealth]:
        return [self.get(tid) for tid in sorted(self._state)]
