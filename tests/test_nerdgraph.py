from datetime import datetime

import pytest

from backend_health.credentials import DemoCredentialBackend
from backend_health.nerdgraph import (
    NRQL_BOTTLENECKS,
    NRQL_LATENCY,
    NRQL_RESOURCES,
    DemoMetricsSource,
    NerdGraphClient,
    NerdGraphError,
    NerdGraphMetricsSource,
    get_source,
)
from backend_health.tenants import Tenant

COLLECTED_AT = datetime(2026, 7, 21, 12, 0, 0)

TENANT = Tenant(
    tenant_id="tenant-a",
    status="active",
    newrelic_account_id="1000001",
    credential_ref="tenant-a",
)


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    """Returns canned NRQL results keyed by the NRQL string in the request."""

    def __init__(self, results_by_nrql):
        self._results_by_nrql = results_by_nrql
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append((url, json, headers))
        nrql = json["variables"]["nrql"]
        results = self._results_by_nrql.get(nrql, [])
        return FakeResponse({"data": {"actor": {"account": {"nrql": {"results": results}}}}})


def test_demo_source_is_deterministic():
    source = DemoMetricsSource()
    a = source.fetch(TENANT, COLLECTED_AT)
    b = source.fetch(TENANT, COLLECTED_AT)
    assert a == b
    assert a.tenant_id == "tenant-a"
    assert len(a.latency) == 3
    assert len(a.resources) == 2
    assert not a.is_empty()


def test_demo_source_varies_by_tenant():
    source = DemoMetricsSource()
    other = Tenant(tenant_id="tenant-z", status="active",
                   newrelic_account_id="9", credential_ref="tenant-z")
    assert source.fetch(TENANT, COLLECTED_AT) != source.fetch(other, COLLECTED_AT)


def test_client_run_nrql_parses_results():
    session = FakeSession({"SELECT 1": [{"x": 1}]})
    client = NerdGraphClient("demo-key", "1000001", session=session)
    assert client.run_nrql("SELECT 1") == [{"x": 1}]
    # api key travels in the header, never the query body
    assert session.calls[0][2]["API-Key"] == "demo-key"


def test_client_non_numeric_account_raises():
    session = FakeSession({})
    client = NerdGraphClient("demo-key", "DEMO-1000001", session=session)
    with pytest.raises(NerdGraphError, match="not numeric"):
        client.run_nrql("SELECT 1")


def test_client_http_error_raises():
    class ErrSession:
        def post(self, *_, **__):
            return FakeResponse({}, status_code=403, text="forbidden")

    client = NerdGraphClient("k", "1", session=ErrSession())
    with pytest.raises(NerdGraphError, match="HTTP 403"):
        client.run_nrql("SELECT 1")


def test_client_graphql_error_raises():
    class GqlErrSession:
        def post(self, *_, **__):
            return FakeResponse({"errors": [{"message": "bad nrql"}]})

    client = NerdGraphClient("k", "1", session=GqlErrSession())
    with pytest.raises(NerdGraphError, match="GraphQL errors"):
        client.run_nrql("SELECT 1")


def test_client_non_json_body_raises():
    class NonJsonResponse:
        status_code = 200
        text = "<html>gateway error</html>"

        def json(self):
            raise ValueError("no json")

    class NonJsonSession:
        def post(self, *_, **__):
            return NonJsonResponse()

    client = NerdGraphClient("k", "1", session=NonJsonSession())
    with pytest.raises(NerdGraphError, match="non-JSON body"):
        client.run_nrql("SELECT 1")


def test_nerdgraph_source_normalizes_and_converts_units():
    session = FakeSession(
        {
            NRQL_LATENCY: [
                {
                    "name": "GET /api/items",
                    "percentile.duration": {"50": 0.05, "95": 0.2, "99": 0.4},
                    "throughput": 120.0,
                }
            ],
            NRQL_BOTTLENECKS: [{"name": "POST /api/orders", "duration": 2.5}],
            NRQL_RESOURCES: [{"hostname": "web-1", "cpu": 72.0, "mem": 63.0}],
        }
    )
    source = NerdGraphMetricsSource(DemoCredentialBackend(), session=session)
    bundle = source.fetch(TENANT, COLLECTED_AT)

    assert bundle.latency[0].p50_ms == 50.0
    assert bundle.latency[0].p95_ms == 200.0
    assert bundle.latency[0].throughput_rpm == 120.0
    assert bundle.bottlenecks[0].duration_ms == 2500.0
    assert bundle.bottlenecks[0].kind == "slow_transaction"
    assert bundle.resources[0].host == "web-1"
    assert bundle.resources[0].cpu_percent == 72.0


def test_nerdgraph_source_handles_null_values_for_empty_window():
    session = FakeSession(
        {
            NRQL_LATENCY: [
                {"name": "GET /idle", "percentile.duration": {"50": None, "95": None,
                 "99": None}, "throughput": None}
            ],
            NRQL_RESOURCES: [{"hostname": "web-1", "cpu": None, "mem": None}],
        }
    )
    source = NerdGraphMetricsSource(DemoCredentialBackend(), session=session)
    bundle = source.fetch(TENANT, COLLECTED_AT)
    assert bundle.latency[0].p95_ms == 0.0
    assert bundle.latency[0].throughput_rpm == 0.0
    assert bundle.resources[0].cpu_percent == 0.0


def test_nerdgraph_source_handles_facet_fallback():
    session = FakeSession({NRQL_RESOURCES: [{"facet": "web-9", "cpu": 10.0, "mem": 20.0}]})
    source = NerdGraphMetricsSource(DemoCredentialBackend(), session=session)
    bundle = source.fetch(TENANT, COLLECTED_AT)
    assert bundle.resources[0].host == "web-9"


def test_get_source_factory():
    assert isinstance(get_source("demo"), DemoMetricsSource)
    assert isinstance(
        get_source("nerdgraph", credentials=DemoCredentialBackend()), NerdGraphMetricsSource
    )
    with pytest.raises(ValueError, match="unknown metrics source"):
        get_source("bogus")
    with pytest.raises(ValueError, match="requires a credential backend"):
        get_source("nerdgraph")
