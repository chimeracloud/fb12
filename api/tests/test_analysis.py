"""Results and export: totals with the number of bets behind each, cumulative profit, splits,
and one CSV row per runner per bet. Built from settled entries on the real Goodwood result."""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from services import analysis, racing_api
from services.dutch import calculate
from services.paper import PaperStore
from services.racing_api import RacingApiClient

FIXTURES = Path(__file__).parent / "fixtures"
GOODWOOD = json.loads((FIXTURES / "goodwood_results_page.json").read_text(encoding="utf-8"))["results"][0]
RACE = "rac_11991616"
SP = {r["horse"]: (r["horse_id"], float(r["sp_dec"])) for r in GOODWOOD["runners"]}


def runner(horse: str, tier: str, part_fraction: float | None = None) -> dict:
    horse_id, price = SP[horse]
    return {"horse_id": horse_id, "horse": horse, "price": price, "card_price": price, "card_price_at_save": price,
            "price_edited": False, "tier": tier, "part_fraction": part_fraction}


def make_entry(entry_id: str, runners: list[dict], *, kind: str = "BET", preset: str = "top_two", pattern: str | None = "Group 2",
               minutes_before_off: float = 45.0, off: datetime | None = None, stake: float = 100) -> dict:
    off = off or datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
    result = calculate(stake, 0.02, [{k: r[k] for k in ("horse_id", "horse", "price", "tier", "part_fraction")} for r in runners])
    assert result.feasible, result.message
    figures = result.to_contract()
    return {
        "entry_id": entry_id, "status": "OPEN", "kind": kind, "trial": kind == "TRIAL",
        "saved_at": (off - timedelta(minutes=minutes_before_off)).isoformat(), "saved_by": "cloud@ascotwm.com",
        "placed_at": (off - timedelta(minutes=minutes_before_off)).isoformat(), "placed_by": "cloud@ascotwm.com",
        "minutes_before_off": minutes_before_off, "preset": preset,
        "expected_profit_gbp": figures["expected_value_gbp"], "expected_profit_pct": figures["expected_value_pct"],
        "race": {"race_id": RACE, "race_name": "Lennox Stakes", "course": "Goodwood", "off_dt": off.isoformat(), "pattern": pattern,
                 "card_fetched_at": (off - timedelta(minutes=minutes_before_off)).isoformat()},
        "inputs": {"stake_total": stake, "commission_rate": 0.02, "runners": runners},
        "figures": figures, "settlement": None, "result_summary": None, "raw_card": {}, "raw_result": None,
    }


def settle(entry: dict, result: dict = GOODWOOD) -> dict:
    entry = json.loads(json.dumps(entry))
    entry["settlement"] = PaperStore.work_out(entry, result)
    entry["status"] = entry["settlement"]["status"]
    entry["raw_result"] = result
    return entry


WIN = [runner("Lake Forest (GB)", "PROFIT"), runner("Rogue Diplomat (IRE)", "PROFIT"), runner("Holguin (GB)", "OUT")]
LOSE = [runner("Witness Stand (GB)", "PROFIT"), runner("Qirat (GB)", "PROFIT"), runner("Lake Forest (GB)", "OUT")]
EVEN = [runner("Witness Stand (GB)", "PROFIT"), runner("Lake Forest (GB)", "BREAK_EVEN"), runner("Holguin (GB)", "OUT")]


def test_runner_rows_carry_what_was_taken_and_what_came_back():
    entry = settle(make_entry("pe_a", WIN))
    rows = {r["horse"]: r for r in entry["settlement"]["runners"]}
    lake = rows["Lake Forest (GB)"]
    assert lake["won"] is True and lake["position"] == "1" and lake["sp_dec"] == 1.91 and lake["bsp"] == 2.05
    assert lake["price_taken"] == 1.91 and lake["price_edited"] is False and lake["tier"] == "PROFIT"
    assert lake["return_at_price_taken"] == pytest.approx(lake["stake"] * 1.91, abs=0.01)
    assert lake["return_at_sp"] == pytest.approx(lake["stake"] * 1.91, abs=0.01)
    assert lake["return_at_bsp"] == pytest.approx(lake["stake"] * 2.05, abs=0.01)
    rogue = rows["Rogue Diplomat (IRE)"]
    assert rogue["won"] is False and rogue["position"] == "2" and rogue["return_at_price_taken"] == 0.0 and rogue["return_at_bsp"] == 0.0
    holguin = rows["Holguin (GB)"]
    assert holguin["tier"] == "OUT" and holguin["stake"] == 0.0 and holguin["position"] == "5"
    # A review leaves the returns empty but keeps the positions.
    dead_heat = json.loads(json.dumps(GOODWOOD))
    next(r for r in dead_heat["runners"] if r["horse"] == "Rogue Diplomat (IRE)")["position"] = "1"
    reviewed = settle(make_entry("pe_b", WIN), dead_heat)
    assert reviewed["status"] == "NEEDS_REVIEW"
    assert all(r["return_at_price_taken"] is None for r in reviewed["settlement"]["runners"])
    assert {r["horse"]: r["position"] for r in reviewed["settlement"]["runners"]}["Rogue Diplomat (IRE)"] == "1"


def test_band_for():
    assert analysis.band_for(3) == "0-5 min" and analysis.band_for(5) == "5-15 min" and analysis.band_for(29.9) == "15-30 min"
    assert analysis.band_for(60) == "60-120 min" and analysis.band_for(500) == "120+ min"
    assert analysis.band_for(-2) == "after the off" and analysis.band_for(None) == "unknown"


def test_stats_totals_cumulative_and_splits():
    items = [
        PaperStore._list_item(settle(make_entry("pe_1", WIN, preset="top_two", minutes_before_off=10, off=datetime(2026, 7, 28, 14, 0, tzinfo=UTC)))),
        PaperStore._list_item(settle(make_entry("pe_2", LOSE, preset="four_horses", pattern=None, minutes_before_off=70, off=datetime(2026, 7, 28, 15, 0, tzinfo=UTC)))),
        PaperStore._list_item(settle(make_entry("pe_3", EVEN, preset="custom", minutes_before_off=3, off=datetime(2026, 7, 28, 16, 0, tzinfo=UTC)))),
        PaperStore._list_item(make_entry("pe_open", WIN, off=datetime(2026, 7, 29, 14, 0, tzinfo=UTC))),  # OPEN: counted, not totalled
        PaperStore._list_item(settle(make_entry("pe_trial", WIN, kind="TRIAL"))),  # a trial: out of the totals
    ]
    out = analysis.stats(items)
    assert out["scope"] == {"kind": "BET", "statuses": ["SETTLED"], "settled": 3, "open": 1, "needs_review": 0, "trials": 1, "bsp_pending": 0}
    totals = out["totals"]
    win_pnl = settle(make_entry("x", WIN))["settlement"]["pnl_after_commission"]
    assert totals["bets"] == {"value": 3, "n": 3}
    assert totals["staked"] == {"value": 300.0, "n": 3}
    assert totals["profit"]["value"] == pytest.approx(win_pnl - 100.0 + 0.0, abs=0.01) and totals["profit"]["n"] == 3
    assert totals["return_on_stake_pct"]["value"] == pytest.approx((win_pnl - 100.0) / 300.0 * 100, abs=0.01)
    assert totals["win_rate_pct"] == {"value": pytest.approx(33.33, abs=0.01), "n": 3}
    assert totals["winning_bets"]["value"] == 1
    assert totals["expected_profit"]["n"] == 3 and totals["expected_minus_actual"]["n"] == 3
    assert totals["profit_at_bsp_after_commission"]["n"] == 3
    # Cumulative in off-time order.
    assert [c["entry_id"] for c in out["cumulative"]] == ["pe_1", "pe_2", "pe_3"]
    assert out["cumulative"][0]["cumulative"] == pytest.approx(win_pnl, abs=0.01)
    assert out["cumulative"][1]["cumulative"] == pytest.approx(win_pnl - 100.0, abs=0.01)
    assert out["cumulative"][2]["cumulative"] == pytest.approx(win_pnl - 100.0, abs=0.01)
    # Splits.
    by_preset = {g["key"]: g for g in out["splits"]["preset"]}
    assert set(by_preset) == {"top_two", "four_horses", "custom"} and by_preset["four_horses"]["profit"] == -100.0 and by_preset["four_horses"]["n"] == 1
    by_pattern = {g["key"]: g for g in out["splits"]["pattern"]}
    assert by_pattern["pattern race"]["n"] == 2 and by_pattern["not a pattern race"]["n"] == 1
    bands = [g["key"] for g in out["splits"]["minutes_before_off"]]
    assert bands == ["0-5 min", "5-15 min", "60-120 min"]
    # Trials have their own view.
    assert analysis.stats(items, kind="TRIAL")["scope"]["settled"] == 1


def test_export_rows_and_csv():
    entry = settle(make_entry("pe_1", WIN, minutes_before_off=12))
    rows = analysis.export_rows(entry)
    assert len(rows) == 3 and [r["horse"] for r in rows] == ["Lake Forest (GB)", "Rogue Diplomat (IRE)", "Holguin (GB)"]
    assert set(analysis.COLUMNS) <= set(rows[0])
    assert rows[0]["entry_id"] == "pe_1" and rows[0]["kind"] == "BET" and rows[0]["minutes_before_off"] == 12
    assert rows[0]["pnl_after_commission"] == entry["settlement"]["pnl_after_commission"] and rows[0]["won"] is True
    unsettled = analysis.export_rows(make_entry("pe_open", WIN))
    assert unsettled[0]["status"] == "OPEN" and unsettled[0]["pnl"] is None and unsettled[0]["won"] is None and unsettled[0]["stake"] > 0
    text = analysis.to_csv(rows)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert len(parsed) == 3 and parsed[0]["horse"] == "Lake Forest (GB)" and parsed[0]["won"] == "True"
    assert parsed[2]["return_at_price_taken"] == "0.0" and parsed[0]["review_reason"] == ""
    assert text.splitlines()[0] == ",".join(analysis.COLUMNS)


# --- through the app ---------------------------------------------------------------------

@pytest.fixture(autouse=True)
def credentials_from_memory(monkeypatch):
    monkeypatch.setattr(racing_api, "get_credential", lambda name: {"racing_api_username": "fb12-user", "racing_api_password": "fb12-pass"}[name])


@pytest.fixture
def stats_app(app):
    racing = RacingApiClient(app.state.store, transport=httpx.MockTransport(lambda r: httpx.Response(404, json={"detail": "Not Found"})), base_url="https://racing.test/v1")
    app.state.racing = racing
    app.state.paper.racing = racing
    store = app.state.paper
    for entry in (settle(make_entry("pe_20260728T130000_aaa001", WIN)), settle(make_entry("pe_20260728T130000_bbb002", LOSE, preset="four_horses")),
                  make_entry("pe_20260729T130000_ccc003", WIN, off=datetime(2026, 7, 29, 14, 0, tzinfo=UTC))):
        asyncio.run(store._write(entry))
    return app


def test_stats_endpoint(stats_app, client, operator_headers):
    body = client.get("/api/paper/stats", headers=operator_headers).json()
    assert body["scope"]["settled"] == 2 and body["scope"]["open"] == 1
    assert body["totals"]["bets"] == {"value": 2, "n": 2}
    assert len(body["cumulative"]) == 2 and body["splits"]["preset"]
    assert client.get("/api/paper/stats?kind=nonsense", headers=operator_headers).status_code == 400


def test_export_endpoints(stats_app, client, operator_headers):
    body = client.get("/api/paper/export", headers=operator_headers).json()
    assert body["entries"] == 3 and len(body["rows"]) == 9 and body["columns"] == analysis.COLUMNS
    settled_only = client.get("/api/paper/export?status=SETTLED", headers=operator_headers).json()
    assert settled_only["entries"] == 2
    response = client.get("/api/paper/export.csv?kind=BET", headers=operator_headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="fb12-paper-bets-')
    parsed = list(csv.DictReader(io.StringIO(response.text)))
    assert len(parsed) == 9 and {r["entry_id"] for r in parsed} == {"pe_20260728T130000_aaa001", "pe_20260728T130000_bbb002", "pe_20260729T130000_ccc003"}
    # The entry route still works and the literal routes are not mistaken for entry ids.
    assert client.get("/api/paper/pe_20260728T130000_aaa001", headers=operator_headers).status_code == 200
