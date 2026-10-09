"""Operational endpoints: the FB12 job itself."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from core.errors import ApiError
from models.schemas import CalculateRequest, CalculateResponse, RaceCard, RaceList
from services.dutch import calculate
from services.races import UK, map_race_card, map_race_summary

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
