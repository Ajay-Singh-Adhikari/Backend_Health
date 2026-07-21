from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LatencySample:
    """Response-time percentiles for one transaction/endpoint over the window."""

    tenant_id: str
    collected_at: datetime
    transaction: str
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_rpm: float


@dataclass(frozen=True)
class Bottleneck:
    """A slow transaction trace surfaced by New Relic APM."""

    tenant_id: str
    collected_at: datetime
    transaction: str
    duration_ms: float
    kind: str


@dataclass(frozen=True)
class ResourceSample:
    """Host-level resource pressure over the window."""

    tenant_id: str
    collected_at: datetime
    host: str
    cpu_percent: float
    memory_percent: float


@dataclass(frozen=True)
class MetricsBundle:
    """Everything pulled for one tenant in one run."""

    tenant_id: str
    collected_at: datetime
    latency: list[LatencySample]
    bottlenecks: list[Bottleneck]
    resources: list[ResourceSample]

    def is_empty(self) -> bool:
        return not (self.latency or self.bottlenecks or self.resources)
