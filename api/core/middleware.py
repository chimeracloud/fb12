"""Request context: trace id, timing, counters and one JSON log line per request."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.logging import log, trace_id_var

logger = logging.getLogger("fb12.request")


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    requests: int = 0
    errors: int = 0
    status_counts: dict[int, int] = field(default_factory=dict)

    def record(self, status: int) -> None:
        self.requests += 1
        if status >= 500:
            self.errors += 1
        self.status_counts[status] = self.status_counts.get(status, 0) + 1

    @property
    def error_rate(self) -> float:
        return round(self.errors / self.requests, 4) if self.requests else 0.0

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)


def trace_from_header(value: str) -> str:
    # X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=TRACE_TRUE
    return value.split("/", 1)[0].strip() if value else ""


class RequestContext:
    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        trace = trace_from_header(headers.get("x-cloud-trace-context", "")) or uuid.uuid4().hex
        token = trace_id_var.set(trace)
        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            status = status_holder["status"] or 500
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            self.metrics.record(status)
            credential = scope.get("state", {}).get("credential")
            log(
                logger,
                logging.INFO if status < 500 else logging.ERROR,
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status,
                duration_ms=duration_ms,
                auth_method=getattr(credential, "method", None),
                auth_email=getattr(credential, "email", None),
            )
            trace_id_var.reset(token)
