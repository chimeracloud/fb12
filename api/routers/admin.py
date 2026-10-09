"""The seven admin endpoints of CHI-ADR-010."""

from __future__ import annotations

import asyncio
import logging
import platform
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from core.config import CONFIG, VERSION, Runtime
from core.credentials import credential_names, credential_state
from core.events import now_iso, sse
from core.logging import RING
from core.settings import MASK
from models.schemas import SettingsUpdate

logger = logging.getLogger("fb12.admin")
router = APIRouter(prefix="/admin", tags=["admin"])

STREAM_HEARTBEAT_SECONDS = 15


def _credential_email(request: Request) -> str:
    credential = getattr(request.state, "credential", None)
    return getattr(credential, "email", "unknown")


def health_snapshot(state: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": CONFIG.service_name,
        "unit": CONFIG.unit,
        "version": VERSION,
        "revision": Runtime.revision or None,
        "time": now_iso(),
        "uptime_seconds": state.metrics.uptime_seconds,
        "settings_source": state.store.source,
    }


def status_snapshot(state: Any) -> dict[str, Any]:
    metrics = state.metrics
    store = state.store
    verifier = state.verifier
    bus = state.bus
    racing = getattr(state, "racing_stats", None)
    return {
        "service": CONFIG.service_name,
        "unit": CONFIG.unit,
        "version": VERSION,
        "revision": Runtime.revision or None,
        "mode": "paper",
        "time": now_iso(),
        "started_at": datetime.fromtimestamp(metrics.started_at, UTC).isoformat(),
        "uptime_seconds": metrics.uptime_seconds,
        "requests": {
            "total": metrics.requests,
            "errors": metrics.errors,
            "error_rate": metrics.error_rate,
            "by_status": {str(k): v for k, v in sorted(metrics.status_counts.items())},
        },
        "access": {
            "accepted": dict(verifier.accepted),
            "rejected": verifier.rejected,
            "cloudflare_configured": CONFIG.access.cloudflare.configured,
            "operators": len(CONFIG.access.google.operators),
        },
        "settings": {
            "source": store.source,
            "updated_at": store.updated_at,
            "updated_by": store.updated_by,
            "last_error": store.last_error,
        },
        "credentials": {name: credential_state(name) for name in credential_names()},
        "racing_api": racing.snapshot() if racing is not None else None,
        "stream": {
            "subscribers": bus.subscriber_count,
            "events_published": bus.published,
            "events_dropped": bus.dropped,
        },
    }


@router.get("/health")
async def admin_health(request: Request) -> dict[str, Any]:
    return health_snapshot(request.app.state)


@router.get("/status")
async def admin_status(request: Request) -> dict[str, Any]:
    return status_snapshot(request.app.state)


@router.get("/settings")
async def admin_settings_get(request: Request) -> dict[str, Any]:
    store = request.app.state.store
    await store.load()  # ADR 010: read from Firestore on each GET
    return store.form()


@router.put("/settings")
async def admin_settings_put(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    applied, rejected = await store.update(body.values, by=_credential_email(request))
    return {"applied": applied, "rejected": rejected, "settings": store.form()}


@router.get("/config")
async def admin_config(request: Request) -> dict[str, Any]:
    return {
        "service": CONFIG.service_name,
        "unit": CONFIG.unit,
        "version": VERSION,
        "project": CONFIG.gcp_project,
        "region": CONFIG.region,
        "cloud_run": {
            "service": Runtime.service or None,
            "revision": Runtime.revision or None,
            "configuration": Runtime.configuration or None,
        },
        "python": platform.python_version(),
        "racing_api": {"base_url": CONFIG.racing_api.base_url},
        "paper_entries_bucket": CONFIG.paper_entries_bucket,
        "firestore": CONFIG.firestore.model_dump(),
        "access": {
            "iam": "allUsers may invoke; FB12 is the gate (POL-004 / POL-006 exception, Charles, 9 October 2026)",
            "cloudflare": {
                "team_domain": CONFIG.access.cloudflare.team_domain or None,
                "audience_tag": CONFIG.access.cloudflare.audience_tag or None,
                "configured": CONFIG.access.cloudflare.configured,
            },
            "google": {
                "operators": CONFIG.access.google.operators,
                "extra_audiences": CONFIG.access.google.extra_audiences,
                "audience_rule": "https://<host the request was sent to>, or one of extra_audiences",
            },
        },
        "credentials": {
            name: {"secret": secret_id, "value": MASK, "state": credential_state(name)}
            for name, secret_id in credential_names().items()
        },
        "config_file": "api/config/fb12.json",
        "pipeline": "push to main -> Cloud Build trigger (api/**) -> Dockerfile with a test stage -> Cloud Run",
    }


@router.get("/logs")
async def admin_logs(
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, ge=1, description="Only entries with seq below this value"),
    severity: str | None = Query(None, description="Exact severity to keep, e.g. WARNING"),
) -> dict[str, Any]:
    entries = RING.snapshot()
    entries.reverse()  # newest first
    if before is not None:
        entries = [e for e in entries if e.get("seq", 0) < before]
    if severity:
        entries = [e for e in entries if e.get("severity") == severity.upper()]
    page = entries[:limit]
    return {
        "entries": page,
        "count": len(page),
        "limit": limit,
        "newest_seq": page[0]["seq"] if page else None,
        "oldest_seq": page[-1]["seq"] if page else None,
        "next_before": page[-1]["seq"] if len(entries) > limit else None,
        "buffer_size": RING.entries.maxlen,
    }


async def event_stream(state: Any) -> AsyncIterator[str]:
    bus = state.bus
    queue = bus.subscribe()
    try:
        yield sse("hello", {"event": "hello", "time": now_iso(), "data": status_snapshot(state)})
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=STREAM_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield sse("status", {"event": "status", "time": now_iso(), "data": status_snapshot(state)})
                continue
            event_id = payload["data"].get("seq") if payload["event"] == "log" else None
            yield sse(payload["event"], payload, event_id)
    finally:
        bus.unsubscribe(queue)


@router.get("/stream")
async def admin_stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        event_stream(request.app.state),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
