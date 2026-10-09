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
    raw: dict[str, Any]


class RaceCard(Strict):
    race: RaceHeader
    fetched_at: str
    raw_race: dict[str, Any]
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


# --- API contract: move and pace -------------------------------------------------

class MoveResponse(Strict):
    horse_id: str
    source: Literal["bookmaker median", "Betfair Exchange"] | None
    first_price: float | None
    first_at: str | None
    latest_price: float | None
    latest_at: str | None
    change_pct: float | None
    direction: Literal["shortened", "drifted", "unchanged"] | None
    note: str | None


class PaceRun(Strict):
    date: str | None
    course: str | None
    race_name: str | None
    position: str | None
    race_class: str | None = Field(None, alias="class")
    comment: str | None
    category: Literal["LED", "PROMINENT", "MIDFIELD", "HELD_UP", "UNCLASSIFIED"]
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PaceCounts(Strict):
    LED: int
    PROMINENT: int
    MIDFIELD: int
    HELD_UP: int
    UNCLASSIFIED: int


class PaceResponse(Strict):
    horse_id: str
    counts: PaceCounts
    runs: list[PaceRun]


# --- API contract: paper entries ----------------------------------------------------

PaperStatus = Literal["OPEN", "SETTLED", "NEEDS_REVIEW"]


class PaperRunnerIn(Strict):
    horse_id: str
    price: float | None = None
    card_price: float | None = None
    price_edited: bool = False
    tier: Tier
    part_fraction: float | None = None


class PaperRequest(Strict):
    race_id: str
    stake_total: float
    commission_rate: float
    runners: list[PaperRunnerIn]


class PaperCreated(Strict):
    entry_id: str
    status: Literal["OPEN"]
    saved_at: str
    saved_by: str


class PaperListItem(Strict):
    entry_id: str
    race_id: str
    race_name: str | None
    course: str | None
    off_dt: str | None
    saved_at: str
    saved_by: str
    status: PaperStatus
    pnl: float | None
    pnl_after_commission: float | None
    pnl_at_sp: float | None
    pnl_at_bsp: float | None
    pnl_at_bsp_after_commission: float | None
    bsp_pending: bool | None
    review_reason: str | None


class PaperList(Strict):
    entries: list[PaperListItem]


class SettleResponse(Strict):
    entry_id: str
    status: PaperStatus
    winner: str | None
    pnl: float | None
    pnl_after_commission: float | None
    pnl_at_sp: float | None
    pnl_at_bsp: float | None
    pnl_at_bsp_after_commission: float | None
    bsp_pending: bool | None
    review_reason: str | None
