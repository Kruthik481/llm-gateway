from collections.abc import Mapping

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from app.core.ledger import UsageRecord


class Metrics:
    """Prometheus metrics in a private registry, so each app instance (and test) starts clean."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "gateway_requests_total",
            "Proxy requests by outcome",
            ["status", "provider", "cache"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "gateway_request_latency_seconds",
            "Time from admission to the last byte",
            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
            registry=self.registry,
        )
        self.ttft = Histogram(
            "gateway_ttft_seconds",
            "Time to the first streamed token",
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=self.registry,
        )
        self.fallbacks = Counter(
            "gateway_fallbacks_total",
            "Requests answered after at least one failed attempt",
            registry=self.registry,
        )
        self.circuit_open = Gauge(
            "gateway_circuit_open",
            "1 while a provider's circuit is open",
            ["provider"],
            registry=self.registry,
        )

    def observe(self, record: UsageRecord) -> None:
        cache = "hit" if record.cache_hit else "miss"
        self.requests.labels(record.status, record.provider or "none", cache).inc()
        self.latency.observe(record.latency_ms / 1000)
        if record.ttft_ms is not None:
            self.ttft.observe(record.ttft_ms / 1000)
        if record.attempts > 1 and record.status != "error":
            self.fallbacks.inc()

    def render(self, circuits: Mapping[str, str]) -> bytes:
        for provider, state in circuits.items():
            self.circuit_open.labels(provider).set(1 if state == "open" else 0)
        return generate_latest(self.registry)
