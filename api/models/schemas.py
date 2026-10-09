"""Pydantic v2 request models. extra="forbid" everywhere: an unknown field is an error."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsUpdate(Strict):
    values: dict[str, Any] = Field(..., description="Setting key -> new value")


# --- API contract: races ---------------------------------------------------

RunnerStatus = Literal["DECLARED", "NON_RUNNER", "RESERVE"]


class RaceSummary(Strict):
    race_id: str
    off_dt: str | None
    off_time_uk: str | None
    course: str | None
    race_name: str | None
    pattern: str | None
    race_class: str | None
    field_size: int | None
    region: str | None


class RaceList(Strict):
    date: str
    races: list[RaceSummary]


class RaceHeader(Strict):
    race_id: str
    off_dt: str | None
    off_time_uk: str | None
    course: str | None
    race_name: str | None
    pattern: str | None
    distance: str | None
    going: str | None
    field_size: int | None


class RunnerCard(Strict):
    horse_id: str
    horse: str
    number: str
    draw: int | None
    status: RunnerStatus
    owner: str | None
    owner_id: str | None
    trainer: str | None
    trainer_id: str | None
    jockey: str | None
    official_rating: int | None
    form: str | None
    exchange_price: float | None
    exchange_updated: str | None
    best_bookmaker_price: float | None
    best_bookmaker: str | None
    same_owner_as: list[str]
    same_trainer_too: bool


class RaceCard(Strict):
    race: RaceHeader
    fetched_at: str
    runners: list[RunnerCard]


# --- API contract: calculate -------------------------------------------------

Tier = Literal["PROFIT", "BREAK_EVEN", "PART", "OUT"]


class CalculateRunnerIn(Strict):
    horse_id: str
    horse: str
    price: float | None = None
    tier: Tier
    part_fraction: float | None = None


class CalculateRequest(Strict):
    stake_total: float
    commission_rate: float
    runners: list[CalculateRunnerIn]


class CalculateRunnerOut(Strict):
    horse_id: str
    horse: str
    tier: Tier
    price: float | None
    stake: float | None
    return_if_wins: float | None
    net_if_wins: float | None
    net_after_commission: float | None
    market_chance: float | None
    break_even_chance: float | None
    can_break_even: bool | None
    wins_wiped_out: float | None


class CalculateResponse(Strict):
    feasible: bool
    message: str | None
    profit_per_win: float | None
    book_pct: float | None
    expected_value_gbp: float | None
    expected_value_pct: float | None
    runners: list[CalculateRunnerOut]
