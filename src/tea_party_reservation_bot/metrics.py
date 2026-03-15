from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, start_http_server

from tea_party_reservation_bot.config.settings import MetricsSettings
from tea_party_reservation_bot.logging import get_logger


class AppMetrics:
    def record_registration(self, *, amount: int = 1) -> None:
        return None

    def record_waitlist_join(self, *, amount: int = 1) -> None:
        return None

    def record_promotion(self, *, amount: int = 1) -> None:
        return None

    def record_cancellation(self, *, target: str, amount: int = 1) -> None:
        return None

    def record_publication_failure(self, *, amount: int = 1) -> None:
        return None

    def record_auth_denial(self, *, permission: str, amount: int = 1) -> None:
        return None

    def record_duplicate_suppression(self, *, source: str, amount: int = 1) -> None:
        return None

    def start_http_server(self, *, host: str, port: int) -> None:
        return None


class NoOpAppMetrics(AppMetrics):
    pass


@dataclass(slots=True)
class PrometheusAppMetrics(AppMetrics):
    registry: CollectorRegistry

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self._registrations = Counter(
            "tea_party_registrations_total",
            "Total successful confirmed registrations.",
            registry=self.registry,
        )
        self._waitlist_joins = Counter(
            "tea_party_waitlist_joins_total",
            "Total waitlist joins.",
            registry=self.registry,
        )
        self._promotions = Counter(
            "tea_party_waitlist_promotions_total",
            "Total promotions from waitlist to confirmed reservations.",
            registry=self.registry,
        )
        self._cancellations = Counter(
            "tea_party_cancellations_total",
            "Total cancellations by membership type.",
            labelnames=("target",),
            registry=self.registry,
        )
        self._publication_failures = Counter(
            "tea_party_publication_failures_total",
            "Total publication failures.",
            registry=self.registry,
        )
        self._auth_denials = Counter(
            "tea_party_auth_denials_total",
            "Total authorization denials by permission.",
            labelnames=("permission",),
            registry=self.registry,
        )
        self._duplicate_suppressions = Counter(
            "tea_party_duplicate_suppressions_total",
            "Total duplicate command suppressions by command source.",
            labelnames=("source",),
            registry=self.registry,
        )

    def record_registration(self, *, amount: int = 1) -> None:
        self._registrations.inc(amount)

    def record_waitlist_join(self, *, amount: int = 1) -> None:
        self._waitlist_joins.inc(amount)

    def record_promotion(self, *, amount: int = 1) -> None:
        self._promotions.inc(amount)

    def record_cancellation(self, *, target: str, amount: int = 1) -> None:
        self._cancellations.labels(target=target).inc(amount)

    def record_publication_failure(self, *, amount: int = 1) -> None:
        self._publication_failures.inc(amount)

    def record_auth_denial(self, *, permission: str, amount: int = 1) -> None:
        self._auth_denials.labels(permission=permission).inc(amount)

    def record_duplicate_suppression(self, *, source: str, amount: int = 1) -> None:
        self._duplicate_suppressions.labels(source=source).inc(amount)

    def start_http_server(self, *, host: str, port: int) -> None:
        start_http_server(port=port, addr=host, registry=self.registry)


NO_OP_METRICS = NoOpAppMetrics()


def build_app_metrics(settings: MetricsSettings) -> AppMetrics:
    if not settings.enabled:
        return NO_OP_METRICS
    return PrometheusAppMetrics()


def maybe_start_metrics_http_server(
    metrics: AppMetrics,
    *,
    host: str,
    port: int,
    runtime: str,
) -> None:
    if isinstance(metrics, NoOpAppMetrics):
        return
    metrics.start_http_server(host=host, port=port)
    get_logger(__name__).info(
        "metrics.http_server_started",
        runtime=runtime,
        host=host,
        port=port,
    )
