"""Results and export over paper entries. Totals are over settled bets; trials, open entries
and entries needing review are counted but kept out. Every figure the GUI shows comes from here.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from services.paper import KIND_BET, STATUS_NEEDS_REVIEW, STATUS_OPEN, STATUS_SETTLED, PaperStore
from services.races import parse_off_dt

BANDS: list[tuple[str, float, float]] = [
    ("0-5 min", 0, 5), ("5-15 min", 5, 15), ("15-30 min", 15, 30), ("30-60 min", 30, 60),
    ("60-120 min", 60, 120), ("120+ min", 120, float("inf")),
]


def band_for(minutes: float | None) -> str:
    if minutes is None:
        return "unknown"
    if minutes < 0:
        return "after the off"
    for label, low, high in BANDS:
        if low <= minutes < high:
            return label
    return "120+ min"


def _r2(value: float | None) -> float | None:
    return None if value is None else round(value + 0.0, 2)


def _pct(numerator: float, denominator: float) -> float | None:
    return None if not denominator else round(numerator / denominator * 100.0, 2)


def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals over settled bets, each with the number of bets behind it."""
    bets = len(items)
    staked = sum(float(i.get("stake_total") or 0) for i in items)
    profit_items = [i for i in items if i.get("pnl_after_commission") is not None]
    profit = sum(float(i["pnl_after_commission"]) for i in profit_items)
    at_prices = sum(float(i["pnl"]) for i in items if i.get("pnl") is not None)
    sp_items = [i for i in items if i.get("pnl_at_sp") is not None]
    bsp_items = [i for i in items if i.get("pnl_at_bsp_after_commission") is not None]
    expected_items = [i for i in items if i.get("expected_profit_gbp") is not None]
    winners = [i for i in profit_items if float(i["pnl_after_commission"]) > 0.004]
    return {
        "bets": {"value": bets, "n": bets},
        "staked": {"value": _r2(staked), "n": bets},
        "profit": {"value": _r2(profit), "n": len(profit_items)},
        "profit_at_prices_taken": {"value": _r2(at_prices), "n": len(profit_items)},
        "profit_at_sp": {"value": _r2(sum(float(i["pnl_at_sp"]) for i in sp_items)), "n": len(sp_items)},
        "profit_at_sp_after_commission": {"value": _r2(sum(float(i.get("pnl_at_sp_after_commission") or 0) for i in sp_items)), "n": len(sp_items)},
        "profit_at_bsp": {"value": _r2(sum(float(i["pnl_at_bsp"]) for i in bsp_items if i.get("pnl_at_bsp") is not None)), "n": len(bsp_items)},
        "profit_at_bsp_after_commission": {"value": _r2(sum(float(i["pnl_at_bsp_after_commission"]) for i in bsp_items)), "n": len(bsp_items)},
        "return_on_stake_pct": {"value": _pct(profit, staked), "n": len(profit_items)},
        "win_rate_pct": {"value": _pct(len(winners), len(profit_items)), "n": len(profit_items)},
        "winning_bets": {"value": len(winners), "n": len(profit_items)},
        "expected_profit": {"value": _r2(sum(float(i["expected_profit_gbp"]) for i in expected_items)), "n": len(expected_items)},
        "expected_minus_actual": {
            "value": _r2(sum(float(i["expected_profit_gbp"]) for i in expected_items) - profit) if expected_items and profit_items else None,
            "n": min(len(expected_items), len(profit_items)),
        },
    }


def _split(items: list[dict[str, Any]], key_of) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(key_of(item), []).append(item)
    out = []
    for key, members in groups.items():
        totals = aggregate(members)
        out.append({"key": key, **{k: v["value"] for k, v in totals.items()}, "n": len(members)})
    return out


def stats(index_items: list[dict[str, Any]], kind: str = KIND_BET) -> dict[str, Any]:
    wanted = [i for i in index_items if i.get("kind", "TRIAL") == kind]
    settled = [i for i in wanted if i.get("status") == STATUS_SETTLED]
    open_items = [i for i in wanted if i.get("status") == STATUS_OPEN]
    review_items = [i for i in wanted if i.get("status") == STATUS_NEEDS_REVIEW]
    trials = [i for i in index_items if i.get("kind", "TRIAL") != kind]
    ordered = sorted(settled, key=lambda i: (i.get("off_dt") or "", i.get("placed_at") or ""))
    cumulative: list[dict[str, Any]] = []
    running = 0.0
    for i in ordered:
        pnl = float(i.get("pnl_after_commission") or 0.0)
        running += pnl
        cumulative.append({
            "entry_id": i["entry_id"], "off_dt": i.get("off_dt"), "race_name": i.get("race_name"), "course": i.get("course"),
            "winner": i.get("winner"), "pnl": _r2(pnl), "cumulative": _r2(running),
            "expected": _r2(float(i["expected_profit_gbp"])) if i.get("expected_profit_gbp") is not None else None,
        })
    band_order = {label: n for n, (label, _, _) in enumerate(BANDS)}
    by_band = sorted(_split(settled, lambda i: band_for(i.get("minutes_before_off"))), key=lambda g: band_order.get(g["key"], 99))
    return {
        "scope": {
            "kind": kind, "statuses": [STATUS_SETTLED],
            "settled": len(settled), "open": len(open_items), "needs_review": len(review_items), "trials": len(trials),
            "bsp_pending": sum(1 for i in settled if i.get("bsp_pending")),
        },
        "totals": aggregate(settled),
        "cumulative": cumulative,
        "splits": {
            "preset": sorted(_split(settled, lambda i: i.get("preset") or "custom"), key=lambda g: g["key"]),
            "pattern": sorted(_split(settled, lambda i: "pattern race" if i.get("pattern") else "not a pattern race"), key=lambda g: g["key"]),
            "minutes_before_off": by_band,
        },
    }


ENTRY_COLUMNS = [
    "entry_id", "kind", "status", "race_id", "race_name", "course", "off_dt", "pattern", "placed_at", "placed_by",
    "minutes_before_off", "preset", "stake_total", "commission_rate", "expected_profit_gbp", "expected_profit_pct",
    "profit_per_win", "book_pct", "winner", "pnl", "pnl_after_commission", "pnl_at_sp", "pnl_at_sp_after_commission",
    "pnl_at_bsp", "pnl_at_bsp_after_commission", "bsp_pending", "review_reason", "settled_at", "card_fetched_at",
]
RUNNER_COLUMNS = [
    "horse_id", "horse", "tier", "part_fraction", "price_taken", "card_price", "card_price_at_save", "price_edited",
    "stake", "return_if_wins", "net_if_wins", "market_chance", "break_even_chance", "wins_wiped_out",
    "in_result", "position", "sp", "sp_dec", "bsp", "won", "return_at_price_taken", "return_at_sp", "return_at_bsp",
]
COLUMNS = ENTRY_COLUMNS + RUNNER_COLUMNS


def export_rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per runner per entry with every settlement field. Unsettled entries carry
    their saved figures and empty result fields."""
    settlement = entry.get("settlement") or {}
    figures = entry.get("figures") or {}
    base = {
        "entry_id": entry["entry_id"], "kind": entry.get("kind"), "status": entry.get("status"),
        "race_id": entry["race"].get("race_id"), "race_name": entry["race"].get("race_name"), "course": entry["race"].get("course"),
        "off_dt": entry["race"].get("off_dt"), "pattern": entry["race"].get("pattern"),
        "placed_at": entry.get("placed_at"), "placed_by": entry.get("placed_by"), "minutes_before_off": entry.get("minutes_before_off"),
        "preset": entry.get("preset"), "stake_total": entry["inputs"].get("stake_total"), "commission_rate": entry["inputs"].get("commission_rate"),
        "expected_profit_gbp": entry.get("expected_profit_gbp"), "expected_profit_pct": entry.get("expected_profit_pct"),
        "profit_per_win": figures.get("profit_per_win"), "book_pct": figures.get("book_pct"),
        "winner": settlement.get("winner"), "pnl": settlement.get("pnl"), "pnl_after_commission": settlement.get("pnl_after_commission"),
        "pnl_at_sp": settlement.get("pnl_at_sp"), "pnl_at_sp_after_commission": settlement.get("pnl_at_sp_after_commission"),
        "pnl_at_bsp": settlement.get("pnl_at_bsp"), "pnl_at_bsp_after_commission": settlement.get("pnl_at_bsp_after_commission"),
        "bsp_pending": settlement.get("bsp_pending"), "review_reason": settlement.get("review_reason"),
        "settled_at": settlement.get("settled_at"), "card_fetched_at": entry["race"].get("card_fetched_at"),
    }
    runners = settlement.get("runners") or PaperStore.runner_rows(entry, entry.get("raw_result"), settled=False)
    return [{**base, **{c: r.get(c) for c in RUNNER_COLUMNS}} for r in runners]


def to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return buffer.getvalue()


def export_filename(now: datetime) -> str:
    return f"fb12-paper-bets-{now.strftime('%Y%m%d-%H%M')}.csv"
