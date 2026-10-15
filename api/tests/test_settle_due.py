"""Settlement without clicks: POST /api/paper/settle-due settles open entries after the off, leaves
the rest, and refreshes BSP from 06:00 UK the next morning at most once an hour."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from services import racing_api
from services.dutch import calculate
from services.paper import BSP_MAX_ATTEMPTS, PaperStore
from services.racing_api import RacingApiClient
from tests.conftest import cloudflare_token

FIXTURES = Path(__file__).parent / "fixtures"
GOODWOOD = json.loads((FIXTURES / "goodwood_results_page.json").read_text(encoding="utf-8"))["results"][0]
RACE = "rac_11991616"
UK = ZoneInfo("Europe/London")
SP = {r["horse"]: (r["horse_id"], float(r["sp_dec"])) for r in GOODWOOD["runners"]}


@pytest.fixture(autouse=True)
def credentials_from_memory(monkeypatch):
    monkeypatch.setattr(racing_api, "get_credential", lambda name: {"racing_api_username": "fb12-user", "racing_api_password": "fb12-pass"}[name])


class Upstream:
    def __init__(self) -> None:
        self.result: dict | None = None
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if request.url.path == f"/v1/results/{RACE}":
            if self.result is None:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json=self.result)
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture
def upstream():
    return Upstream()


@pytest.fixture
def due_app(app, upstream):
    app.state.store.values["request_rate_per_second"] = 5.0
    racing = RacingApiClient(app.state.store, transport=httpx.MockTransport(upstream.handler), base_url="https://racing.test/v1")
    app.state.racing = racing
    app.state.racing_stats = racing.stats
    app.state.paper.racing = racing
    return app


def runner(horse: str, tier: str) -> dict:
    horse_id, price = SP[horse]
    return {"horse_id": horse_id, "horse": horse, "price": price, "tier": tier, "part_fraction": None}


def write_entry(store: PaperStore, entry_id: str, off: datetime, status: str = "OPEN", settlement: dict | None = None) -> None:
    result = calculate(100, 0.02, [runner("Lake Forest (GB)", "PROFIT"), runner("Rogue Diplomat (IRE)", "PROFIT"), runner("Holguin (GB)", "OUT")])
    entry = {
        "entry_id": entry_id, "status": status, "kind": "BET", "trial": False,
        "saved_at": (off - timedelta(hours=1)).isoformat(), "saved_by": "cloud@ascotwm.com",
        "placed_at": (off - timedelta(hours=1)).isoformat(), "placed_by": "cloud@ascotwm.com", "minutes_before_off": 60.0,
        "preset": "top_two", "expected_profit_gbp": None, "expected_profit_pct": None,
        "race": {"race_id": RACE, "race_name": "Lennox Stakes", "course": "Goodwood", "off_dt": off.isoformat(), "pattern": "Group 2"},
        "inputs": {"stake_total": 100, "commission_rate": 0.02, "runners": []},
        "figures": result.to_contract(), "settlement": settlement, "result_summary": None, "raw_card": {}, "raw_result": None,
    }
    asyncio.run(store._write(entry))


def test_due_rules(due_app):
    store = due_app.state.paper
    now = datetime(2026, 7, 28, 15, 10, tzinfo=UK)
    off = datetime(2026, 7, 28, 15, 0, tzinfo=UK)
    item = {"status": "OPEN", "off_dt": off.isoformat()}
    assert store._due(item, now) == (True, "open after the off")
    assert store._due(item, off - timedelta(minutes=5))[0] is False  # not off yet
    assert store._due(item, off + timedelta(seconds=30))[0] is False  # inside the one minute grace
    pending = {"status": "SETTLED", "off_dt": off.isoformat(), "bsp_pending": True, "auto": {}}
    assert store._due(pending, now)[0] is False  # BSP window not open until 06:00 next day
    next_morning = datetime(2026, 7, 29, 6, 0, tzinfo=UK)
    assert store._due(pending, next_morning) == (True, "BSP pending")
    tried = dict(pending, auto={"last_attempt_at": (next_morning - timedelta(minutes=20)).isoformat(), "bsp_attempts": 1})
    assert store._due(tried, next_morning)[0] is False  # once an hour
    exhausted = dict(pending, auto={"bsp_attempts": BSP_MAX_ATTEMPTS})
    assert store._due(exhausted, next_morning) == (False, "BSP attempts exhausted")
    assert store._due({"status": "SETTLED", "off_dt": off.isoformat(), "bsp_pending": False}, now) == (False, "nothing to do")
    assert store._due({"status": "NEEDS_REVIEW", "off_dt": off.isoformat()}, now) == (False, "nothing to do")
    assert store.bsp_window_opens(datetime(2026, 7, 28, 23, 30, tzinfo=UK)) == datetime(2026, 7, 29, 6, 0, tzinfo=UK)


def test_settle_due_settles_open_entries_after_the_off_and_waits_for_results(due_app, client, operator_headers, upstream):
    store = due_app.state.paper
    past_off = datetime.now(UTC) - timedelta(hours=2)
    future_off = datetime.now(UTC) + timedelta(hours=2)
    write_entry(store, "pe_20260728T140000_past01", past_off)
    write_entry(store, "pe_20260728T140000_futur1", future_off)

    # No result yet: the past entry is tried and waits; the future one is not touched.
    first = client.post("/api/paper/settle-due", headers=operator_headers).json()
    assert first["entries"] == 2 and first["due"] == 1 and first["skipped"] == 1
    assert first["settled"] == [] and [w["entry_id"] for w in first["waiting"]] == ["pe_20260728T140000_past01"]
    assert upstream.calls.count(f"/v1/results/{RACE}") == 1
    past = client.get("/api/paper/pe_20260728T140000_past01", headers=operator_headers).json()
    assert past["status"] == "OPEN" and past["auto"]["attempts"] == 1 and past["auto"]["last_outcome"].startswith("NO_RESULT_YET")

    # The result lands: the next run settles it, with BSP in straight away here.
    upstream.result = GOODWOOD
    second = client.post("/api/paper/settle-due", headers=operator_headers).json()
    assert [s["entry_id"] for s in second["settled"]] == ["pe_20260728T140000_past01"]
    assert second["settled"][0]["status"] == "SETTLED" and second["settled"][0]["winner"] == "Lake Forest (GB)"
    past = client.get("/api/paper/pe_20260728T140000_past01", headers=operator_headers).json()
    assert past["status"] == "SETTLED" and past["auto"]["attempts"] == 2 and past["auto"]["last_outcome"] == "SETTLED"
    listing = client.get("/api/paper?status=OPEN", headers=operator_headers).json()["entries"]
    assert [e["entry_id"] for e in listing] == ["pe_20260728T140000_futur1"]

    # Nothing more to do: a third run makes no Racing API call.
    calls_before = len(upstream.calls)
    third = client.post("/api/paper/settle-due", headers=operator_headers).json()
    assert third["due"] == 0 and len(upstream.calls) == calls_before


def test_settle_due_fills_bsp_next_morning(due_app, client, operator_headers, upstream):
    store = due_app.state.paper
    off = datetime.now(UTC) - timedelta(days=2)  # the BSP window opened yesterday morning
    write_entry(store, "pe_20260726T140000_bsp001", off)
    without_bsp = json.loads(json.dumps(GOODWOOD))
    next(r for r in without_bsp["runners"] if r["horse"] == "Lake Forest (GB)")["bsp"] = ""
    upstream.result = without_bsp
    first = client.post("/api/paper/settle-due", headers=operator_headers).json()
    assert first["settled"][0]["bsp_pending"] is True
    # Pending BSP: tried again at most hourly. It was just tried, so nothing is due now.
    second = client.post("/api/paper/settle-due", headers=operator_headers).json()
    assert second["due"] == 0
    # An hour later BSP is in.
    entry = asyncio.run(store._read_entry("pe_20260726T140000_bsp001"))
    entry["auto"]["last_attempt_at"] = (datetime.now(UTC) - timedelta(minutes=61)).isoformat()
    asyncio.run(store._write(entry))
    upstream.result = GOODWOOD
    third = client.post("/api/paper/settle-due", headers=operator_headers).json()
    assert third["bsp_filled"] == ["pe_20260726T140000_bsp001"]
    done = client.get("/api/paper/pe_20260726T140000_bsp001", headers=operator_headers).json()
    assert done["settlement"]["bsp_pending"] is False and done["settlement"]["pnl_at_bsp"] is not None
    assert done["auto"]["bsp_attempts"] == 1 and done["auto"]["attempts"] == 1


def test_settle_due_is_operator_only(due_app, client, keypair, cloudflare_enabled):
    response = client.post("/api/paper/settle-due", headers={"Cf-Access-Jwt-Assertion": cloudflare_token(keypair)})
    assert response.status_code == 401
