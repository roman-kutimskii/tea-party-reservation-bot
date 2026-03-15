from __future__ import annotations

import io
import json
from collections.abc import Iterable
from typing import Any, cast

from tea_party_reservation_bot.metrics import (
    PrometheusAppMetrics,
    RuntimeStatus,
    build_operational_wsgi_app,
)


def _call_app(app: Any, path: str) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body = b"".join(cast(Iterable[bytes], app(environ, start_response)))
    return captured["status"], captured["headers"], body


def test_operational_wsgi_app_reports_live_and_not_ready_states() -> None:
    metrics = PrometheusAppMetrics()
    status = RuntimeStatus(runtime="bot")
    app = build_operational_wsgi_app(registry=metrics.registry, runtime_status=status)

    health_status, _health_headers, health_body = _call_app(app, "/healthz")
    ready_status, _ready_headers, ready_body = _call_app(app, "/readyz")

    assert health_status == "200 OK"
    assert json.loads(health_body) == {"status": "alive", "runtime": "bot"}
    assert ready_status == "503 Service Unavailable"
    assert json.loads(ready_body) == {
        "status": "not_ready",
        "runtime": "bot",
        "reason": "starting",
    }


def test_operational_wsgi_app_reports_ready_and_serves_metrics() -> None:
    metrics = PrometheusAppMetrics()
    metrics.record_registration()
    status = RuntimeStatus(runtime="worker")
    status.mark_ready()
    app = build_operational_wsgi_app(registry=metrics.registry, runtime_status=status)

    ready_status, _ready_headers, ready_body = _call_app(app, "/readyz")
    metrics_status, metrics_headers, metrics_body = _call_app(app, "/metrics")

    assert ready_status == "200 OK"
    assert json.loads(ready_body) == {
        "status": "ready",
        "runtime": "worker",
        "reason": "ready",
    }
    assert metrics_status == "200 OK"
    assert metrics_headers["Content-Type"].startswith("text/plain")
    assert b"tea_party_registrations_total" in metrics_body
