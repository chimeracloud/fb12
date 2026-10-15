"""Paper entries: one JSON object per entry in the paper entries bucket, settled against the result.

An entry holds the saved time (UTC), saved_by, the inputs, every figure from the
calculate function (the one code path), and the race card exactly as FB12 saw
it at save time. Settle fetches the result, stores it raw in the same object,
and works out the P&L for the winner from the saved stakes and prices. A dead
heat, or any runner in the entry turning non runner, sets NEEDS_REVIEW with the
reason and no automatic P&L.

Settlement fields (contract of 9 October 2026): pnl and pnl_after_commission at
the saved prices; pnl_at_sp at bookmaker SP, no commission, straight away;
pnl_at_bsp and pnl_at_bsp_after_commission once BSP is in, bsp_pending until
then. A later settle call fills them.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, time as time_of_day, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from core.errors import ApiError
from core.logging import log
from core.storage import ObjectStore, get_json, put_json
from services.dutch import calculate
from services.races import STATUS_DECLARED, map_race_card, parse_off_dt, to_float, uk_time

logger = logging.getLogger("fb12.paper")

INDEX_KEY = "entries/_index.json"
STATUS_OPEN = "OPEN"
STATUS_SETTLED = "SETTLED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUSES = (STATUS_OPEN, STATUS_SETTLED, STATUS_NEEDS_REVIEW)
KIND_BET = "BET"
KIND_TRIAL = "TRIAL"
PRESETS = ("top_two", "four_horses", "custom")
UK = ZoneInfo("Europe/London")
BSP_RETRY_MINUTES = 60
BSP_MAX_ATTEMPTS = 48
RESULT_GRACE_MINUTES = 1



def entry_key(entry_id: str) -> str:
    return f"entries/{entry_id}.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_entry_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    return f"pe_{stamp}_{secrets.token_hex(3)}"


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    rounded = round(value + 0.0, 2)
    return 0.0 if rounded == 0 else rounded


def _after_commission(value: float | None, commission: float) -> float | None:
    if value is None:
        return None
    return value * (1.0 - commission) if value > 0 else value


def _names(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


class PaperStore:
    def __init__(self, store: ObjectStore, racing: Any, settings: Any) -> None:
        self.store = store
        self.racing = racing
        self.settings = settings
        self._index: dict[str, dict[str, Any]] | None = None

    # --- index ---------------------------------------------------------------

    async def _load_index(self) -> dict[str, dict[str, Any]]:
        if self._index is not None:
            return self._index
        try:
            document = await get_json(self.store, INDEX_KEY)
            if document is None:
                keys = await self.store.list_keys("entries/")
                entries: dict[str, dict[str, Any]] = {}
                for key in keys:
                    if key.endswith("_index.json"):
                        continue
                    entry = await get_json(self.store, key)
                    if entry:
                        entries[entry["entry_id"]] = self._list_item(entry)
                self._index = entries
                if keys:
                    await self._save_index()
            else:
                self._index = document.get("entries", {})
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApiError(
                502, "UPSTREAM_ERROR",
                f"The paper entries bucket gs://{self.store.bucket} could not be read ({type(exc).__name__}: {exc}).",
            ) from exc
        return self._index

    async def _save_index(self) -> None:
        await put_json(self.store, INDEX_KEY, {"updated_at": now_iso(), "entries": self._index or {}})

    @staticmethod
    def _list_item(entry: dict[str, Any]) -> dict[str, Any]:
        settlement = entry.get("settlement") or {}
        return {
            "entry_id": entry["entry_id"],
            "race_id": entry["race"]["race_id"],
            "race_name": entry["race"].get("race_name"),
            "course": entry["race"].get("course"),
            "off_dt": entry["race"].get("off_dt"),
            "pattern": entry["race"].get("pattern"),
            "saved_at": entry["saved_at"],
            "saved_by": entry["saved_by"],
            "status": entry["status"],
            "kind": entry.get("kind", KIND_TRIAL),
            "placed_at": entry.get("placed_at", entry["saved_at"]),
            "minutes_before_off": entry.get("minutes_before_off"),
            "preset": entry.get("preset"),
            "stake_total": entry["inputs"]["stake_total"],
            "expected_profit_gbp": entry.get("expected_profit_gbp"),
            "winner": settlement.get("winner"),
            "pnl": settlement.get("pnl"),
            "pnl_after_commission": settlement.get("pnl_after_commission"),
            "pnl_at_sp": settlement.get("pnl_at_sp"),
            "pnl_at_sp_after_commission": settlement.get("pnl_at_sp_after_commission"),
            "pnl_at_bsp": settlement.get("pnl_at_bsp"),
            "pnl_at_bsp_after_commission": settlement.get("pnl_at_bsp_after_commission"),
            "bsp_pending": settlement.get("bsp_pending"),
            "review_reason": settlement.get("review_reason"),
            "auto": entry.get("auto"),
        }

    async def _write(self, entry: dict[str, Any]) -> None:
        try:
            await put_json(self.store, entry_key(entry["entry_id"]), entry)
            index = await self._load_index()
            index[entry["entry_id"]] = self._list_item(entry)
            await self._save_index()
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApiError(
                502, "UPSTREAM_ERROR",
                f"The paper entry could not be written to gs://{self.store.bucket} ({type(exc).__name__}: {exc}).",
            ) from exc

    # --- create ---------------------------------------------------------------

    async def create(self, body: dict[str, Any], saved_by: str) -> dict[str, Any]:
        race_id = str(body.get("race_id") or "").strip()
        if not race_id:
            raise ApiError(400, "INVALID_INPUT", "race_id is required.")
        if not body.get("runners"):
            raise ApiError(400, "INVALID_INPUT", "runners must list at least one runner.")
        card, fetched_at = await self.racing.get(
            f"/racecards/{race_id}/pro", None, cache_kind="race_card", describe=f"race card {race_id}",
        )
        if not isinstance(card, dict) or "runners" not in card:
            raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's card for {race_id} had no runners field.")
        mapped = map_race_card(card, fetched_at)
        by_id = {r["horse_id"]: r for r in mapped["runners"]}

        problems: list[str] = []
        runner_inputs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in body["runners"]:
            horse_id = str(raw.get("horse_id") or "").strip()
            on_card = by_id.get(horse_id)
            if on_card is None:
                problems.append(f"{horse_id or '(blank)'} is not on the card for {race_id}.")
                continue
            if horse_id in seen:
                problems.append(f"{on_card['horse']} appears more than once.")
            seen.add(horse_id)
            if on_card["status"] != STATUS_DECLARED:
                problems.append(f"{on_card['horse']} is a {on_card['status'].lower().replace('_', ' ')} on the card and cannot be in the entry.")
            runner_inputs.append({
                "horse_id": horse_id,
                "horse": on_card["horse"],
                "price": raw.get("price"),
                "card_price": raw.get("card_price"),
                "card_price_at_save": on_card["exchange_price"],
                "card_price_updated_at_save": on_card["exchange_updated"],
                "price_edited": bool(raw.get("price_edited", False)),
                "tier": raw.get("tier"),
                "part_fraction": raw.get("part_fraction"),
            })
        preset = body.get("preset") or "custom"
        if preset not in PRESETS:
            problems.append(f"preset must be one of {', '.join(PRESETS)}, not {preset!r}.")
        if problems:
            raise ApiError(400, "INVALID_INPUT", "Invalid input. " + " ".join(problems))

        now = datetime.now(UTC)
        off = parse_off_dt(mapped["race"]["off_dt"])
        minutes_before_off = round((off - now).total_seconds() / 60.0, 1) if off is not None else None
        trial = any(r["price_edited"] for r in runner_inputs)
        kind = KIND_TRIAL if trial else KIND_BET
        if kind == KIND_BET:
            if off is None:
                raise ApiError(400, "INVALID_INPUT", f"The card for {race_id} carries no off time, so a bet cannot be timed. Typed prices save as a trial.")
            if now >= off:
                raise ApiError(
                    400, "INVALID_INPUT",
                    f"{mapped['race']['race_name']} went off at {uk_time(mapped['race']['off_dt'])} UK; bets after the off are refused. "
                    "Typed prices save as a trial, which is kept out of the totals.",
                )

        result = calculate(body.get("stake_total"), body.get("commission_rate"), [
            {"horse_id": r["horse_id"], "horse": r["horse"], "price": r["price"], "tier": r["tier"], "part_fraction": r["part_fraction"]}
            for r in runner_inputs
        ])
        if not result.feasible:
            raise ApiError(400, "INVALID_INPUT", f"The entry is not feasible, so it was not saved: {result.message}")

        entry = {
            "entry_id": new_entry_id(now),
            "status": STATUS_OPEN,
            "kind": kind,
            "trial": trial,
            "saved_at": now.isoformat(),
            "saved_by": saved_by,
            "placed_at": now.isoformat(),
            "placed_by": saved_by,
            "minutes_before_off": minutes_before_off,
            "preset": preset,
            "expected_profit_gbp": result.to_contract()["expected_value_gbp"],
            "expected_profit_pct": result.to_contract()["expected_value_pct"],
            "race": {
                "race_id": race_id,
                "race_name": mapped["race"]["race_name"],
                "course": mapped["race"]["course"],
                "off_dt": mapped["race"]["off_dt"],
                "off_time_uk": uk_time(mapped["race"]["off_dt"]),
                "pattern": mapped["race"]["pattern"],
                "field_size": mapped["race"]["field_size"],
                "card_fetched_at": fetched_at,
            },
            "inputs": {
                "stake_total": result.stake_total,
                "commission_rate": result.commission_rate,
                "runners": runner_inputs,
            },
            "figures": result.to_contract(),
            "settlement": None,
            "result_summary": None,
            "raw_card": card,
            "raw_result": None,
        }
        await self._write(entry)
        log(logger, logging.INFO, "paper bet placed" if kind == KIND_BET else "paper trial saved", entry_id=entry["entry_id"],
            race_id=race_id, saved_by=saved_by, stake_total=result.stake_total, runners=len(runner_inputs),
            minutes_before_off=minutes_before_off, preset=preset)
        return {"entry_id": entry["entry_id"], "status": STATUS_OPEN, "saved_at": entry["saved_at"], "saved_by": saved_by,
                "kind": kind, "minutes_before_off": minutes_before_off}

    # --- read -----------------------------------------------------------------

    async def list(self, status: str | None, kind: str | None = None) -> list[dict[str, Any]]:
        if status:
            wanted = status.strip().upper()
            if wanted not in STATUSES:
                raise ApiError(400, "INVALID_INPUT", f"status must be one of OPEN, SETTLED or NEEDS_REVIEW, not {status!r}.")
        else:
            wanted = None
        wanted_kind = kind.strip().upper() if kind else None
        if wanted_kind and wanted_kind not in (KIND_BET, KIND_TRIAL):
            raise ApiError(400, "INVALID_INPUT", f"kind must be BET or TRIAL, not {kind!r}.")
        index = await self._load_index()
        items = [item for item in index.values()
                 if (wanted is None or item.get("status") == wanted) and (wanted_kind is None or item.get("kind") == wanted_kind)]
        items.sort(key=lambda item: item.get("saved_at") or "", reverse=True)
        return items

    async def index_items(self) -> list[dict[str, Any]]:
        index = await self._load_index()
        return list(index.values())

    async def entries_full(self, status: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        """Every entry object (without the raw responses), newest first, for the export."""
        items = await self.list(status, kind)
        entries = []
        for item in items:
            entry = await self._read_entry(item["entry_id"])
            entries.append({k: v for k, v in entry.items() if k != "raw_card"})
        return entries

    async def _read_entry(self, entry_id: str) -> dict[str, Any]:
        try:
            entry = await get_json(self.store, entry_key(entry_id))
        except Exception as exc:  # noqa: BLE001
            raise ApiError(502, "UPSTREAM_ERROR", f"The paper entry {entry_id} could not be read ({type(exc).__name__}: {exc}).") from exc
        if entry is None:
            raise ApiError(404, "NOT_FOUND", f"There is no paper entry {entry_id}.")
        return entry

    async def get(self, entry_id: str) -> dict[str, Any]:
        entry = await self._read_entry(entry_id)
        return {k: v for k, v in entry.items() if k not in ("raw_card", "raw_result")}

    # --- settle -------------------------------------------------------------------

    async def settle(self, entry_id: str) -> dict[str, Any]:
        entry = await self._read_entry(entry_id)
        settlement = entry.get("settlement") or {}
        if entry["status"] == STATUS_SETTLED and settlement.get("bsp_pending") is False:
            return self._settle_response(entry)
        race_id = entry["race"]["race_id"]
        try:
            result, fetched_at = await self.racing.get(f"/results/{race_id}", None, cache_kind=None, describe=f"result of {race_id}")
        except ApiError as exc:
            if exc.upstream_status == 404 or exc.status_code == 404:
                raise ApiError(
                    409, "NO_RESULT_YET",
                    f"The result of {entry['race'].get('race_name') or race_id} is not published yet by The Racing API.",
                    exc.upstream_status,
                ) from exc
            raise
        if not isinstance(result, dict) or not result.get("runners"):
            raise ApiError(409, "NO_RESULT_YET", f"The Racing API's result for {race_id} has no runners yet.")
        entry["raw_result"] = result
        entry["result_fetched_at"] = fetched_at
        entry["settlement"] = self.work_out(entry, result)
        entry["status"] = entry["settlement"]["status"]
        entry["result_summary"] = self._summary(result)
        await self._write(entry)
        log(logger, logging.INFO, "paper entry settled", entry_id=entry_id, status=entry["status"],
            winner=entry["settlement"].get("winner"), pnl=entry["settlement"].get("pnl"), bsp_pending=entry["settlement"].get("bsp_pending"))
        return self._settle_response(entry)

    # --- settlement without clicks ---------------------------------------------------

    @staticmethod
    def bsp_window_opens(off: datetime) -> datetime:
        """BSP lands the next morning: from 06:00 UK on the day after the off."""
        next_day = off.astimezone(UK).date() + timedelta(days=1)
        return datetime.combine(next_day, time_of_day(6, 0), tzinfo=UK)

    def _due(self, item: dict[str, Any], now: datetime) -> tuple[bool, str]:
        """Whether an index item is due a settle attempt now, and why or why not."""
        off = parse_off_dt(item.get("off_dt"))
        if off is None:
            return False, "no off time"
        auto = item.get("auto") or {}
        last = parse_off_dt(auto.get("last_attempt_at"))
        if item.get("status") == STATUS_OPEN:
            if now < off + timedelta(minutes=RESULT_GRACE_MINUTES):
                return False, "not off yet"
            return True, "open after the off"
        if item.get("status") == STATUS_SETTLED and item.get("bsp_pending"):
            opens = self.bsp_window_opens(off)
            if now < opens:
                return False, f"BSP window opens {opens.isoformat()}"
            if int(auto.get("bsp_attempts", 0)) >= BSP_MAX_ATTEMPTS:
                return False, "BSP attempts exhausted"
            if last is not None and now - last < timedelta(minutes=BSP_RETRY_MINUTES):
                return False, "BSP tried within the last hour"
            return True, "BSP pending"
        return False, "nothing to do"

    async def _note_attempt(self, entry_id: str, auto: dict[str, Any]) -> None:
        entry = await self._read_entry(entry_id)
        entry["auto"] = auto
        await self._write(entry)

    async def settle_due(self, by: str) -> dict[str, Any]:
        """Settles every open entry whose race is off and refreshes BSP on settled entries once
        the next morning has come. Called by Cloud Scheduler every 5 minutes; manual settle stays."""
        now = datetime.now(UTC)
        index = await self._load_index()
        settled: list[dict[str, Any]] = []
        filled: list[str] = []
        waiting: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped = 0
        for entry_id, item in sorted(index.items()):
            due, why = self._due(item, now)
            if not due:
                skipped += 1
                continue
            auto = dict(item.get("auto") or {"attempts": 0, "bsp_attempts": 0})
            auto["last_attempt_at"] = now.isoformat()
            auto["last_attempt_by"] = by
            refreshing_bsp = item.get("status") == STATUS_SETTLED
            if refreshing_bsp:
                auto["bsp_attempts"] = int(auto.get("bsp_attempts", 0)) + 1
            else:
                auto["attempts"] = int(auto.get("attempts", 0)) + 1
            try:
                response = await self.settle(entry_id)
            except ApiError as exc:
                auto["last_outcome"] = f"{exc.code}: {exc.message}"
                await self._note_attempt(entry_id, auto)
                if exc.code == "NO_RESULT_YET":
                    waiting.append({"entry_id": entry_id, "why": why, "message": exc.message})
                else:
                    errors.append({"entry_id": entry_id, "message": exc.message})
                continue
            auto["last_outcome"] = response["status"] + (" (BSP pending)" if response.get("bsp_pending") else "")
            await self._note_attempt(entry_id, auto)
            if refreshing_bsp:
                if response.get("bsp_pending"):
                    waiting.append({"entry_id": entry_id, "why": "BSP still pending"})
                else:
                    filled.append(entry_id)
            else:
                settled.append(response)
        summary = {
            "checked_at": now.isoformat(),
            "entries": len(index),
            "due": len(settled) + len(filled) + len(waiting) + len(errors),
            "skipped": skipped,
            "settled": settled,
            "bsp_filled": filled,
            "waiting": waiting,
            "errors": errors,
        }
        if settled or filled or errors:
            log(logger, logging.INFO, "settle-due run", settled=[x["entry_id"] for x in settled], bsp_filled=filled,
                waiting=len(waiting), errors=len(errors))
        return summary

    @staticmethod
    def _summary(result: dict[str, Any]) -> dict[str, Any]:
        positions = []
        for runner in result.get("runners") or []:
            positions.append({
                "position": runner.get("position"), "horse_id": runner.get("horse_id"), "horse": runner.get("horse"),
                "sp": runner.get("sp"), "sp_dec": runner.get("sp_dec"), "bsp": runner.get("bsp"), "btn": runner.get("btn"),
            })
        winners = [p["horse"] for p in positions if str(p.get("position") or "").strip() == "1"]
        return {
            "winner": winners[0] if len(winners) == 1 else None,
            "winners": winners,
            "positions": positions,
            "non_runners": result.get("non_runners"),
            "off_dt": result.get("off_dt"),
            "going": result.get("going"),
            "winning_time_detail": result.get("winning_time_detail"),
        }

    @staticmethod
    def runner_rows(entry: dict[str, Any], result: dict[str, Any] | None, settled: bool) -> list[dict[str, Any]]:
        """One row per runner in the entry: what was taken, what the result says, what it returned."""
        inputs = {r["horse_id"]: r for r in entry["inputs"].get("runners") or []}
        by_id = {r.get("horse_id"): r for r in (result or {}).get("runners") or []}
        rows: list[dict[str, Any]] = []
        for f in entry["figures"]["runners"]:
            inp = inputs.get(f["horse_id"], {})
            res = by_id.get(f["horse_id"])
            position = str(res.get("position") or "").strip() if res else None
            won = position == "1" if res else None
            stake = float(f["stake"]) if f.get("stake") is not None else 0.0
            sp_dec = to_float(res.get("sp_dec")) if res else None
            bsp = to_float(res.get("bsp")) if res else None

            def returned(price: float | None) -> float | None:
                if not settled or won is None:
                    return None
                if not won:
                    return 0.0
                return _round(stake * price) if price else None

            rows.append({
                "horse_id": f["horse_id"],
                "horse": f["horse"],
                "tier": f["tier"],
                "part_fraction": inp.get("part_fraction"),
                "price_taken": f.get("price"),
                "card_price": inp.get("card_price"),
                "card_price_at_save": inp.get("card_price_at_save"),
                "price_edited": inp.get("price_edited"),
                "stake": _round(stake),
                "return_if_wins": f.get("return_if_wins"),
                "net_if_wins": f.get("net_if_wins"),
                "market_chance": f.get("market_chance"),
                "break_even_chance": f.get("break_even_chance"),
                "wins_wiped_out": f.get("wins_wiped_out"),
                "in_result": res is not None,
                "position": position or None,
                "sp": res.get("sp") if res else None,
                "sp_dec": sp_dec,
                "bsp": bsp,
                "won": won,
                "return_at_price_taken": returned(f.get("price")),
                "return_at_sp": returned(sp_dec),
                "return_at_bsp": returned(bsp),
            })
        return rows

    @staticmethod
    def work_out(entry: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """The settlement from the saved stakes and prices and the result. Pure."""
        total = float(entry["inputs"]["stake_total"])
        commission = float(entry["inputs"]["commission_rate"])
        figures = {r["horse_id"]: r for r in entry["figures"]["runners"]}
        result_runners = result.get("runners") or []
        by_id = {r.get("horse_id"): r for r in result_runners}
        winners = [r for r in result_runners if str(r.get("position") or "").strip() == "1"]

        def review(reason: str) -> dict[str, Any]:
            return {
                "status": STATUS_NEEDS_REVIEW, "winner": winners[0].get("horse") if len(winners) == 1 else None,
                "winners": [w.get("horse") for w in winners], "pnl": None, "pnl_after_commission": None,
                "pnl_at_sp": None, "pnl_at_sp_after_commission": None, "pnl_at_bsp": None, "pnl_at_bsp_after_commission": None, "bsp_pending": None,
                "review_reason": reason, "settled_at": now_iso(),
                "runners": PaperStore.runner_rows(entry, result, settled=False),
            }

        non_runner_text = str(result.get("non_runners") or "").lower()
        missing = [f["horse"] for hid, f in figures.items() if hid not in by_id]
        named_nr = [f["horse"] for f in figures.values() if f["horse"].lower() in non_runner_text and non_runner_text]
        if missing or named_nr:
            names = sorted(set(missing) | set(named_nr))
            return review(f"{_names(names)} {'was' if len(names) == 1 else 'were'} not in the result as a runner (non runner or withdrawn); the saved stakes no longer describe the race.")
        if len(winners) != 1:
            if len(winners) == 0:
                return review("The result names no winner (no runner in position 1).")
            return review(f"Dead heat between {_names([w.get('horse') or '?' for w in winners])}.")

        winner = winners[0]
        winner_id = winner.get("horse_id")
        winner_figures = figures.get(winner_id)
        stake = float(winner_figures["stake"]) if winner_figures and winner_figures.get("stake") is not None else 0.0
        if winner_figures is not None and winner_figures.get("net_if_wins") is not None:
            pnl = float(winner_figures["net_if_wins"])
        else:
            pnl = -total  # the winner was not in the entry: every stake is lost
        sp_dec = to_float(winner.get("sp_dec"))
        bsp = to_float(winner.get("bsp"))
        pnl_at_sp = (stake * sp_dec - total) if sp_dec else None
        pnl_at_bsp = (stake * bsp - total) if bsp else None
        notes = []
        if sp_dec is None:
            notes.append("the result carries no decimal SP for the winner")
        return {
            "status": STATUS_SETTLED,
            "winner": winner.get("horse"),
            "winner_horse_id": winner_id,
            "winner_in_entry": winner_figures is not None,
            "winner_tier": winner_figures.get("tier") if winner_figures else None,
            "winner_stake": _round(stake),
            "winner_price_saved": winner_figures.get("price") if winner_figures else None,
            "winner_sp_dec": sp_dec,
            "winner_bsp": bsp,
            "pnl": _round(pnl),
            "pnl_after_commission": _round(_after_commission(pnl, commission)),
            "pnl_at_sp": _round(pnl_at_sp),
            "pnl_at_sp_after_commission": _round(_after_commission(pnl_at_sp, commission)),
            "pnl_at_bsp": _round(pnl_at_bsp),
            "pnl_at_bsp_after_commission": _round(_after_commission(pnl_at_bsp, commission)),
            "bsp_pending": bsp is None,
            "review_reason": None,
            "note": "; ".join(notes) if notes else None,
            "settled_at": now_iso(),
            "stake_total": _round(total),
            "commission_rate": commission,
            "expected_profit_gbp": entry.get("expected_profit_gbp"),
            "runners": PaperStore.runner_rows(entry, result, settled=True),
        }

    @staticmethod
    def _settle_response(entry: dict[str, Any]) -> dict[str, Any]:
        settlement = entry.get("settlement") or {}
        return {
            "entry_id": entry["entry_id"],
            "status": entry["status"],
            "winner": settlement.get("winner"),
            "pnl": settlement.get("pnl"),
            "pnl_after_commission": settlement.get("pnl_after_commission"),
            "pnl_at_sp": settlement.get("pnl_at_sp"),
            "pnl_at_sp_after_commission": settlement.get("pnl_at_sp_after_commission"),
            "pnl_at_bsp": settlement.get("pnl_at_bsp"),
            "pnl_at_bsp_after_commission": settlement.get("pnl_at_bsp_after_commission"),
            "bsp_pending": settlement.get("bsp_pending"),
            "review_reason": settlement.get("review_reason"),
        }
