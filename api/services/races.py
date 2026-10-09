"""Race list and race card: The Racing API's racecards mapped to the contract.

Field names are those of the Racing API's RacecardOddsPro / RunnerOddsPro
schemas (checked against api.theracingapi.com/openapi.json on 9 October 2026).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")

BETFAIR_EXCHANGE = "betfair exchange"
EXCHANGES = {"betfair exchange", "smarkets", "matchbook"}

STATUS_DECLARED = "DECLARED"
STATUS_NON_RUNNER = "NON_RUNNER"
STATUS_RESERVE = "RESERVE"


def parse_off_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def uk_time(value: Any) -> str | None:
    """off_dt (ISO with offset) -> HH:MM in UK time."""
    parsed = parse_off_dt(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UK)
    return parsed.astimezone(UK).strftime("%H:%M")


def to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if number.is_integer() else None


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_updated(value: Any) -> str | None:
    """The card gives odds 'updated' as 'YYYY-MM-DD HH:MM:SS' with no offset.
    The Racing API is a UK service and its offset-bearing times are UK time, so
    a naive updated time is read as UK time and returned in ISO 8601 with offset."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UK)
    return parsed.isoformat()


def runner_status(number: Any) -> str:
    text = str(number or "").strip().upper()
    if text == "NR":
        return STATUS_NON_RUNNER
    if text.startswith("R"):
        return STATUS_RESERVE
    return STATUS_DECLARED


def blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def map_race_summary(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "race_id": card.get("race_id"),
        "off_dt": card.get("off_dt"),
        "off_time_uk": uk_time(card.get("off_dt")),
        "course": card.get("course"),
        "race_name": card.get("race_name"),
        "pattern": blank_to_none(card.get("pattern")),
        "race_class": blank_to_none(card.get("race_class")),
        "field_size": to_int(card.get("field_size")),
        "region": card.get("region"),
    }


def exchange_and_best(odds: list[dict[str, Any]] | None) -> tuple[float | None, str | None, float | None, str | None]:
    """(exchange_price, exchange_updated, best_bookmaker_price, best_bookmaker)."""
    exchange_price = None
    exchange_updated = None
    best_price = None
    best_name = None
    for entry in odds or []:
        name = str(entry.get("bookmaker") or "").strip()
        price = to_float(entry.get("decimal"))
        if price is None:
            continue
        lowered = name.lower()
        if lowered == BETFAIR_EXCHANGE:
            exchange_price = price
            exchange_updated = parse_updated(entry.get("updated"))
            continue
        if lowered in EXCHANGES:
            continue
        if best_price is None or price > best_price:
            best_price = price
            best_name = name
    return exchange_price, exchange_updated, best_price, best_name


def map_race_card(card: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    runners_in = card.get("runners") or []
    mapped: list[dict[str, Any]] = []
    for runner in runners_in:
        exchange_price, exchange_updated, best_price, best_name = exchange_and_best(runner.get("odds"))
        mapped.append({
            "horse_id": runner.get("horse_id"),
            "horse": runner.get("horse"),
            "number": str(runner.get("number") or "").strip(),
            "draw": to_int(runner.get("draw")),
            "status": runner_status(runner.get("number")),
            "owner": runner.get("owner"),
            "owner_id": blank_to_none(runner.get("owner_id")),
            "trainer": runner.get("trainer"),
            "trainer_id": blank_to_none(runner.get("trainer_id")),
            "jockey": runner.get("jockey"),
            "official_rating": to_int(runner.get("ofr")),
            "form": blank_to_none(runner.get("form")),
            "exchange_price": exchange_price,
            "exchange_updated": exchange_updated,
            "best_bookmaker_price": best_price,
            "best_bookmaker": best_name,
            "same_owner_as": [],
            "same_trainer_too": False,
        })
    declared = [r for r in mapped if r["status"] == STATUS_DECLARED]
    for runner in mapped:
        if runner["status"] != STATUS_DECLARED or not runner["owner_id"]:
            continue
        others = [o for o in declared if o is not runner and o["owner_id"] == runner["owner_id"]]
        runner["same_owner_as"] = [o["horse"] for o in others]
        runner["same_trainer_too"] = any(
            o["trainer_id"] and o["trainer_id"] == runner["trainer_id"] for o in others
        )
    return {
        "race": {
            "race_id": card.get("race_id"),
            "off_dt": card.get("off_dt"),
            "off_time_uk": uk_time(card.get("off_dt")),
            "course": card.get("course"),
            "race_name": card.get("race_name"),
            "pattern": blank_to_none(card.get("pattern")),
            "distance": blank_to_none(card.get("distance")),
            "going": blank_to_none(card.get("going")),
            "field_size": to_int(card.get("field_size")),
        },
        "fetched_at": fetched_at,
        "runners": mapped,
    }
