"""The Racing API client.

HTTP Basic Auth with the username and password from the credential module.
FB12's own throttle (requests per second from settings; the account allows 5
and may be shared with the Racing API FSUs), back-off and retry on 429, a TTL
cache per endpoint kind with lifetimes from settings, and counters for
/admin/status. Any upstream failure becomes the contract's error envelope with
the Racing API's status and detail in the message. Nothing is invented: if The
Racing API fails, its error is returned.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from core.config import CONFIG
from core.credentials import CredentialError, get_credential
from core.errors import ApiError
from core.logging import log

logger = logging.getLogger("fb12.racing_api")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RacingApiStats:
    calls: int = 0
    errors: int = 0
    retries_429: int = 0
    throttle_waits: int = 0
    cache_hits: int = 0
    last_call_at: str | None = None
    last_status: int | None = None
    last_path: str | None = None
    last_error: str | None = None
    cache_entries: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "base_url": CONFIG.racing_api.base_url,
            "calls": self.calls,
            "errors": self.errors,
            "retries_429": self.retries_429,
            "throttle_waits": self.throttle_waits,
            "cache_hits": self.cache_hits,
            "cache_entries": self.cache_entries,
            "last_call_at": self.last_call_at,
            "last_status": self.last_status,
            "last_path": self.last_path,
            "last_error": self.last_error,
        }


@dataclass
class CacheEntry:
    value: Any
    fetched_at: str
    expires_at: float


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _upstream_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message") or body.get("error")
        if detail:
            return str(detail)[:300]
    return str(body)[:200]


class RacingApiClient:
    def __init__(self, settings_store: Any, *, transport: httpx.AsyncBaseTransport | None = None,
                 base_url: str | None = None) -> None:
        self.settings = settings_store
        self.stats = RacingApiStats()
        self.base_url = base_url or CONFIG.racing_api.base_url
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._auth: tuple[str, str] | None = None
        self._throttle_lock = asyncio.Lock()
        self._next_slot = 0.0
        self._cache: dict[str, CacheEntry] = {}
        self._key_locks: dict[str, asyncio.Lock] = {}

    # --- plumbing -----------------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(25.0, connect=10.0),
                transport=self._transport,
                headers={"User-Agent": f"{CONFIG.service_name}/{CONFIG.unit}"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _basic_auth(self) -> tuple[str, str]:
        if self._auth is None:
            try:
                username = await asyncio.to_thread(get_credential, "racing_api_username")
                password = await asyncio.to_thread(get_credential, "racing_api_password")
            except CredentialError as exc:
                self.stats.errors += 1
                self.stats.last_error = str(exc)
                raise ApiError(502, "UPSTREAM_ERROR", f"FB12 could not read its Racing API credentials: {exc}") from exc
            self._auth = (username, password)
        return self._auth

    def forget_credentials(self) -> None:
        self._auth = None

    async def _throttle(self) -> None:
        rate = float(self.settings.get("request_rate_per_second") or 3.0)
        interval = 1.0 / rate
        async with self._throttle_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            if wait > 0:
                self.stats.throttle_waits += 1
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_slot = max(now, self._next_slot) + interval

    def _prune_cache(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._cache.items() if v.expires_at <= now]:
            self._cache.pop(key, None)
            self._key_locks.pop(key, None)
        self.stats.cache_entries = len(self._cache)

    def clear_cache(self) -> None:
        self._cache.clear()
        self._key_locks.clear()
        self.stats.cache_entries = 0

    # --- the one public call -------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None, *, cache_kind: str | None,
                  describe: str) -> tuple[Any, str]:
        """GET a Racing API path. Returns (json, fetched_at). cache_kind picks the
        cache_<kind>_seconds setting; None means never cached."""
        key = path + ("?" + urlencode(sorted(params.items()), doseq=True) if params else "")
        ttl = int(self.settings.get(f"cache_{cache_kind}_seconds")) if cache_kind else 0
        if ttl > 0:
            hit = self._cache.get(key)
            if hit is not None and hit.expires_at > time.monotonic():
                self.stats.cache_hits += 1
                return hit.value, hit.fetched_at
        lock = self._key_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if ttl > 0:
                hit = self._cache.get(key)
                if hit is not None and hit.expires_at > time.monotonic():
                    self.stats.cache_hits += 1
                    return hit.value, hit.fetched_at
            data, fetched_at = await self._fetch(path, params, describe)
            if ttl > 0:
                self._cache[key] = CacheEntry(data, fetched_at, time.monotonic() + ttl)
                self._prune_cache()
            return data, fetched_at

    async def _fetch(self, path: str, params: dict[str, Any] | None, describe: str) -> tuple[Any, str]:
        client = self._ensure_client()
        auth = await self._basic_auth()
        max_retries = int(self.settings.get("retry_on_429_max"))
        attempt = 0
        while True:
            await self._throttle()
            self.stats.calls += 1
            self.stats.last_path = path
            self.stats.last_call_at = now_iso()
            started = time.perf_counter()
            try:
                response = await client.get(path, params=params, auth=auth)
            except httpx.HTTPError as exc:
                self.stats.errors += 1
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
                log(logger, logging.ERROR, "racing api unreachable", path=path, error=self.stats.last_error)
                raise ApiError(
                    502, "UPSTREAM_ERROR",
                    f"The Racing API did not answer for {describe}: {type(exc).__name__}: {exc}",
                ) from exc
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            self.stats.last_status = response.status_code
            log(logger, logging.INFO, "racing api call", path=path, status=response.status_code,
                duration_ms=duration_ms, attempt=attempt)
            if response.status_code == 429 and attempt < max_retries:
                attempt += 1
                self.stats.retries_429 += 1
                delay = _retry_after_seconds(response)
                if delay is None:
                    delay = min(float(2 ** attempt), 10.0)
                log(logger, logging.WARNING, "racing api 429, backing off", path=path, delay_seconds=delay, attempt=attempt)
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 400:
                self.stats.errors += 1
                error = self._error(response, describe, attempt)
                self.stats.last_error = error.message
                raise error
            try:
                data = response.json()
            except ValueError as exc:
                self.stats.errors += 1
                self.stats.last_error = "non-JSON response"
                raise ApiError(
                    502, "UPSTREAM_ERROR",
                    f"The Racing API returned something that is not JSON for {describe} (HTTP {response.status_code}).",
                    response.status_code,
                ) from exc
            return data, now_iso()

    @staticmethod
    def _error(response: httpx.Response, describe: str, retries: int) -> ApiError:
        status = response.status_code
        detail = _upstream_detail(response)
        if status == 404:
            return ApiError(404, "NOT_FOUND", f"The Racing API has no {describe}: {detail or 'not found'}.", 404)
        if status in (401, 403):
            return ApiError(502, "UPSTREAM_ERROR",
                            f"The Racing API refused FB12's credentials for {describe} (HTTP {status}): {detail}", status)
        if status == 429:
            return ApiError(503, "UPSTREAM_ERROR",
                            f"The Racing API is rate limiting FB12 for {describe}; retried {retries} times. Try again in a moment.",
                            429)
        return ApiError(502, "UPSTREAM_ERROR", f"The Racing API failed for {describe} (HTTP {status}): {detail}", status)
