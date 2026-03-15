from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from socketserver import ThreadingMixIn
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from prometheus_client import CollectorRegistry, Counter, make_wsgi_app

from tea_party_reservation_bot.config.settings import MetricsSettings
from tea_party_reservation_bot.logging import get_logger


@dataclass(slots=True)
class RuntimeStatus:
    runtime: str
    ready: bool = False
    reason: str = "starting"

    def mark_ready(self) -> None:
        self.ready = True
        self.reason = "ready"

    def mark_not_ready(self, *, reason: str) -> None:
        self.ready = False
        self.reason = reason


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietRequestHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return None


def _json_response(
    start_response: Any,
    *,
    status: HTTPStatus,
    payload: dict[str, Any],
) -> list[bytes]:
    body = json.dumps(payload).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def build_operational_wsgi_app(
    *,
    registry: CollectorRegistry,
    runtime_status: RuntimeStatus,
) -> Any:
    metrics_app = make_wsgi_app(registry=registry)

    def app(environ: dict[str, Any], start_response: Any) -> Any:
        path = environ.get("PATH_INFO", "")
        if path == "/metrics":
            return metrics_app(environ, start_response)
        if path == "/healthz":
            return _json_response(
                start_response,
                status=HTTPStatus.OK,
                payload={
                    "status": "alive",
                    "runtime": runtime_status.runtime,
                },
            )
        if path == "/readyz":
            ready = runtime_status.ready
            return _json_response(
                start_response,
                status=HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                payload={
                    "status": "ready" if ready else "not_ready",
                    "runtime": runtime_status.runtime,
                    "reason": runtime_status.reason,
                },
            )
        return _json_response(
            start_response,
            status=HTTPStatus.NOT_FOUND,
            payload={"status": "not_found"},
        )

    return app


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

    def start_http_server(self, *, host: str, port: int, runtime_status: RuntimeStatus) -> None:
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

    def start_http_server(self, *, host: str, port: int, runtime_status: RuntimeStatus) -> None:
        app = build_operational_wsgi_app(registry=self.registry, runtime_status=runtime_status)
        server = make_server(
            host,
            port,
            app,
            server_class=_ThreadingWSGIServer,
            handler_class=_QuietRequestHandler,
        )
        thread = threading.Thread(
            target=server.serve_forever,
            name=f"{runtime_status.runtime}-metrics-http",
            daemon=True,
        )
        thread.start()


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
    runtime_status: RuntimeStatus,
) -> None:
    if isinstance(metrics, NoOpAppMetrics):
        return
    metrics.start_http_server(host=host, port=port, runtime_status=runtime_status)
    get_logger(__name__).info(
        "metrics.http_server_started",
        runtime=runtime,
        host=host,
        port=port,
    )
