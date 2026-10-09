"""Operational endpoints: the FB12 job itself."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from core.auth import METHOD_GOOGLE
from core.errors import ApiError
from models.schemas import (
    CalculateRequest, CalculateResponse, MoveResponse, PaceResponse, PaperCreated, PaperList, PaperRequest, RaceCard,
    RaceList, SettleResponse,
)
from services.dutch import calculate
from services.move import compute_move
from services.pace import compute_pace
from services.recorder import parse_mode
from datetime import date as date_type, timedelta

from services.races import UK, map_race_card, map_race_summary, parse_off_dt

router = APIRouter(prefix="/api", tags=["api"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REGION_RE = re.compile(r"^[a-z]{2,4}$")
RACE_ID_RE = re.compile(r"^rac_[A-Za-z0-9]+$")


def _parse_date(value: str | None) -> str:
    if value is None or not value.strip():
        return datetime.now(UK).strftime("%Y-%m-%d")
    text = value.strip()
    if not DATE_RE.match(text):
        raise ApiError(400, "INVALID_INPUT", f"date must be YYYY-MM-DD, not {text!r}.")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ApiError(400, "INVALID_INPUT", f"{text!r} is not a real date.") from None
    return text


def _parse_regions(value: str | None, default: list[str]) -> list[str]:
    if value is None or not value.strip():
        regions = [r.lower() for r in default]
    else:
        regions = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not regions:
        raise ApiError(400, "INVALID_INPUT", "regions must name at least one region, for example gb,ire.")
    for region in regions:
        if not REGION_RE.match(region):
            raise ApiError(400, "INVALID_INPUT", f"{region!r} is not a region code. Use codes like gb or ire.")
    return regions


def _check_race_id(race_id: str) -> str:
    if not RACE_ID_RE.match(race_id):
        raise ApiError(400, "INVALID_INPUT", f"{race_id!r} is not a Racing API race id (they look like rac_12345).")
    return race_id


@router.get("/races", response_model=RaceList)
async def list_races(
    request: Request,
    date: str | None = Query(None, description="YYYY-MM-DD, default today in UK time"),
    regions: str | None = Query(None, description="Comma-separated region codes, default from settings"),
    pattern_only: bool = Query(False),
) -> Any:
    state = request.app.state
    day = _parse_date(date)
    region_codes = _parse_regions(regions, state.store.get("regions"))
    data, _ = await state.racing.get(
        "/racecards/pro",
        {"date": day, "region_codes": region_codes},
        cache_kind="race_list",
        describe=f"race list for {day} ({', '.join(region_codes)})",
    )
    cards = data.get("racecards") if isinstance(data, dict) else None
    if cards is None:
        raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's race list for {day} had no racecards field.")
    races = [map_race_summary(card) for card in cards]
    if pattern_only:
        races = [r for r in races if r["pattern"]]
    # One day, one offset: the ISO off_dt strings sort chronologically. Unknown times last.
    races.sort(key=lambda r: (r["off_dt"] is None, r["off_dt"] or "", r["course"] or ""))
    return {"date": day, "races": races}


@router.get("/races/{race_id}", response_model=RaceCard)
async def get_race(race_id: str, request: Request) -> Any:
    state = request.app.state
    _check_race_id(race_id)
    data, fetched_at = await state.racing.get(
        f"/racecards/{race_id}/pro",
        None,
        cache_kind="race_card",
        describe=f"race card {race_id}",
    )
    if not isinstance(data, dict) or "runners" not in data:
        raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's card for {race_id} had no runners field.")
    return map_race_card(data, fetched_at)


@router.post("/calculate", response_model=CalculateResponse)
async def post_calculate(body: CalculateRequest) -> Any:
    """The maths, nothing else: no Racing API call, nothing stored."""
    result = calculate(body.stake_total, body.commission_rate, [r.model_dump() for r in body.runners])
    return result.to_contract()


@router.post("/record")
async def post_record(request: Request, date: str | None = Query(None, description="YYYY-MM-DD, 'yesterday' or 'backfill'")) -> Any:
    """Operator only: records one day of raw Racing API responses into the recordings bucket."""
    credential = getattr(request.state, "credential", None)
    if credential is None or credential.method != METHOD_GOOGLE:
        raise ApiError(401, "UNAUTHENTICATED", "Not authenticated.")
    mode, day = parse_mode(date)
    return await request.app.state.recorder.record(mode, day, by=credential.email)


HORSE_ID_RE = re.compile(r"^hrs_[A-Za-z0-9]+$")


def _check_horse_id(horse_id: str) -> str:
    if not HORSE_ID_RE.match(horse_id):
        raise ApiError(400, "INVALID_INPUT", f"{horse_id!r} is not a Racing API horse id (they look like hrs_12345).")
    return horse_id


async def _race_day(state: Any, race_id: str) -> date_type:
    """The race's date (UK), from the cached card."""
    data, _ = await state.racing.get(f"/racecards/{race_id}/pro", None, cache_kind="race_card", describe=f"race card {race_id}")
    if not isinstance(data, dict):
        raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's card for {race_id} was not an object.")
    text = str(data.get("date") or "").strip()
    if text:
        try:
            return date_type.fromisoformat(text)
        except ValueError:
            pass
    off = parse_off_dt(data.get("off_dt"))
    if off is None:
        raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's card for {race_id} carries no usable date or off time.")
    return off.astimezone(UK).date()


@router.get("/races/{race_id}/runners/{horse_id}/move", response_model=MoveResponse)
async def get_move(race_id: str, horse_id: str, request: Request) -> Any:
    state = request.app.state
    _check_race_id(race_id)
    _check_horse_id(horse_id)
    race_day = await _race_day(state, race_id)
    data, _ = await state.racing.get(
        f"/odds/{race_id}/{horse_id}", None, cache_kind="odds", describe=f"odds history for {horse_id} in {race_id}",
    )
    if not isinstance(data, dict):
        raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's odds history for {horse_id} in {race_id} was not an object.")
    return compute_move(horse_id, data, race_day)


@router.get("/races/{race_id}/runners/{horse_id}/pace", response_model=PaceResponse, response_model_by_alias=True)
async def get_pace(
    race_id: str,
    horse_id: str,
    request: Request,
    runs: int | None = Query(None, ge=1, le=50, description="Past runs to read; default from settings"),
) -> Any:
    state = request.app.state
    _check_race_id(race_id)
    _check_horse_id(horse_id)
    count = int(runs or state.store.get("past_runs"))
    race_day = await _race_day(state, race_id)
    end_date = (race_day - timedelta(days=1)).isoformat()
    data, _ = await state.racing.get(
        f"/horses/{horse_id}/results",
        {"start_date": "2000-01-01", "end_date": end_date, "limit": count},
        cache_kind="past_runs",
        describe=f"past runs of {horse_id} before {race_day.isoformat()}",
    )
    if not isinstance(data, dict):
        raise ApiError(502, "UPSTREAM_ERROR", f"The Racing API's results for {horse_id} were not an object.")
    lists = {
        "LED": list(state.store.get("pace_led")),
        "PROMINENT": list(state.store.get("pace_prominent")),
        "HELD_UP": list(state.store.get("pace_held_up")),
        "MIDFIELD": list(state.store.get("pace_midfield")),
    }
    return compute_pace(horse_id, data, lists, count)


ENTRY_ID_RE = re.compile(r"^pe_[A-Za-z0-9_]+$")


def _check_entry_id(entry_id: str) -> str:
    if not ENTRY_ID_RE.match(entry_id):
        raise ApiError(400, "INVALID_INPUT", f"{entry_id!r} is not a paper entry id (they look like pe_20261009T143000_a1b2c3).")
    return entry_id


@router.post("/paper", status_code=201, response_model=PaperCreated)
async def post_paper(body: PaperRequest, request: Request) -> Any:
    """Saves a paper entry. The API recalculates from the inputs; figures sent by the browser are never stored."""
    credential = getattr(request.state, "credential", None)
    saved_by = getattr(credential, "email", "unknown")
    return await request.app.state.paper.create(body.model_dump(), saved_by=saved_by)


@router.get("/paper", response_model=PaperList)
async def list_paper(request: Request, status: str | None = Query(None, description="OPEN, SETTLED or NEEDS_REVIEW")) -> Any:
    return {"entries": await request.app.state.paper.list(status)}


@router.get("/paper/{entry_id}")
async def get_paper(entry_id: str, request: Request) -> Any:
    _check_entry_id(entry_id)
    return await request.app.state.paper.get(entry_id)


@router.post("/paper/{entry_id}/settle", response_model=SettleResponse)
async def settle_paper(entry_id: str, request: Request) -> Any:
    _check_entry_id(entry_id)
    return await request.app.state.paper.settle(entry_id)
