"""The recorder. FB12 owns its history so every decision can be replayed and scored.

Each run records one day for the configured regions: the pro racecards for the
day, the results for the day (every page), and the odds history of every runner
on the card. Every response is stored raw and untouched (gzip) in the recordings
bucket, one object per response, plus a manifest per day with counts,
completeness and fetch times. A day is complete only when every result carries
BSP; incomplete days are retried on later runs. GUI calls go first: recorder
calls are background calls that wait their turn within the same 3-a-second budget.

Modes of POST /api/record?date=
  YYYY-MM-DD  that day, any time
  yesterday   yesterday (UK) plus a retry of incomplete days in the retry window
  backfill    the newest day not yet complete, newest first, inside the night window

What the plan gives (The Racing API documentation, 9 October 2026): historical
racecards from 2023-01-23, results for the last 12 months, odds history from
2025-03-17. Those are the recorder's settings and it asks for nothing outside them.

Layout in the bucket:
  cards/{date}.json.gz                    GET /racecards/pro?date=&region_codes=
  results/{date}/page-NN.json.gz          GET /results?start_date=&end_date=&region=&limit=&skip=
  odds/{date}/{race_id}/{horse_id}.json.gz GET /odds/{race_id}/{horse_id}
  manifest/{date}.json                    counts, completeness, fetch times, errors
  manifest/_index.json                    per-day summary for fast skipping
  manifest/_state.json                    availability boundaries learned from the API
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from core.errors import ApiError
from core.events import now_iso
from core.logging import log
from core.storage import ObjectStore, get_json, put_json, put_raw_gzip
from services.racing_api import Fetched, RacingApiClient

logger = logging.getLogger("fb12.recorder")

UK = ZoneInfo("Europe/London")
INDEX_KEY = "manifest/_index.json"
STATE_KEY = "manifest/_state.json"
CONSECUTIVE_FAILURES_TO_ABORT = 10
UNAVAILABLE_STATUSES = {400, 403, 404, 422}


def manifest_key(day: date) -> str:
    return f"manifest/{day.isoformat()}.json"


def cards_key(day: date) -> str:
    return f"cards/{day.isoformat()}.json.gz"


def results_key(day: date, page: int) -> str:
    return f"results/{day.isoformat()}/page-{page:02d}.json.gz"


def odds_key(day: date, race_id: str, horse_id: str) -> str:
    return f"odds/{day.isoformat()}/{race_id}/{horse_id}.json.gz"


def parse_mode(value: str | None) -> tuple[str, date | None]:
    text = (value or "").strip().lower()
    if text in ("", "backfill"):
        return "backfill", None
    if text == "yesterday":
        return "yesterday", None
    try:
        return "day", date.fromisoformat(text)
    except ValueError:
        raise ApiError(400, "INVALID_INPUT", f"date must be YYYY-MM-DD, 'yesterday' or 'backfill', not {value!r}.") from None


def count_bsp(pages: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(races, runners, runners with a BSP) across result pages."""
    races = runners = with_bsp = 0
    for page in pages:
        for race in page.get("results") or []:
            races += 1
            for runner in race.get("runners") or []:
                runners += 1
                if str(runner.get("bsp") or "").strip() not in ("", "-"):
                    with_bsp += 1
    return races, runners, with_bsp


def runners_from_cards(cards: dict[str, Any] | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for race in (cards or {}).get("racecards") or []:
        race_id = race.get("race_id")
        for runner in race.get("runners") or []:
            horse_id = runner.get("horse_id")
            if race_id and horse_id:
                pairs.append((race_id, horse_id))
    return pairs


def new_manifest(day: date, regions: list[str]) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "regions": regions,
        "attempts": 0,
        "complete": False,
        "runs": [],
        "cards": {"status": "pending"},
        "results": {"status": "pending"},
        "odds": {"status": "pending", "done": [], "missing": [], "failed": []},
    }


class Recorder:
    def __init__(self, racing: RacingApiClient, store: ObjectStore, settings: Any, bus: Any = None) -> None:
        self.racing = racing
        self.store = store
        self.settings = settings
        self.bus = bus
        self._lock = asyncio.Lock()
        self._loaded = False
        self.index: dict[str, dict[str, Any]] = {}
        self.state: dict[str, Any] = {}
        self.current: dict[str, Any] | None = None
        self.last_run: dict[str, Any] | None = None

    # --- settings -------------------------------------------------------------

    def _regions(self) -> list[str]:
        return [str(r).lower() for r in self.settings.get("regions")]

    def _date_setting(self, key: str) -> date:
        return date.fromisoformat(str(self.settings.get(key)))

    def today_uk(self) -> date:
        return datetime.now(UK).date()

    def in_backfill_window(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UK)
        start = int(self.settings.get("backfill_window_start_hour"))
        end = int(self.settings.get("backfill_window_end_hour"))
        hour = now.astimezone(UK).hour
        return start <= hour < end if start < end else (hour >= start or hour < end)

    # --- persistence of index and state -----------------------------------------

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            index = await get_json(self.store, INDEX_KEY)
            if index is None:
                # First run, or the index is gone: rebuild from the manifests that exist.
                keys = await self.store.list_keys("manifest/")
                days: dict[str, dict[str, Any]] = {}
                for key in keys:
                    name = key.rsplit("/", 1)[-1]
                    if not name.endswith(".json") or name.startswith("_"):
                        continue
                    manifest = await get_json(self.store, key)
                    if manifest:
                        days[manifest["date"]] = self._index_entry(manifest)
                self.index = days
                if keys:
                    await self._save_index()
            else:
                self.index = index.get("days", {})
            self.state = (await get_json(self.store, STATE_KEY)) or {}
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001 - a missing or unreadable bucket is reported, not hidden
            raise ApiError(
                502, "UPSTREAM_ERROR",
                f"The recorder cannot use its bucket gs://{self.store.bucket} ({type(exc).__name__}: {exc}). "
                "Nothing was recorded. The bucket must exist and fb12-sa must hold objectAdmin on it.",
            ) from exc
        self._loaded = True

    @staticmethod
    def _index_entry(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "complete": bool(manifest.get("complete")),
            "attempts": int(manifest.get("attempts", 0)),
            "updated_at": manifest.get("finished_at"),
            "calls": manifest.get("calls"),
        }

    async def _save_index(self) -> None:
        await put_json(self.store, INDEX_KEY, {"updated_at": now_iso(), "days": self.index})

    async def _save_state(self) -> None:
        self.state["updated_at"] = now_iso()
        await put_json(self.store, STATE_KEY, self.state)

    # --- status --------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        complete = sorted(d for d, e in self.index.items() if e.get("complete"))
        incomplete = sorted(d for d, e in self.index.items() if not e.get("complete"))
        current = None
        if self.current:
            current = dict(self.current)
            current["calls_so_far"] = self.racing.stats.calls - current.pop("calls_at_start", 0)
        return {
            "bucket": self.store.bucket,
            "running": self.current is not None,
            "current": current,
            "last_run": self.last_run,
            "days_complete": len(complete),
            "days_incomplete": len(incomplete),
            "oldest_complete": complete[0] if complete else None,
            "newest_complete": complete[-1] if complete else None,
            "incomplete_days": incomplete[-20:],
            "availability": {
                "cards_from": str(self.settings.get("cards_history_from")),
                "odds_from": str(self.settings.get("odds_history_from")),
                "results_last_days": int(self.settings.get("results_history_days")),
                "learned": {k: v for k, v in self.state.items() if k != "updated_at"},
            },
            "backfill_window_uk": f"{int(self.settings.get('backfill_window_start_hour')):02d}:00-{int(self.settings.get('backfill_window_end_hour')):02d}:00",
            "loaded": self._loaded,
        }

    def _publish(self, phase: str, **extra: Any) -> None:
        if self.current is not None:
            self.current["phase"] = phase
            self.current.update(extra)
        if self.bus is not None:
            payload = {"phase": phase, **extra}
            if self.current:
                payload["date"] = self.current.get("date")
            self.bus.publish("recorder", payload)

    # --- entry point ----------------------------------------------------------

    async def record(self, mode: str, day: date | None, by: str) -> dict[str, Any]:
        if self._lock.locked():
            current = self.current or {}
            raise ApiError(
                409, "RECORDER_BUSY",
                f"A recording run is already in progress ({current.get('mode')} {current.get('date')}, "
                f"started {current.get('started_at')}). Try again when it finishes.",
            )
        async with self._lock:
            await self._ensure_loaded()
            today = self.today_uk()
            if mode == "day":
                assert day is not None
                if day >= today:
                    raise ApiError(400, "INVALID_INPUT", f"{day.isoformat()} is not over yet in UK time; the recorder records finished days.")
                manifest = await self._record_day(day, mode, by)
                return self._response(mode, manifest)
            if mode == "yesterday":
                yesterday = today - timedelta(days=1)
                manifest = await self._record_day(yesterday, mode, by)
                retried: list[dict[str, Any]] = []
                window = int(self.settings.get("recorder_retry_days"))
                for back in range(2, window + 1):
                    candidate = today - timedelta(days=back)
                    entry = self.index.get(candidate.isoformat())
                    if entry is None or entry.get("complete"):
                        continue
                    retried.append(self._summary(await self._record_day(candidate, "retry", by)))
                response = self._response(mode, manifest)
                response["retried"] = retried
                return response
            # backfill
            if not self.in_backfill_window():
                return {
                    "mode": mode, "skipped": True, "date": None,
                    "reason": f"outside the backfill window {self.snapshot()['backfill_window_uk']} UK; nothing recorded.",
                }
            target = self._pick_backfill_day(today)
            if target is None:
                return {
                    "mode": mode, "skipped": True, "date": None,
                    "reason": f"backfill complete: every day from {self.settings.get('backfill_earliest_date')} to yesterday is recorded or has used its attempts.",
                }
            manifest = await self._record_day(target, mode, by)
            response = self._response(mode, manifest)
            response["remaining_estimate"] = self._remaining_estimate(today)
            return response

    def _pick_backfill_day(self, today: date) -> date | None:
        earliest = self._date_setting("backfill_earliest_date")
        max_attempts = int(self.settings.get("recorder_max_attempts"))
        day = today - timedelta(days=1)
        while day >= earliest:
            entry = self.index.get(day.isoformat())
            if entry is None:
                return day
            if not entry.get("complete") and int(entry.get("attempts", 0)) < max_attempts:
                return day
            day -= timedelta(days=1)
        return None

    def _remaining_estimate(self, today: date) -> int:
        earliest = self._date_setting("backfill_earliest_date")
        max_attempts = int(self.settings.get("recorder_max_attempts"))
        remaining = 0
        day = today - timedelta(days=1)
        while day >= earliest:
            entry = self.index.get(day.isoformat())
            if entry is None or (not entry.get("complete") and int(entry.get("attempts", 0)) < max_attempts):
                remaining += 1
            day -= timedelta(days=1)
        return remaining

    @staticmethod
    def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": manifest["date"],
            "complete": manifest["complete"],
            "attempts": manifest["attempts"],
            "calls": manifest.get("calls"),
            "duration_seconds": manifest.get("duration_seconds"),
            "cards": manifest["cards"].get("status"),
            "results": manifest["results"].get("status"),
            "odds": manifest["odds"].get("status"),
            "errors": manifest.get("errors", []),
        }

    def _response(self, mode: str, manifest: dict[str, Any]) -> dict[str, Any]:
        response = {"mode": mode, "skipped": manifest.get("skipped", False), **self._summary(manifest)}
        response["manifest"] = manifest_key(date.fromisoformat(manifest["date"]))
        response["counts"] = {
            "cards_races": manifest["cards"].get("races"),
            "cards_runners": manifest["cards"].get("runners"),
            "results_races": manifest["results"].get("races"),
            "results_runners": manifest["results"].get("runners"),
            "results_with_bsp": manifest["results"].get("runners_with_bsp"),
            "odds_expected": manifest["odds"].get("expected"),
            "odds_done": len(manifest["odds"].get("done", [])),
            "odds_missing": len(manifest["odds"].get("missing", [])),
            "odds_failed": len(manifest["odds"].get("failed", [])),
        }
        return response

    # --- one day ----------------------------------------------------------------

    async def _record_day(self, day: date, mode: str, by: str) -> dict[str, Any]:
        regions = self._regions()
        manifest = (await get_json(self.store, manifest_key(day))) or new_manifest(day, regions)
        if manifest.get("complete"):
            manifest["skipped"] = True
            return manifest
        manifest.pop("skipped", None)
        manifest["attempts"] = int(manifest.get("attempts", 0)) + 1
        started = time.perf_counter()
        calls_at_start = self.racing.stats.calls
        run: dict[str, Any] = {"mode": mode, "by": by, "started_at": now_iso()}
        errors: list[str] = []
        self.current = {"date": day.isoformat(), "mode": mode, "phase": "start", "started_at": run["started_at"],
                        "calls_at_start": calls_at_start, "odds_done": 0, "odds_total": 0}
        log(logger, logging.INFO, "recorder day start", date=day.isoformat(), mode=mode, attempt=manifest["attempts"])
        try:
            cards_data = await self._do_cards(day, manifest, errors)
            await self._do_results(day, manifest, errors)
            await self._do_odds(day, manifest, cards_data, errors)
        finally:
            self.current = None
        manifest["complete"] = self._is_complete(day, manifest)
        manifest["errors"] = errors
        manifest["calls"] = self.racing.stats.calls - calls_at_start + int(manifest.get("calls_previous", 0))
        manifest["calls_previous"] = manifest["calls"]
        manifest["duration_seconds"] = round(time.perf_counter() - started, 1)
        manifest["finished_at"] = now_iso()
        run.update({"finished_at": manifest["finished_at"], "complete": manifest["complete"], "errors": len(errors)})
        manifest["runs"] = (manifest.get("runs") or [])[-9:] + [run]
        await put_json(self.store, manifest_key(day), manifest)
        self.index[day.isoformat()] = self._index_entry(manifest)
        await self._save_index()
        self.last_run = self._summary(manifest)
        log(logger, logging.INFO, "recorder day done", date=day.isoformat(), complete=manifest["complete"],
            calls=manifest["calls"], duration_seconds=manifest["duration_seconds"], errors=len(errors))
        self._publish_done(manifest)
        return manifest

    def _publish_done(self, manifest: dict[str, Any]) -> None:
        if self.bus is not None:
            self.bus.publish("recorder", {"phase": "done", **self._summary(manifest)})

    def _is_complete(self, day: date, manifest: dict[str, Any]) -> bool:
        cards_ok = manifest["cards"].get("status") in ("ok", "skipped", "unavailable")
        results = manifest["results"]
        results_ok = results.get("status") in ("skipped", "unavailable") or (
            results.get("status") == "ok" and results.get("all_bsp") is True
        )
        odds = manifest["odds"]
        odds_ok = odds.get("status") in ("skipped", "ok")
        return bool(cards_ok and results_ok and odds_ok)

    # --- cards -----------------------------------------------------------------

    def _cards_required(self, day: date) -> tuple[bool, str | None]:
        if day < self._date_setting("cards_history_from"):
            return False, f"racecards start {self.settings.get('cards_history_from')} on this plan"
        learned = self.state.get("cards_available_from")
        if learned and day < date.fromisoformat(learned):
            return False, f"the API answered that racecards are unavailable before {learned}"
        return True, None

    async def _do_cards(self, day: date, manifest: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
        section = manifest["cards"]
        required, why = self._cards_required(day)
        if not required:
            section.update({"status": "skipped", "detail": why})
            return None
        if section.get("status") == "ok":
            # Already stored by an earlier attempt: load it for the runner list.
            return await get_json(self.store, cards_key(day))
        self._publish("cards")
        params = {"date": day.isoformat(), "region_codes": self._regions(), "limit": 500}
        try:
            fetched = await self.racing.fetch("/racecards/pro", params, describe=f"racecards for {day.isoformat()}", background=True)
        except ApiError as exc:
            await self._component_failed("cards", day, section, exc, errors, boundary_key="cards_available_from")
            return None
        await put_raw_gzip(self.store, cards_key(day), fetched.raw)
        races = fetched.data.get("racecards") or [] if isinstance(fetched.data, dict) else []
        section.update({
            "status": "ok", "key": cards_key(day), "fetched_at": fetched.fetched_at, "http_status": fetched.status,
            "races": len(races), "runners": sum(len(r.get("runners") or []) for r in races),
            "total_reported": fetched.data.get("total") if isinstance(fetched.data, dict) else None,
            "bytes": len(fetched.raw),
        })
        return fetched.data

    async def _component_failed(self, name: str, day: date, section: dict[str, Any], exc: ApiError,
                                errors: list[str], boundary_key: str) -> None:
        if exc.upstream_status in UNAVAILABLE_STATUSES:
            section.update({"status": "unavailable", "http_status": exc.upstream_status, "detail": exc.message,
                            "fetched_at": now_iso()})
            self.state[boundary_key] = (day + timedelta(days=1)).isoformat()
            self.state[boundary_key + "_detail"] = exc.message
            await self._save_state()
            log(logger, logging.WARNING, f"recorder {name} unavailable", date=day.isoformat(), status=exc.upstream_status, detail=exc.message)
        else:
            section.update({"status": "error", "http_status": exc.upstream_status, "detail": exc.message, "fetched_at": now_iso()})
            errors.append(f"{name}: {exc.message}")
            log(logger, logging.ERROR, f"recorder {name} failed", date=day.isoformat(), detail=exc.message)
        return None

    # --- results ---------------------------------------------------------------

    def _results_required(self, day: date) -> tuple[bool, str | None]:
        limit_days = int(self.settings.get("results_history_days"))
        if day < self.today_uk() - timedelta(days=limit_days):
            return False, f"results cover the last {limit_days} days on this plan"
        learned = self.state.get("results_available_from")
        if learned and day < date.fromisoformat(learned):
            return False, f"the API answered that results are unavailable before {learned}"
        return True, None

    async def _do_results(self, day: date, manifest: dict[str, Any], errors: list[str]) -> None:
        section = manifest["results"]
        required, why = self._results_required(day)
        if not required:
            section.update({"status": "skipped", "detail": why})
            return
        if section.get("status") == "ok" and section.get("all_bsp"):
            return
        self._publish("results")
        page_size = int(self.settings.get("recorder_results_page_size"))
        pages: list[dict[str, Any]] = []
        keys: list[str] = []
        skip = 0
        page_no = 1
        fetched_at = None
        while True:
            params = {"start_date": day.isoformat(), "end_date": day.isoformat(), "region": self._regions(),
                      "limit": page_size, "skip": skip}
            try:
                fetched = await self.racing.fetch("/results", params, describe=f"results for {day.isoformat()} (page {page_no})", background=True)
            except ApiError as exc:
                await self._component_failed("results", day, section, exc, errors, boundary_key="results_available_from")
                return
            await put_raw_gzip(self.store, results_key(day, page_no), fetched.raw)
            keys.append(results_key(day, page_no))
            fetched_at = fetched.fetched_at
            data = fetched.data if isinstance(fetched.data, dict) else {}
            pages.append(data)
            got = len(data.get("results") or [])
            total = data.get("total")
            skip += got
            page_no += 1
            if got < page_size or got == 0 or (isinstance(total, int) and skip >= total):
                break
        races, runners, with_bsp = count_bsp(pages)
        section.update({
            "status": "ok", "keys": keys, "pages": len(keys), "fetched_at": fetched_at, "http_status": 200,
            "races": races, "runners": runners, "runners_with_bsp": with_bsp,
            "all_bsp": runners == with_bsp,
            "total_reported": pages[0].get("total") if pages else None,
        })
        card_races = int(manifest["cards"].get("races") or 0)
        if races == 0 and card_races > 0:
            # The card shows racing but results came back empty: the plan does not reach this day.
            section["status"] = "empty"
            section["detail"] = (f"the API returned no results although the card has {card_races} races; "
                                 "results on this plan do not reach this day. Older days are not asked for results.")
            self.state["results_available_from"] = (day + timedelta(days=1)).isoformat()
            self.state["results_available_from_detail"] = section["detail"]
            await self._save_state()
            log(logger, logging.WARNING, "recorder results empty for a racing day", date=day.isoformat(), card_races=card_races)
            return
        if runners != with_bsp:
            section["detail"] = f"{runners - with_bsp} of {runners} runners have no BSP yet; the day is retried on the next run."

    # --- odds -------------------------------------------------------------------

    async def _do_odds(self, day: date, manifest: dict[str, Any], cards_data: dict[str, Any] | None, errors: list[str]) -> None:
        section = manifest["odds"]
        if day < self._date_setting("odds_history_from"):
            section.update({"status": "skipped", "detail": f"odds history starts {self.settings.get('odds_history_from')} on this plan"})
            return
        if manifest["cards"].get("status") != "ok":
            if manifest["cards"].get("status") in ("skipped", "unavailable"):
                section.update({"status": "skipped", "detail": "no racecard for the day, so no runner list for odds"})
            else:
                section.update({"status": "blocked", "detail": "the racecard fetch failed, so the runner list is unknown"})
            return
        if cards_data is None:
            cards_data = await get_json(self.store, cards_key(day))
        pairs = runners_from_cards(cards_data)
        done = set(section.get("done") or [])
        missing = set(section.get("missing") or [])
        section["failed"] = []
        section["expected"] = len(pairs)
        todo = [p for p in pairs if f"{p[0]}/{p[1]}" not in done and f"{p[0]}/{p[1]}" not in missing]
        self._publish("odds", odds_done=len(done) + len(missing), odds_total=len(pairs))
        consecutive = 0
        for n, (race_id, horse_id) in enumerate(todo, start=1):
            ref = f"{race_id}/{horse_id}"
            try:
                fetched = await self.racing.fetch(f"/odds/{race_id}/{horse_id}", None, describe=f"odds history {ref}", background=True)
            except ApiError as exc:
                if exc.upstream_status == 404:
                    missing.add(ref)
                    consecutive = 0
                else:
                    section["failed"].append({"runner": ref, "detail": exc.message})
                    consecutive += 1
                    if consecutive >= CONSECUTIVE_FAILURES_TO_ABORT:
                        errors.append(f"odds: {consecutive} consecutive failures, day aborted; last: {exc.message}")
                        break
                continue
            consecutive = 0
            await put_raw_gzip(self.store, odds_key(day, race_id, horse_id), fetched.raw)
            done.add(ref)
            if n % 25 == 0 and self.current is not None:
                self.current["odds_done"] = len(done) + len(missing)
        section["done"] = sorted(done)
        section["missing"] = sorted(missing)
        section["fetched_at"] = now_iso()
        finished = len(done) + len(missing) >= len(pairs) and not section["failed"]
        section["status"] = "ok" if finished else "partial"
        if section["failed"]:
            errors.append(f"odds: {len(section['failed'])} runners failed")
