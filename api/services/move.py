"""Price movement from the runner's odds history (GET /odds/{race_id}/{horse_id}).

Source order (Charles, 9 October 2026): the bookmaker median first; Betfair
Exchange only when no bookmaker has history. The card holds one price per
bookmaker with no movement, so movement always comes from the odds history,
which is minute level, every bookmaker, from the evening before to the off.
"SP" and dash entries are skipped. Exchange prices outside that minute's
bookmaker range are dropped: thin early books show 1.1 while bookmakers are at
16/1. First price is the price at the start of race day (UK), carrying the last
evening price forward, or the first race-day price if nothing came before;
latest is the newest price. change_pct is latest against first.
"""

from __future__ import annotations

from datetime import date, datetime, time
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from services.races import EXCHANGES, BETFAIR_EXCHANGE, to_float

UK = ZoneInfo("Europe/London")

SOURCE_BOOKMAKERS = "bookmaker median"
SOURCE_EXCHANGE = "Betfair Exchange"


def parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UK)
    return parsed


def usable_price(value: Any) -> float | None:
    """Decimal odds from a history or card entry; 'SP', dashes and blanks are skipped."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "SP" or text in ("-", "—"):
        return None
    price = to_float(text)
    if price is None or price <= 1.0:
        return None
    return price


def series(entry: dict[str, Any]) -> list[tuple[datetime, float]]:
    """A bookmaker's history as (time, price) oldest first, unusable entries skipped."""
    points: list[tuple[datetime, float]] = []
    for item in entry.get("history") or []:
        when = parse_time(item.get("changed_at"))
        price = usable_price(item.get("decimal"))
        if when is not None and price is not None:
            points.append((when, price))
    points.sort(key=lambda p: p[0])
    return points


def price_at(points: list[tuple[datetime, float]], when: datetime) -> float | None:
    """The last price at or before `when` (a step function), or None if none yet."""
    current = None
    for stamp, price in points:
        if stamp <= when:
            current = price
        else:
            break
    return current


def race_day_start(race_day: date) -> datetime:
    return datetime.combine(race_day, time(0, 0), tzinfo=UK)


def compute_move(horse_id: str, odds_response: dict[str, Any], race_day: date) -> dict[str, Any]:
    entries = odds_response.get("odds") or []
    bookmakers = {}
    exchange = None
    for entry in entries:
        name = str(entry.get("bookmaker") or "").strip()
        lowered = name.lower()
        if lowered == BETFAIR_EXCHANGE:
            exchange = entry
        elif lowered in EXCHANGES:
            continue
        elif name:
            bookmakers[name] = entry

    def result(source: str | None, first: tuple[datetime, float] | None, latest: tuple[datetime, float] | None, note: str | None) -> dict[str, Any]:
        change_pct = None
        direction = None
        if first is not None and latest is not None and first[1] > 0:
            change_pct = round((latest[1] - first[1]) / first[1] * 100.0, 2)
            if abs(latest[1] - first[1]) < 1e-9:
                direction = "unchanged"
            elif latest[1] < first[1]:
                direction = "shortened"
            else:
                direction = "drifted"
        return {
            "horse_id": horse_id,
            "source": source,
            "first_price": round(first[1], 2) if first else None,
            "first_at": first[0].isoformat() if first else None,
            "latest_price": round(latest[1], 2) if latest else None,
            "latest_at": latest[0].isoformat() if latest else None,
            "change_pct": change_pct,
            "direction": direction,
            "note": note,
        }

    day_start = race_day_start(race_day)
    book_series = {name: series(entry) for name, entry in bookmakers.items()}
    book_series = {name: pts for name, pts in book_series.items() if pts}

    if book_series:
        all_stamps = sorted({stamp for pts in book_series.values() for stamp, _ in pts})
        earliest = all_stamps[0]
        latest_stamp = all_stamps[-1]
        # Start of race day if any bookmaker priced before it (the evening price carries forward),
        # else the first price of the day.
        first_at = day_start if earliest <= day_start else earliest
        first_prices = [p for p in (price_at(pts, first_at) for pts in book_series.values()) if p is not None]
        latest_prices = [p for p in (price_at(pts, latest_stamp) for pts in book_series.values()) if p is not None]
        if first_prices and latest_prices:
            note = None
            if first_at == latest_stamp:
                note = "only one bookmaker price time in the history"
            elif earliest > day_start:
                note = "no bookmaker price before race day; first price is the first of the day"
            return result(
                SOURCE_BOOKMAKERS,
                (first_at, float(median(first_prices))),
                (latest_stamp, float(median(latest_prices))),
                note if note else f"median of {len(book_series)} bookmakers with history",
            )

    # Fallback: Betfair Exchange, inside the bookmakers' range at each minute.
    if exchange is not None:
        ex_points = series(exchange)
        if ex_points:
            current_book_prices = [p for p in (usable_price(e.get("decimal")) for e in bookmakers.values()) if p is not None]
            kept: list[tuple[datetime, float]] = []
            dropped = 0
            for stamp, price in ex_points:
                at_minute = [p for p in (price_at(pts, stamp) for pts in book_series.values()) if p is not None] or current_book_prices
                if at_minute:
                    low, high = min(at_minute), max(at_minute)
                    if price < low or price > high:
                        dropped += 1
                        continue
                kept.append((stamp, price))
            if kept:
                stamps = [s for s, _ in kept]
                first_at = day_start if stamps[0] <= day_start else stamps[0]
                first_price = price_at(kept, first_at)
                if first_price is None:
                    first_at, first_price = kept[0]
                latest_at, latest_price = kept[-1]
                note = "Betfair Exchange: no bookmaker has history"
                if dropped:
                    note += f"; {dropped} exchange prices outside the bookmaker range dropped"
                if not current_book_prices and not book_series:
                    note += "; no bookmaker prices to bound the exchange"
                return result(SOURCE_EXCHANGE, (first_at, first_price), (latest_at, latest_price), note)
            return result(None, None, None, "no price history: every Betfair Exchange price was outside the bookmaker range")
    if not entries:
        return result(None, None, None, "no price history: the odds response lists no bookmakers")
    return result(None, None, None, "no price history")
