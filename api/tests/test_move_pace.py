"""Move and pace on real Racing API data: Holguin's odds history of 9 October 2026 and his
two most recent past runs, plus the real running comments of the other runners."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from core.settings import PACE_HELD_UP, PACE_LED, PACE_MIDFIELD, PACE_PROMINENT
from models.schemas import MoveResponse, PaceResponse
from services import racing_api
from services.move import compute_move, usable_price
from services.pace import classify, compute_pace, normalise
from services.racing_api import RacingApiClient

FIXTURES = Path(__file__).parent / "fixtures"
ODDS = json.loads((FIXTURES / "holguin_odds.json").read_text(encoding="utf-8"))
PAST_RUNS = json.loads((FIXTURES / "holguin_past_runs.json").read_text(encoding="utf-8"))
CARD = json.loads((FIXTURES / "challenge_stakes_card.json").read_text(encoding="utf-8"))
RACE_DAY = date(2026, 10, 9)
LISTS = {"LED": PACE_LED, "PROMINENT": PACE_PROMINENT, "HELD_UP": PACE_HELD_UP, "MIDFIELD": PACE_MIDFIELD}
HOLGUIN = "hrs_29228423"


# --- move ---------------------------------------------------------------------------

def test_usable_price_skips_sp_and_dashes():
    assert usable_price("15") == 15.0
    assert usable_price("SP") is None and usable_price("sp") is None
    assert usable_price("-") is None and usable_price("") is None and usable_price(None) is None
    assert usable_price("1.0") is None


def test_move_uses_the_bookmaker_median_with_the_evening_price_carried_to_race_day():
    move = compute_move(HOLGUIN, ODDS, RACE_DAY)
    MoveResponse.model_validate(move)
    assert move["source"] == "bookmaker median"
    # Bet365 is the only bookmaker with history: 11 at midnight the day before, 12 at 17:13,
    # then 15, 17, 15 on race day. Start of race day carries 12 forward; latest is 15 at 09:26.
    assert move["first_price"] == 12.0 and move["first_at"] == "2026-10-09T00:00:00+01:00"
    assert move["latest_price"] == 15.0 and move["latest_at"] == "2026-10-09T09:26:00+01:00"
    assert move["change_pct"] == 25.0 and move["direction"] == "drifted"
    assert move["note"] == "median of 1 bookmakers with history"


def test_move_falls_back_to_the_exchange_inside_the_bookmaker_range():
    odds = json.loads(json.dumps(ODDS))
    bet365 = next(o for o in odds["odds"] if o["bookmaker"] == "Bet365")
    bet365["history"] = []  # no bookmaker has history any more
    # A second bookmaker's current price (Betfair Sportsbook 19 on the 09:53 card) bounds the exchange.
    odds["odds"].append({"bookmaker": "Betfair Sportsbook", "fractional": "18/1", "decimal": "19", "ew_places": "", "ew_denom": "", "updated": "2026-10-09 09:53:06", "history": []})
    move = compute_move(HOLGUIN, odds, RACE_DAY)
    MoveResponse.model_validate(move)
    assert move["source"] == "Betfair Exchange"
    # Range [15, 19]: 13 and 13.5 on the day before are dropped; 17, 17, 17.5 on race day stay.
    assert move["first_price"] == 17.0 and move["first_at"] == "2026-10-09T09:36:00+01:00"
    assert move["latest_price"] == 17.5 and move["latest_at"] == "2026-10-09T09:38:00+01:00"
    assert move["change_pct"] == 2.94 and move["direction"] == "drifted"
    assert "2 exchange prices outside the bookmaker range dropped" in move["note"]


def test_move_with_no_history_says_so():
    odds = json.loads(json.dumps(ODDS))
    for o in odds["odds"]:
        o["history"] = []
    move = compute_move(HOLGUIN, odds, RACE_DAY)
    assert move["source"] is None and move["first_price"] is None and move["direction"] is None
    assert move["note"] == "no price history"
    empty = compute_move(HOLGUIN, {"odds": []}, RACE_DAY)
    assert empty["note"].startswith("no price history")


def test_move_unchanged_and_shortened():
    odds = json.loads(json.dumps(ODDS))
    bet365 = next(o for o in odds["odds"] if o["bookmaker"] == "Bet365")
    bet365["history"] = [{"changed_at": "2026-10-09T09:00:00+01:00", "fractional": "14/1", "decimal": "15"},
                         {"changed_at": "2026-10-08T20:00:00+01:00", "fractional": "14/1", "decimal": "15"}]
    assert compute_move(HOLGUIN, odds, RACE_DAY)["direction"] == "unchanged"
    bet365["history"] = [{"changed_at": "2026-10-09T09:00:00+01:00", "fractional": "10/1", "decimal": "11"},
                         {"changed_at": "2026-10-08T20:00:00+01:00", "fractional": "14/1", "decimal": "15"}]
    move = compute_move(HOLGUIN, odds, RACE_DAY)
    assert move["direction"] == "shortened" and move["change_pct"] == pytest.approx(-26.67, abs=0.005)


# --- pace ---------------------------------------------------------------------------

def test_normalise():
    assert normalise("Held up towards the back - made headway 2f out") == "held up towards the back made headway 2f out"
    assert normalise("raced in mid-division - driven") == "raced in mid division driven"
    assert normalise("") == "" and normalise(None) == ""


@pytest.mark.parametrize(("comment", "category"), [
    ("Held up towards the back - made headway 2f out - driven approaching final furlong - kept on same gait to the line finishing 5th", "HELD_UP"),
    ("pulled hard early - raced handy - driven into the front over 1f out - continued well in the final furlong", "PROMINENT"),
    ("Set the pace early - driven on approaching 2f out to stretch clear", "LED"),
    ("made the running - roused along 2f out - drifted right and was overtaken over 1f out", "LED"),
    ("raced in mid-division - driven over 1f out - made late progress in the final furlong", "MIDFIELD"),
    ("Took strong hold in midfield - urged forward with over 2f to run", "MIDFIELD"),
    ("Sat close to the pace - asked for effort 2f out - weakened inside final furlong to finish sixth", "PROMINENT"),
    ("travelled wide and close up - driven over 2f out - faded quickly", "PROMINENT"),
    ("settled off the pace - driven 2f out - made headway 1f out", "HELD_UP"),
    ("settled towards the back - pressed for a response over 2f out - not a factor throughout", "HELD_UP"),
    ("Settled just behind the leader - urged forward with 2f left and battled on", "UNCLASSIFIED"),
    ("Steered right early - settled towards back - urged forward past the furlong marker", "UNCLASSIFIED"),
    ("settled early in rear, then held up", "HELD_UP"),  # 'settled early' is not 'led early': whole phrases only
    ("Prominent, pressed leader 2f out", "PROMINENT"),  # punctuation is not a barrier
    ("", "UNCLASSIFIED"),
    (None, "UNCLASSIFIED"),
])
def test_classify_real_comments(comment, category):
    assert classify(comment, LISTS) == category


def test_first_match_wins_in_list_order():
    # A comment with both a LED phrase and a HELD_UP phrase is LED: the lists are checked in order.
    assert classify("led early but held up after the second", LISTS) == "LED"
    custom = {"LED": ["bounced out"], "PROMINENT": [], "HELD_UP": ["held up"], "MIDFIELD": []}
    assert classify("Bounced out to lead - held up later", custom) == "LED"


def test_compute_pace_for_holguin():
    pace = compute_pace(HOLGUIN, PAST_RUNS, LISTS, 5)
    PaceResponse.model_validate(pace)
    assert pace["counts"] == {"LED": 0, "PROMINENT": 1, "MIDFIELD": 0, "HELD_UP": 1, "UNCLASSIFIED": 0}
    assert [r["date"] for r in pace["runs"]] == ["2026-07-28", "2026-07-11"]  # newest first
    goodwood, chester = pace["runs"]
    assert goodwood["course"] == "Goodwood" and goodwood["position"] == "5" and goodwood["class"] == "Class 1"
    assert goodwood["comment"].startswith("Held up towards the back") and goodwood["category"] == "HELD_UP"
    assert chester["course"] == "Chester" and chester["position"] == "3" and chester["category"] == "PROMINENT"
    assert chester["comment"] == PAST_RUNS["results"][1]["runners"][2]["comment"]  # raw text, untouched


def test_compute_pace_limits_runs_and_handles_no_runs():
    one = compute_pace(HOLGUIN, PAST_RUNS, LISTS, 1)
    assert len(one["runs"]) == 1 and one["counts"]["HELD_UP"] == 1 and one["counts"]["PROMINENT"] == 0
    none = compute_pace(HOLGUIN, {"results": [], "total": 0}, LISTS, 5)
    assert none["runs"] == [] and sum(none["counts"].values()) == 0


# --- through the app --------------------------------------------------------------------

@pytest.fixture(autouse=True)
def credentials_from_memory(monkeypatch):
    monkeypatch.setattr(racing_api, "get_credential", lambda name: {"racing_api_username": "fb12-user", "racing_api_password": "fb12-pass"}[name])


@pytest.fixture
def app_with_history(app):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path == "/v1/racecards/rac_32300820643/pro":
            return httpx.Response(200, json=CARD)
        if path == f"/v1/odds/rac_32300820643/{HOLGUIN}":
            return httpx.Response(200, json=ODDS)
        if path == f"/v1/horses/{HOLGUIN}/results":
            return httpx.Response(200, json=PAST_RUNS)
        return httpx.Response(404, json={"detail": "Not Found"})

    app.state.store.values["request_rate_per_second"] = 5.0
    racing = RacingApiClient(app.state.store, transport=httpx.MockTransport(handler), base_url="https://racing.test/v1")
    app.state.racing = racing
    app.state.racing_stats = racing.stats
    app.state.seen = seen
    return app


def test_move_endpoint(app_with_history, client, operator_headers):
    response = client.get(f"/api/races/rac_32300820643/runners/{HOLGUIN}/move", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "bookmaker median" and body["change_pct"] == 25.0 and body["direction"] == "drifted"
    assert set(body) == {"horse_id", "source", "first_price", "first_at", "latest_price", "latest_at", "change_pct", "direction", "note"}


def test_pace_endpoint_asks_for_runs_before_the_race_day(app_with_history, client, operator_headers):
    response = client.get(f"/api/races/rac_32300820643/runners/{HOLGUIN}/pace", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["HELD_UP"] == 1 and body["counts"]["PROMINENT"] == 1
    assert body["runs"][0]["class"] == "Class 1" and "race_class" not in body["runs"][0]
    asked = [u for u in app_with_history.state.seen if "/horses/" in u][0]
    assert "end_date=2026-10-08" in asked and "start_date=2000-01-01" in asked and "limit=5" in asked
    three = client.get(f"/api/races/rac_32300820643/runners/{HOLGUIN}/pace?runs=3", headers=operator_headers)
    assert three.status_code == 200
    assert any("limit=3" in u for u in app_with_history.state.seen)


def test_move_and_pace_reject_bad_ids(app_with_history, client, operator_headers):
    assert client.get("/api/races/rac_32300820643/runners/nonsense/move", headers=operator_headers).status_code == 400
    assert client.get("/api/races/rac_32300820643/runners/hrs_1/pace?runs=0", headers=operator_headers).status_code == 400
    missing = client.get("/api/races/rac_32300820643/runners/hrs_404/move", headers=operator_headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
