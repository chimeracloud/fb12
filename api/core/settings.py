"""Admin settings (ADR 010): field definitions, validation, Firestore persistence.

GET /admin/settings returns the form definition with current values so the GUI
renders it generically. PUT validates each value, persists the whole set to
Firestore (collection fsu-admin-settings, document fb12) and answers with the
applied and rejected lists. Values are applied in memory only after the write
succeeds, so memory never drifts from storage. Credentials appear masked and
cannot be written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from core.config import CONFIG, Fb12Config
from core.credentials import credential_names, credential_state
from core.errors import ApiError
from core.logging import log

logger = logging.getLogger("fb12.settings")

MASK = "••••••••"


@dataclass(frozen=True)
class FieldDef:
    key: str
    group: str
    label: str
    type: str  # number | integer | boolean | string | list | secret
    default: Any
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    writable: bool = True
    secret_ref: str | None = None  # logical credential name for type == secret


GROUPS: list[tuple[str, str]] = [
    ("dutch", "Dutch defaults"),
    ("racing", "Racing API"),
    ("cache", "Cache lifetimes (seconds)"),
    ("pace", "Pace keyword lists (matched in this order, first match wins)"),
    ("recorder", "Recorder"),
    ("credentials", "Credentials (read only)"),
]

PACE_LED = [
    "made the running", "made all", "set the pace", "went straight to front",
    "led early", "clear early", "went forward from the break",
]
PACE_PROMINENT = [
    "raced handy", "prominent", "up with the pace", "close up", "tracked the pace",
    "tracked front group", "sat close",
]
PACE_HELD_UP = ["held up", "towards the back", "at the rear", "at rear", "in rear", "off the pace"]
PACE_MIDFIELD = ["midfield", "mid division", "in the pack"]

FIELDS: list[FieldDef] = [
    FieldDef("commission_rate", "dutch", "Commission rate", "number", 0.02,
             "Betfair commission on net market winnings, as a fraction (0.02 = 2%).", 0, 1, 0.001),
    FieldDef("default_stake", "dutch", "Default total stake (£)", "number", 100.0,
             "Total stake the GUI starts with.", 0.01, 1_000_000, 1),
    FieldDef("default_part_fraction", "dutch", "Default PART fraction", "number", 0.5,
             "Share of the total stake a PART runner returns if it wins.", 0, 1, 0.05),
    FieldDef("past_runs", "racing", "Past runs per runner", "integer", 5,
             "How many previous runs the pace endpoint reads by default.", 1, 50, 1),
    FieldDef("regions", "racing", "Regions", "list", ["gb", "ire"],
             "Racing API region codes for the race list."),
    FieldDef("request_rate_per_second", "racing", "Racing API requests per second", "number", 3.0,
             "FB12's own ceiling; the account allows 5 and may be shared.", 0.1, 5, 0.1),
    FieldDef("retry_on_429_max", "racing", "Retries on 429", "integer", 3,
             "How many times a throttled Racing API call is retried with backoff.", 0, 10, 1),
    FieldDef("cache_race_list_seconds", "cache", "Race list", "integer", 300, "", 0, 86400, 1),
    FieldDef("cache_race_card_seconds", "cache", "Race card", "integer", 60, "", 0, 86400, 1),
    FieldDef("cache_odds_seconds", "cache", "Odds history", "integer", 60, "", 0, 86400, 1),
    FieldDef("cache_past_runs_seconds", "cache", "Past runs", "integer", 86400, "", 0, 604800, 1),
    FieldDef("pace_led", "pace", "LED", "list", PACE_LED),
    FieldDef("pace_prominent", "pace", "PROMINENT", "list", PACE_PROMINENT),
    FieldDef("pace_held_up", "pace", "HELD_UP", "list", PACE_HELD_UP),
    FieldDef("pace_midfield", "pace", "MIDFIELD", "list", PACE_MIDFIELD),
    FieldDef("cards_history_from", "recorder", "Racecards available from", "string", "2023-01-23",
             "The Racing API's documented start of historical racecards. Nothing earlier is requested."),
    FieldDef("odds_history_from", "recorder", "Odds history available from", "string", "2025-03-17",
             "The Racing API's documented start of price movements. Nothing earlier is requested."),
    FieldDef("results_history_days", "recorder", "Results history (days)", "integer", 365,
             "How far back results go on this plan (12 months without the historical add-on).", 1, 10000, 1),
    FieldDef("backfill_earliest_date", "recorder", "Backfill stops at", "string", "2023-01-23",
             "The oldest day the backfill will try."),
    FieldDef("backfill_window_start_hour", "recorder", "Backfill window start (UK hour)", "integer", 0, "", 0, 23, 1),
    FieldDef("backfill_window_end_hour", "recorder", "Backfill window end (UK hour)", "integer", 6, "", 0, 24, 1),
    FieldDef("recorder_retry_days", "recorder", "Daily run retries incomplete days within (days)", "integer", 10, "", 1, 60, 1),
    FieldDef("recorder_max_attempts", "recorder", "Backfill attempts per day before giving up", "integer", 3, "", 1, 20, 1),
    FieldDef("recorder_results_page_size", "recorder", "Results page size", "integer", 100, "The API allows up to 100.", 1, 100, 1),
    FieldDef("racing_api_username", "credentials", "Racing API username", "secret", None,
             "Read from Secret Manager by the credential module. Never shown, never writable here.",
             writable=False, secret_ref="racing_api_username"),
    FieldDef("racing_api_password", "credentials", "Racing API password", "secret", None,
             "Read from Secret Manager by the credential module. Never shown, never writable here.",
             writable=False, secret_ref="racing_api_password"),
]
FIELD_INDEX: dict[str, FieldDef] = {f.key: f for f in FIELDS}


def coerce(fd: FieldDef, value: Any) -> Any:
    """Validate and normalise one value, or raise ValueError with a readable reason."""
    if fd.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        value = float(value)
    elif fd.type == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError("must be a whole number")
        value = int(value)
    elif fd.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
    elif fd.type == "string":
        if not isinstance(value, str):
            raise ValueError("must be text")
        value = value.strip()
    elif fd.type == "list":
        if isinstance(value, str):
            value = [p for p in (s.strip() for s in value.replace("\n", ",").split(",")) if p]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("must be a list of text values")
        value = [v.strip() for v in value if v.strip()]
        if not value:
            raise ValueError("must not be empty")
    else:
        raise ValueError("is read only")
    if fd.minimum is not None and isinstance(value, (int, float)) and value < fd.minimum:
        raise ValueError(f"must be at least {fd.minimum}")
    if fd.maximum is not None and isinstance(value, (int, float)) and value > fd.maximum:
        raise ValueError(f"must be at most {fd.maximum}")
    return value


class SettingsBackend(Protocol):
    name: str

    async def read(self) -> dict[str, Any] | None: ...

    async def write(self, document: dict[str, Any]) -> None: ...


class MemoryBackend:
    """In-process persistence, used by the test suite. Not for deployment."""

    name = "memory"

    def __init__(self) -> None:
        self.document: dict[str, Any] | None = None

    async def read(self) -> dict[str, Any] | None:
        return dict(self.document) if self.document is not None else None

    async def write(self, document: dict[str, Any]) -> None:
        self.document = dict(document)


class FirestoreBackend:
    name = "firestore"

    def __init__(self, project: str, database: str, collection: str, document: str) -> None:
        self.project = project
        self.database = database
        self.collection = collection
        self.document = document
        self._client = None

    @classmethod
    def from_config(cls, config: Fb12Config = CONFIG) -> FirestoreBackend:
        return cls(config.gcp_project, config.firestore.database, config.firestore.collection, config.firestore.document)

    @property
    def path(self) -> str:
        return f"{self.collection}/{self.document}"

    def _ref(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(project=self.project, database=self.database)
        return self._client.document(self.path)

    async def read(self) -> dict[str, Any] | None:
        snapshot = await self._ref().get()
        return snapshot.to_dict() if snapshot.exists else None

    async def write(self, document: dict[str, Any]) -> None:
        await self._ref().set(document, merge=True)


class SettingsStore:
    def __init__(self, backend: SettingsBackend) -> None:
        self.backend = backend
        self.values: dict[str, Any] = {f.key: f.default for f in FIELDS if f.type != "secret"}
        self.source = "defaults"
        self.updated_at: str | None = None
        self.updated_by: str | None = None
        self.last_error: str | None = None
        self.last_loaded_at: str | None = None
        self.on_change = None  # callable(list[str]) set by the app

    def get(self, key: str) -> Any:
        return self.values[key]

    async def load(self) -> bool:
        try:
            document = await self.backend.read()
        except Exception as exc:  # noqa: BLE001 - the service must start without Firestore
            self.last_error = f"{type(exc).__name__}: {exc}"
            log(logger, logging.WARNING, "settings load failed, running on defaults", backend=self.backend.name, error=self.last_error)
            return False
        self.last_error = None
        self.last_loaded_at = datetime.now(UTC).isoformat()
        if not document:
            self.source = f"defaults (nothing stored in {self.backend.name} yet)"
            return True
        stored = document.get("values") or {}
        for fd in FIELDS:
            if not fd.writable or fd.key not in stored:
                continue
            try:
                self.values[fd.key] = coerce(fd, stored[fd.key])
            except ValueError as exc:
                log(logger, logging.WARNING, "stored setting ignored", key=fd.key, reason=str(exc))
        self.source = self.backend.name
        self.updated_at = document.get("updated_at")
        self.updated_by = document.get("updated_by")
        return True

    async def update(self, values: dict[str, Any], by: str) -> tuple[list[str], list[dict[str, str]]]:
        applied: dict[str, Any] = {}
        rejected: list[dict[str, str]] = []
        for key, value in values.items():
            fd = FIELD_INDEX.get(key)
            if fd is None:
                rejected.append({"key": key, "reason": "unknown setting"})
            elif not fd.writable:
                rejected.append({"key": key, "reason": "read only"})
            else:
                try:
                    applied[key] = coerce(fd, value)
                except ValueError as exc:
                    rejected.append({"key": key, "reason": str(exc)})
        if applied:
            new_values = {**self.values, **applied}
            now = datetime.now(UTC).isoformat()
            document = {
                "unit": CONFIG.unit,
                "service": CONFIG.service_name,
                "values": new_values,
                "updated_at": now,
                "updated_by": by,
            }
            try:
                await self.backend.write(document)
            except Exception as exc:  # noqa: BLE001
                raise ApiError(
                    502,
                    "UPSTREAM_ERROR",
                    f"Settings were not saved: the {self.backend.name} write failed ({type(exc).__name__}: {exc}). Nothing changed.",
                ) from exc
            self.values = new_values
            self.source = self.backend.name
            self.updated_at = now
            self.updated_by = by
            log(logger, logging.INFO, "settings updated", keys=sorted(applied), updated_by=by)
            if self.on_change is not None:
                self.on_change(sorted(applied))
        return sorted(applied), rejected

    def form(self) -> dict[str, Any]:
        groups = []
        for group_id, label in GROUPS:
            fields = []
            for fd in FIELDS:
                if fd.group != group_id:
                    continue
                if fd.type == "secret":
                    fields.append({
                        "key": fd.key,
                        "label": fd.label,
                        "type": "secret",
                        "value": MASK,
                        "writable": False,
                        "help": fd.help,
                        "secret": credential_names().get(fd.secret_ref or "", None),
                        "state": credential_state(fd.secret_ref or ""),
                    })
                    continue
                fields.append({
                    "key": fd.key,
                    "label": fd.label,
                    "type": fd.type,
                    "value": self.values[fd.key],
                    "default": fd.default,
                    "writable": fd.writable,
                    "help": fd.help,
                    "min": fd.minimum,
                    "max": fd.maximum,
                    "step": fd.step,
                })
            groups.append({"id": group_id, "label": label, "fields": fields})
        return {
            "service": CONFIG.service_name,
            "unit": CONFIG.unit,
            "storage": {"backend": self.backend.name, "path": getattr(self.backend, "path", None)},
            "source": self.source,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "last_loaded_at": self.last_loaded_at,
            "last_error": self.last_error,
            "groups": groups,
        }
