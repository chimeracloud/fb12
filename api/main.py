"""FB12 Dutch API: FastAPI application factory and the deployed app object."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.logging import RING, configure_logging, log

configure_logging()

from core.auth import AccessGate, Verifier  # noqa: E402
from core.config import CONFIG, VERSION, Runtime  # noqa: E402
from core.errors import install_error_handlers  # noqa: E402
from core.events import EventBus  # noqa: E402
from core.middleware import Metrics, RequestContext  # noqa: E402
from core.settings import FirestoreBackend, SettingsBackend, SettingsStore  # noqa: E402
from core.storage import GcsStore, ObjectStore  # noqa: E402
from routers import admin, api  # noqa: E402
from services.racing_api import RacingApiClient  # noqa: E402
from services.recorder import Recorder  # noqa: E402

logger = logging.getLogger("fb12.main")


def create_app(settings_backend: SettingsBackend | None = None,
               recordings_store: ObjectStore | None = None) -> FastAPI:
    metrics = Metrics()
    bus = EventBus()
    verifier = Verifier(CONFIG)
    store = SettingsStore(settings_backend or FirestoreBackend.from_config(CONFIG))
    store.on_change = lambda keys: bus.publish("settings", {"keys": keys, "updated_by": store.updated_by, "updated_at": store.updated_at})
    racing = RacingApiClient(store)
    recorder = Recorder(racing, recordings_store or GcsStore(CONFIG.recordings_bucket), store, bus)

    def forward_log(entry: dict) -> None:
        bus.publish("log", entry)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        RING.add_listener(forward_log)
        await store.load()
        try:
            await recorder._ensure_loaded()
        except Exception as exc:  # noqa: BLE001 - the service starts even if the bucket is unreachable
            log(logger, logging.WARNING, "recorder index not loaded at startup", error=f"{type(exc).__name__}: {exc}")
        log(logger, logging.INFO, "fb12 started", version=VERSION, revision=Runtime.revision or None,
            settings_source=store.source, cloudflare_configured=CONFIG.access.cloudflare.configured,
            operators=len(CONFIG.access.google.operators))
        try:
            yield
        finally:
            await racing.aclose()
            RING.remove_listener(forward_log)
            log(logger, logging.INFO, "fb12 stopping")

    app = FastAPI(
        title="FB12 Dutch API",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.metrics = metrics
    app.state.bus = bus
    app.state.verifier = verifier
    app.state.store = store
    app.state.racing = racing
    app.state.racing_stats = racing.stats
    app.state.recorder = recorder

    install_error_handlers(app)
    app.include_router(admin.router)
    app.include_router(api.router)

    # Last added is outermost: RequestContext wraps AccessGate wraps the app.
    app.add_middleware(AccessGate, verifier=verifier)
    app.add_middleware(RequestContext, metrics=metrics)
    return app


app = create_app()
