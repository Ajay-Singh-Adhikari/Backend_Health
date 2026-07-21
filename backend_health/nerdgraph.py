from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Protocol

import requests

from backend_health.credentials import CredentialBackend
from backend_health.metrics import (
    Bottleneck,
    LatencySample,
    MetricsBundle,
    ResourceSample,
)
from backend_health.tenants import Tenant

NERDGRAPH_ENDPOINT = "https://api.newrelic.com/graphql"

# NerdGraph wraps NRQL in GraphQL. Variables (not string interpolation) keep the
# account id and NRQL out of the query body.
_GQL = """
query ($accountId: Int!, $nrql: Nrql!) {
  actor {
    account(id: $accountId) {
      nrql(query: $nrql) { results }
    }
  }
}
""".strip()

# New Relic `duration` is in seconds; normalize to milliseconds.
_S_TO_MS = 1000.0

NRQL_LATENCY = (
    "SELECT percentile(duration, 50, 95, 99), rate(count(*), 1 minute) AS 'throughput' "
    "FROM Transaction FACET name LIMIT 20 SINCE 60 MINUTES AGO"
)
NRQL_BOTTLENECKS = (
    "SELECT max(duration) AS 'duration' FROM Transaction "
    "FACET name LIMIT 10 SINCE 60 MINUTES AGO"
)
NRQL_RESOURCES = (
    "SELECT average(cpuPercent) AS 'cpu', average(memoryUsedPercent) AS 'mem' "
    "FROM SystemSample FACET hostname LIMIT 20 SINCE 60 MINUTES AGO"
)


class NerdGraphError(RuntimeError):
    """Raised on a NerdGraph transport error or a GraphQL-level error."""


class NerdGraphClient:
    """Thin NerdGraph client that runs NRQL and returns raw result rows."""

    def __init__(
        self,
        api_key: str,
        account_id: str | int,
        *,
        endpoint: str = NERDGRAPH_ENDPOINT,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.account_id = account_id
        self.endpoint = endpoint
        self.timeout = timeout
        self._session = session or requests.Session()

    def _account_id_int(self) -> int:
        try:
            return int(self.account_id)
        except (TypeError, ValueError):
            raise NerdGraphError(
                f"account id {self.account_id!r} is not numeric; a real New Relic "
                "account id is required for live queries"
            ) from None

    def run_nrql(self, nrql: str) -> list[dict]:
        payload = {
            "query": _GQL,
            "variables": {"accountId": self._account_id_int(), "nrql": nrql},
        }
        try:
            resp = self._session.post(
                self.endpoint,
                json=payload,
                headers={"API-Key": self.api_key, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise NerdGraphError(f"NerdGraph request failed: {exc}") from exc

        if resp.status_code != 200:
            raise NerdGraphError(f"NerdGraph returned HTTP {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        if body.get("errors"):
            raise NerdGraphError(f"NerdGraph GraphQL errors: {body['errors']}")

        try:
            return body["data"]["actor"]["account"]["nrql"]["results"]
        except (KeyError, TypeError) as exc:
            raise NerdGraphError(f"unexpected NerdGraph response shape: {body}") from exc


class MetricsSource(Protocol):
    def fetch(self, tenant: Tenant, collected_at: datetime) -> MetricsBundle: ...


def _facet_value(row: dict, field: str) -> str:
    value = row.get(field, row.get("facet"))
    return str(value) if value is not None else "unknown"


def _num(value: object) -> float:
    """Coerce a NerdGraph numeric field to float; treat null/missing as 0.0.

    An empty query window returns null for percentiles and aggregates.
    """
    return float(value) if value is not None else 0.0


class NerdGraphMetricsSource:
    """Fetches and normalizes APM metrics for a tenant via NerdGraph."""

    def __init__(
        self,
        credentials: CredentialBackend,
        *,
        endpoint: str = NERDGRAPH_ENDPOINT,
        session: requests.Session | None = None,
    ):
        self._credentials = credentials
        self._endpoint = endpoint
        self._session = session or requests.Session()

    def _client(self, tenant: Tenant) -> NerdGraphClient:
        api_key = self._credentials.get_api_key(tenant.credential_ref)
        return NerdGraphClient(
            api_key,
            tenant.newrelic_account_id,
            endpoint=self._endpoint,
            session=self._session,
        )

    def fetch(self, tenant: Tenant, collected_at: datetime) -> MetricsBundle:
        client = self._client(tenant)
        return MetricsBundle(
            tenant_id=tenant.tenant_id,
            collected_at=collected_at,
            latency=self._latency(client, tenant, collected_at),
            bottlenecks=self._bottlenecks(client, tenant, collected_at),
            resources=self._resources(client, tenant, collected_at),
        )

    def _latency(self, client, tenant, collected_at) -> list[LatencySample]:
        samples = []
        for row in client.run_nrql(NRQL_LATENCY):
            pct = row.get("percentile.duration") or {}
            samples.append(
                LatencySample(
                    tenant_id=tenant.tenant_id,
                    collected_at=collected_at,
                    transaction=_facet_value(row, "name"),
                    p50_ms=_num(pct.get("50")) * _S_TO_MS,
                    p95_ms=_num(pct.get("95")) * _S_TO_MS,
                    p99_ms=_num(pct.get("99")) * _S_TO_MS,
                    throughput_rpm=_num(row.get("throughput")),
                )
            )
        return samples

    def _bottlenecks(self, client, tenant, collected_at) -> list[Bottleneck]:
        out = []
        for row in client.run_nrql(NRQL_BOTTLENECKS):
            out.append(
                Bottleneck(
                    tenant_id=tenant.tenant_id,
                    collected_at=collected_at,
                    transaction=_facet_value(row, "name"),
                    duration_ms=_num(row.get("duration")) * _S_TO_MS,
                    kind="slow_transaction",
                )
            )
        return out

    def _resources(self, client, tenant, collected_at) -> list[ResourceSample]:
        out = []
        for row in client.run_nrql(NRQL_RESOURCES):
            out.append(
                ResourceSample(
                    tenant_id=tenant.tenant_id,
                    collected_at=collected_at,
                    host=_facet_value(row, "hostname"),
                    cpu_percent=_num(row.get("cpu")),
                    memory_percent=_num(row.get("mem")),
                )
            )
        return out


class DemoMetricsSource:
    """Generates deterministic synthetic metrics, seeded per tenant and hour.

    Re-running the same hour yields identical data, which keeps ingestion
    idempotent without any network or credentials.
    """

    def fetch(self, tenant: Tenant, collected_at: datetime) -> MetricsBundle:
        rng = _seeded_rng(tenant.tenant_id, collected_at)

        latency = []
        for path in ("GET /api/items", "POST /api/orders", "GET /api/profile"):
            p50 = round(rng.uniform(40, 220), 1)
            latency.append(
                LatencySample(
                    tenant_id=tenant.tenant_id,
                    collected_at=collected_at,
                    transaction=path,
                    p50_ms=p50,
                    p95_ms=round(p50 * rng.uniform(2.0, 4.5), 1),
                    p99_ms=round(p50 * rng.uniform(4.5, 8.0), 1),
                    throughput_rpm=round(rng.uniform(30, 900), 1),
                )
            )

        bottlenecks = []
        for _ in range(rng.randint(0, 2)):
            bottlenecks.append(
                Bottleneck(
                    tenant_id=tenant.tenant_id,
                    collected_at=collected_at,
                    transaction=rng.choice(("POST /api/orders", "GET /api/report")),
                    duration_ms=round(rng.uniform(1500, 6000), 1),
                    kind="slow_transaction",
                )
            )

        resources = []
        for host in (f"{tenant.tenant_id}-web-1", f"{tenant.tenant_id}-web-2"):
            resources.append(
                ResourceSample(
                    tenant_id=tenant.tenant_id,
                    collected_at=collected_at,
                    host=host,
                    cpu_percent=round(rng.uniform(35, 95), 1),
                    memory_percent=round(rng.uniform(40, 90), 1),
                )
            )

        return MetricsBundle(
            tenant_id=tenant.tenant_id,
            collected_at=collected_at,
            latency=latency,
            bottlenecks=bottlenecks,
            resources=resources,
        )


def _seeded_rng(tenant_id: str, collected_at: datetime) -> random.Random:
    seed_material = f"{tenant_id}:{collected_at.strftime('%Y%m%d%H')}"
    seed = int(hashlib.sha256(seed_material.encode()).hexdigest(), 16)
    return random.Random(seed)


def get_source(
    mode: str,
    *,
    credentials: CredentialBackend | None = None,
    endpoint: str = NERDGRAPH_ENDPOINT,
    session: requests.Session | None = None,
) -> MetricsSource:
    if mode == "demo":
        return DemoMetricsSource()
    if mode == "nerdgraph":
        if credentials is None:
            raise ValueError("nerdgraph source requires a credential backend")
        return NerdGraphMetricsSource(credentials, endpoint=endpoint, session=session)
    raise ValueError(f"unknown metrics source mode {mode!r}; expected 'demo' or 'nerdgraph'")
