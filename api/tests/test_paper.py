"""Paper entries: saved from the real Challenge Stakes card with the brief's cautious version,
listed, read back without the raw responses, and settled. The settlement maths is proven on
the real Goodwood result (Lennox Stakes, 28 July 2026) with its real SPs and BSPs."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from core.errors import ApiError
from models.schemas import PaperList, SettleResponse
from services import racing_api
from services.dutch import calculate
from services.paper import PaperStore, entry_key
from services.racing_api import RacingApiClient

FIXTURES = Path(__file__).parent / "fixtures"
CARD = json.loads((FIXTURES / "challenge_stakes_card.json").read_text(encoding="utf-8"))
GOODWOOD = json.loads((FIXTURES / "goodwood_results_page.json").read_text(encoding="utf-8"))["results"][0]
RACE = "rac_32300820643"

CAUTIOUS = {
    "race_id": RACE,
    "stake_total": 100,
    "commission_rate": 0.02,
    "runners": [
        {"horse_id": "hrs_35445375", "price": 2.94, "card_price": 2.78, "price_edited": True, "tier": "PROFIT"},
        {"horse_id": "hrs_52830953", "price": 4.1, "card_price": 5.3, "price_edited": True, "tier": "PROFIT"},
        {"horse_id": "hrs_35625688", "price": 6.0, "card_price": 5.7, "price_edited": True, "tier": "BREAK_EVEN"},
        {"horse_id": "hrs_45855166", "price": 7.6, "card_price": 7.2, "price_edited": True, "tier": "BREAK_EVEN"},
        {"horse_id": "hrs_35149667", "price": 11, "card_price": 10, "price_edited": True, "tier": "PART", "part_fraction": 0.5},
        {"horse_id": "hrs_29228423", "price": 17.5, "card_price": 17.5, "price_edited": False, "tier": "OUT"},
    ],
}


@pytest.fixture(autouse=True)
def credentials_from_memory(monkeypatch):
    monkeypatch.setattr(racing_api, "get_credential", lambda name: {"racing_api_username": "fb12-user", "racing_api_password": "fb12-pass"}[name])


class Upstream:
    def __init__(self) -> None:
        self.result: dict | None = None  # None: not published yet
        self.card: dict = CARD
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if request.url.path == f"/v1/racecards/{RACE}/pro":
            return httpx.Response(200, json=self.card)
        if request.url.path == f"/v1/results/{RACE}":
            if self.result is None:
                return httpx.Response(404, json={"detail": "Not Found"})
            return httpx.Response(200, json=self.result)
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture
def upstream():
    return Upstream()


@pytest.fixture
def paper_app(app, upstream):
    app.state.store.values["request_rate_per_second"] = 5.0
    racing = RacingApiClient(app.state.store, transport=httpx.MockTransport(upstream.handler), base_url="https://racing.test/v1")
    app.state.racing = racing
    app.state.racing_stats = racing.stats
    app.state.paper.racing = racing
    return app


def test_save_list_and_read_back(paper_app, client, operator_headers):
    created = client.post("/api/paper", json=CAUTIOUS, headers=operator_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == {"entry_id", "status", "saved_at", "saved_by", "kind", "minutes_before_off"}
    assert body["status"] == "OPEN" and body["saved_by"] == "cloud@ascotwm.com" and body["entry_id"].startswith("pe_")
    assert body["kind"] == "TRIAL"  # typed prices: a trial, kept out of the totals
    entry_id = body["entry_id"]

    listing = client.get("/api/paper", headers=operator_headers).json()
    PaperList.model_validate(listing)
    assert len(listing["entries"]) == 1
    item = listing["entries"][0]
    assert item["entry_id"] == entry_id and item["status"] == "OPEN" and item["course"] == "Newmarket"
    assert item["race_name"].startswith("Thoroughbred Industry") and item["off_dt"] == "2026-10-09T14:25:00+01:00"
    assert item["pnl"] is None and item["bsp_pending"] is None and item["review_reason"] is None
    assert item["kind"] == "TRIAL" and item["pattern"] == "Group 2" and item["stake_total"] == 100 and item["preset"] == "custom"
    assert item["expected_profit_gbp"] == pytest.approx(-2.94, abs=0.005)
    assert client.get("/api/paper?kind=TRIAL", headers=operator_headers).json()["entries"][0]["entry_id"] == entry_id
    assert client.get("/api/paper?kind=BET", headers=operator_headers).json()["entries"] == []
    assert client.get("/api/paper?status=OPEN", headers=operator_headers).json()["entries"][0]["entry_id"] == entry_id
    assert client.get("/api/paper?status=SETTLED", headers=operator_headers).json()["entries"] == []
    assert client.get("/api/paper?status=nonsense", headers=operator_headers).status_code == 400

    entry = client.get(f"/api/paper/{entry_id}", headers=operator_headers).json()
    assert "raw_card" not in entry and "raw_result" not in entry
    assert entry["saved_by"] == "cloud@ascotwm.com" and entry["status"] == "OPEN"
    assert entry["inputs"]["stake_total"] == 100 and entry["inputs"]["commission_rate"] == 0.02
    flora = next(r for r in entry["inputs"]["runners"] if r["horse_id"] == "hrs_35445375")
    assert flora == {"horse_id": "hrs_35445375", "horse": "Flora of Bermuda", "price": 2.94, "card_price": 2.78,
                     "card_price_at_save": 2.78, "card_price_updated_at_save": "2026-10-09T09:53:06+01:00",
                     "price_edited": True, "tier": "PROFIT", "part_fraction": None}
    assert entry["kind"] == "TRIAL" and entry["trial"] is True and entry["placed_by"] == "cloud@ascotwm.com"
    assert entry["race"]["pattern"] == "Group 2" and entry["race"]["field_size"] == 6
    assert entry["expected_profit_gbp"] == entry["figures"]["expected_value_gbp"]
    # The figures are the calculate function's, not anything the browser sent.
    expected = calculate(100, 0.02, [
        {"horse_id": r["horse_id"], "horse": next(c["horse"] for c in CARD["runners"] if c["horse_id"] == r["horse_id"]),
         "price": r["price"], "tier": r["tier"], "part_fraction": r.get("part_fraction")} for r in CAUTIOUS["runners"]
    ]).to_contract()
    assert entry["figures"] == expected
    assert entry["figures"]["profit_per_win"] == pytest.approx(12.37, abs=0.005)
    # The stored object carries the card exactly as FB12 saw it.
    stored = json.loads(paper_app.state.paper.store.objects[entry_key(entry_id)][0])
    assert stored["raw_card"] == CARD and stored["raw_result"] is None
    assert stored["race"]["card_fetched_at"]


def live_bet(off_dt: str | None = None, preset: str | None = "top_two") -> dict:
    """The dutch at the card's live exchange prices: Flora and Time To Turn PROFIT, the rest OUT."""
    prices = {r["horse_id"]: next(o for o in r["odds"] if o["bookmaker"] == "Betfair Exchange")["decimal"] for r in CARD["runners"]}
    tiers = {"hrs_35445375": "PROFIT", "hrs_52830953": "PROFIT"}
    body = {
        "race_id": RACE, "stake_total": 50, "commission_rate": 0.02, "preset": preset,
        "runners": [{"horse_id": hid, "price": float(p), "card_price": float(p), "price_edited": False, "tier": tiers.get(hid, "OUT")}
                    for hid, p in prices.items()],
    }
    return body


@pytest.fixture
def future_card(upstream):
    """The same real card with its off time moved to tomorrow, so a bet is before the off."""
    from datetime import datetime, timedelta, timezone

    future = json.loads(json.dumps(CARD))
    off = datetime.now(timezone.utc) + timedelta(hours=26)
    future["off_dt"] = off.isoformat(timespec="seconds")
    future["date"] = off.date().isoformat()
    upstream.card = future
    return future


def test_live_prices_place_a_bet_with_its_timing(paper_app, client, operator_headers, upstream, future_card):
    created = client.post("/api/paper", json=live_bet(), headers=operator_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "BET"
    assert 25 * 60 < body["minutes_before_off"] <= 26 * 60
    entry = client.get(f"/api/paper/{body['entry_id']}", headers=operator_headers).json()
    assert entry["kind"] == "BET" and entry["trial"] is False and entry["preset"] == "top_two"
    assert entry["placed_at"] == entry["saved_at"] and entry["placed_by"] == "cloud@ascotwm.com"
    assert entry["minutes_before_off"] == body["minutes_before_off"]
    flora = next(r for r in entry["inputs"]["runners"] if r["horse_id"] == "hrs_35445375")
    assert flora["price"] == 2.78 and flora["card_price_at_save"] == 2.78 and flora["price_edited"] is False
    assert entry["figures"]["feasible"] is True
    listing = client.get("/api/paper?kind=BET", headers=operator_headers).json()["entries"]
    assert listing[0]["kind"] == "BET" and listing[0]["minutes_before_off"] == body["minutes_before_off"]


def test_bets_after_the_off_are_refused_but_trials_are_not(paper_app, client, operator_headers):
    # The real card: off 14:25 UK on 9 October 2026, which is in the past for every build after it.
    refused = client.post("/api/paper", json=live_bet(), headers=operator_headers)
    assert refused.status_code == 400
    assert "went off at 14:25 UK; bets after the off are refused" in refused.json()["error"]["message"]
    assert client.get("/api/paper", headers=operator_headers).json()["entries"] == []
    trial = client.post("/api/paper", json=CAUTIOUS, headers=operator_headers)
    assert trial.status_code == 201 and trial.json()["kind"] == "TRIAL"
    assert trial.json()["minutes_before_off"] < 0


def test_preset_is_validated(paper_app, client, operator_headers, future_card):
    assert client.post("/api/paper", json=live_bet(preset="nonsense"), headers=operator_headers).status_code == 400
    assert client.post("/api/paper", json=live_bet(preset=None), headers=operator_headers).json()["kind"] == "BET"
    entries = client.get("/api/paper", headers=operator_headers).json()["entries"]
    assert entries[0]["preset"] == "custom"


def test_save_rejects_bad_entries(paper_app, client, operator_headers):
    unknown = dict(CAUTIOUS, runners=CAUTIOUS["runners"] + [{"horse_id": "hrs_0", "price": 5.0, "tier": "OUT"}])
    response = client.post("/api/paper", json=unknown, headers=operator_headers)
    assert response.status_code == 400 and "hrs_0 is not on the card" in response.json()["error"]["message"]
    infeasible = dict(CAUTIOUS, runners=[dict(r, tier="OUT" if r["tier"] == "PROFIT" else r["tier"]) for r in CAUTIOUS["runners"]])
    response = client.post("/api/paper", json=infeasible, headers=operator_headers)
    assert response.status_code == 400 and "not feasible" in response.json()["error"]["message"]
    assert client.post("/api/paper", json=dict(CAUTIOUS, extra=1), headers=operator_headers).status_code == 400
    assert client.get("/api/paper", headers=operator_headers).json()["entries"] == []
    assert client.get("/api/paper/nonsense", headers=operator_headers).status_code == 400
    assert client.get("/api/paper/pe_20260101T000000_abcdef", headers=operator_headers).status_code == 404


def test_settle_before_the_result_is_409_and_leaves_the_entry_open(paper_app, client, operator_headers):
    entry_id = client.post("/api/paper", json=CAUTIOUS, headers=operator_headers).json()["entry_id"]
    response = client.post(f"/api/paper/{entry_id}/settle", headers=operator_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_RESULT_YET"
    assert "not published yet" in response.json()["error"]["message"]
    assert client.get(f"/api/paper/{entry_id}", headers=operator_headers).json()["status"] == "OPEN"


def test_settle_marks_review_when_entry_runners_are_not_in_the_result(paper_app, client, operator_headers, upstream):
    """A result whose runners are not the entry's runners (here the real Goodwood result) means the
    saved stakes no longer describe the race: NEEDS_REVIEW, no automatic P&L, raw result kept."""
    entry_id = client.post("/api/paper", json=CAUTIOUS, headers=operator_headers).json()["entry_id"]
    upstream.result = GOODWOOD
    response = client.post(f"/api/paper/{entry_id}/settle", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    SettleResponse.model_validate(body)
    assert body["status"] == "NEEDS_REVIEW" and body["pnl"] is None and body["pnl_at_sp"] is None
    assert "Flora of Bermuda" in body["review_reason"] and "not in the result" in body["review_reason"]
    stored = json.loads(paper_app.state.paper.store.objects[entry_key(entry_id)][0])
    assert stored["raw_result"] == GOODWOOD and stored["result_summary"]["winner"] == "Lake Forest (GB)"
    listing = client.get("/api/paper?status=NEEDS_REVIEW", headers=operator_headers).json()["entries"]
    assert listing[0]["entry_id"] == entry_id and listing[0]["review_reason"] == body["review_reason"]


def goodwood_entry(runners: list[dict], stake: float = 100, commission: float = 0.02) -> dict:
    """An entry on the Lennox Stakes at its real SPs, as PaperStore would store it."""
    result = calculate(stake, commission, runners)
    assert result.feasible, result.message
    return {
        "entry_id": "pe_test", "status": "OPEN",
        "inputs": {"stake_total": stake, "commission_rate": commission, "runners": runners},
        "figures": result.to_contract(),
    }


SP = {r["horse"]: (r["horse_id"], float(r["sp_dec"])) for r in GOODWOOD["runners"]}


def runner(horse: str, tier: str, part_fraction: float | None = None) -> dict:
    horse_id, price = SP[horse]
    return {"horse_id": horse_id, "horse": horse, "price": price, "tier": tier, "part_fraction": part_fraction}


def test_work_out_pays_the_winner_at_saved_prices_and_at_sp_and_bsp():
    entry = goodwood_entry([
        runner("Lake Forest (GB)", "PROFIT"), runner("Rogue Diplomat (IRE)", "PROFIT"),
        runner("Witness Stand (GB)", "BREAK_EVEN"), runner("Qirat (GB)", "BREAK_EVEN"),
        runner("Holguin (GB)", "PART", 0.5), runner("Marvelman (IRE)", "OUT"),
        runner("Poet Master (IRE)", "OUT"), runner("Lord Britain (GB)", "OUT"),
    ])
    settlement = PaperStore.work_out(entry, GOODWOOD)
    lake = next(r for r in entry["figures"]["runners"] if r["horse"] == "Lake Forest (GB)")
    assert settlement["status"] == "SETTLED" and settlement["winner"] == "Lake Forest (GB)"
    assert settlement["winner_tier"] == "PROFIT" and settlement["winner_in_entry"] is True
    # Paid at the saved price with the saved stake: the entry's own net for that runner.
    assert settlement["pnl"] == lake["net_if_wins"] == entry["figures"]["profit_per_win"]
    assert settlement["pnl_after_commission"] == pytest.approx(lake["net_if_wins"] * 0.98, abs=0.005)
    # Same saved stake at bookmaker SP 1.91 (the saved price here, so the same figure), no commission.
    assert settlement["pnl_at_sp"] == pytest.approx(lake["stake"] * 1.91 - 100, abs=0.01)
    assert settlement["pnl_at_sp_after_commission"] == pytest.approx((lake["stake"] * 1.91 - 100) * 0.98, abs=0.01)
    # And at BSP 2.05, before and after commission.
    assert settlement["pnl_at_bsp"] == pytest.approx(lake["stake"] * 2.05 - 100, abs=0.01)
    assert settlement["pnl_at_bsp_after_commission"] == pytest.approx((lake["stake"] * 2.05 - 100) * 0.98, abs=0.01)
    assert settlement["bsp_pending"] is False and settlement["review_reason"] is None


def test_work_out_bsp_pending_then_filled():
    entry = goodwood_entry([runner("Lake Forest (GB)", "PROFIT"), runner("Rogue Diplomat (IRE)", "PROFIT"), runner("Holguin (GB)", "OUT")])
    without_bsp = json.loads(json.dumps(GOODWOOD))
    next(r for r in without_bsp["runners"] if r["horse"] == "Lake Forest (GB)")["bsp"] = ""
    first = PaperStore.work_out(entry, without_bsp)
    assert first["status"] == "SETTLED" and first["bsp_pending"] is True
    assert first["pnl"] is not None and first["pnl_at_sp"] is not None
    assert first["pnl_at_bsp"] is None and first["pnl_at_bsp_after_commission"] is None
    later = PaperStore.work_out(entry, GOODWOOD)
    assert later["bsp_pending"] is False and later["pnl_at_bsp"] is not None
    assert later["pnl"] == first["pnl"]  # the saved-price P&L never moves


def test_work_out_loss_when_the_winner_is_not_in_the_entry_or_is_out():
    out_entry = goodwood_entry([runner("Witness Stand (GB)", "PROFIT"), runner("Qirat (GB)", "PROFIT"), runner("Lake Forest (GB)", "OUT")])
    settlement = PaperStore.work_out(out_entry, GOODWOOD)
    assert settlement["status"] == "SETTLED" and settlement["winner_tier"] == "OUT"
    assert settlement["pnl"] == -100.0 and settlement["pnl_after_commission"] == -100.0
    assert settlement["pnl_at_sp"] == -100.0 and settlement["pnl_at_bsp"] == -100.0  # a zero stake wins nothing at any price
    assert settlement["pnl_at_sp_after_commission"] == -100.0
    absent = goodwood_entry([runner("Witness Stand (GB)", "PROFIT"), runner("Qirat (GB)", "PROFIT")])
    settlement = PaperStore.work_out(absent, GOODWOOD)
    assert settlement["winner_in_entry"] is False and settlement["pnl"] == -100.0 and settlement["winner_stake"] == 0.0


def test_work_out_dead_heat_and_non_runner_need_review():
    entry = goodwood_entry([runner("Lake Forest (GB)", "PROFIT"), runner("Rogue Diplomat (IRE)", "PROFIT"), runner("Holguin (GB)", "OUT")])
    dead_heat = json.loads(json.dumps(GOODWOOD))
    next(r for r in dead_heat["runners"] if r["horse"] == "Rogue Diplomat (IRE)")["position"] = "1"
    settlement = PaperStore.work_out(entry, dead_heat)
    assert settlement["status"] == "NEEDS_REVIEW" and settlement["review_reason"].startswith("Dead heat between")
    assert settlement["pnl"] is None and settlement["pnl_at_sp"] is None
    withdrawn = json.loads(json.dumps(GOODWOOD))
    withdrawn["runners"] = [r for r in withdrawn["runners"] if r["horse"] != "Holguin (GB)"]
    withdrawn["non_runners"] = "Holguin (GB)"
    settlement = PaperStore.work_out(entry, withdrawn)
    assert settlement["status"] == "NEEDS_REVIEW" and "Holguin (GB) was not in the result" in settlement["review_reason"]


def test_settle_twice_is_idempotent_once_bsp_is_in(paper_app, upstream):
    """Through the store: a settled entry with BSP in is not re-fetched."""
    import asyncio

    store = paper_app.state.paper
    entry = goodwood_entry([runner("Lake Forest (GB)", "PROFIT"), runner("Rogue Diplomat (IRE)", "PROFIT"), runner("Holguin (GB)", "OUT")])
    entry.update({"entry_id": "pe_20260728T150000_abc123", "saved_at": "2026-07-28T13:00:00+00:00", "saved_by": "cloud@ascotwm.com",
                  "kind": "BET", "trial": False, "placed_at": "2026-07-28T13:00:00+00:00", "placed_by": "cloud@ascotwm.com",
                  "minutes_before_off": 60.0, "preset": "custom", "expected_profit_gbp": None, "expected_profit_pct": None,
                  "race": {"race_id": RACE, "race_name": "Lennox Stakes", "course": "Goodwood", "off_dt": "2026-07-28T15:00:00+01:00", "pattern": "Group 2"},
                  "settlement": None, "result_summary": None, "raw_card": {}, "raw_result": None})

    async def run():
        await store._write(entry)
        upstream.result = GOODWOOD
        first = await store.settle(entry["entry_id"])
        calls_after_first = upstream.calls.count(f"/v1/results/{RACE}")
        second = await store.settle(entry["entry_id"])
        return first, second, calls_after_first, upstream.calls.count(f"/v1/results/{RACE}")

    first, second, calls_after_first, calls_after_second = asyncio.run(run())
    assert first["status"] == "SETTLED" and first["bsp_pending"] is False
    assert second == first and calls_after_second == calls_after_first == 1
