"""Structured JSON logging with a ring buffer for /admin/logs and the live stream.

Every entry carries service_name, trace_id, timestamp and severity. No print
statements anywhere in FB12. Credential values are never logged: the only
places that touch them (core/credentials.py, services/racing_api.py) log names
and versions only.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.config import CONFIG

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

LogListener = Callable[[dict[str, Any]], None]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "service_name": CONFIG.service_name,
            "trace_id": trace_id_var.get(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace = trace_id_var.get()
        if trace:
            entry["logging.googleapis.com/trace"] = f"projects/{CONFIG.gcp_project}/traces/{trace}"
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class RingBufferHandler(logging.Handler):
    """Keeps the most recent entries in memory and tells listeners about each one."""

    def __init__(self, capacity: int = 1000) -> None:
        super().__init__()
        self.entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self.seq = 0
        self._lock = threading.Lock()
        self._listeners: list[LogListener] = []

    def add_listener(self, listener: LogListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: LogListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = json.loads(self.format(record))
        except Exception:  # noqa: BLE001 - a logging failure must never raise
            return
        with self._lock:
            self.seq += 1
            payload["seq"] = self.seq
            self.entries.append(payload)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(payload)
            except Exception:  # noqa: BLE001
                pass

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.entries)


RING = RingBufferHandler()
_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    formatter = JsonFormatter()
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    RING.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stdout, RING]
    root.setLevel(level)

    # uvicorn writes plain text; route its loggers through the JSON handlers and
    # drop its access log, since the request middleware writes a richer one.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    _configured = True


def log(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"fields": fields})
