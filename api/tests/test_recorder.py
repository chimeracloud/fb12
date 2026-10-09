"""The recorder, end to end over an httpx MockTransport serving real Racing API responses
into an in-memory object store: raw bytes stored untouched, manifests, completeness, retries,
backfill selection, the busy lock and the operator-only endpoint."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from core.errors import ApiError
from core.storage import gunzip_if_needed
from services import racing_api
from services.racing_api import RacingApiClient
from services.recorder import (
    INDEX_KEY, STATE_KEY, cards_key, count_bsp, manifest_key, odds_key, parse_mode, results_key, runners_from_cards,
)
from tests.conftest import cloudflare_token, google_token

FIXTURES = Path(__file__).parent / "fixtures"
CARD = json.loads((FIXTURES / "challenge_stakes_card.json").read_text(encoding="utf-8"))
RESULTS_PAGE = json.loads((FIXTURES / "goodwood_results_page.json").read_text(encoding="utf-8"))
ODDS = json.loads((FIXTURES / "holguin_odds.json").read_text(encoding="utf-8"))
UK = ZoneInfo("Europe/London")


def yesterday_uk() -> date:
    return datetime.now(UK).date() - timedelta(days=1)


class Upstream:
    """Serves the real fixtures and counts what the recorder asked for."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.results_page = RESULTS_PAGE
        self.results_status = 200
        self.odds_status: dict[str, int] = {}
        self.cards_body = json.dumps({"racecards": [CARD], "total": 1, "limit": 500, "skip": 0, "query": []}).encode()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path + ("?" + request.url.query.decode() if request.url.query else ""))
        if path == "/v1/racecards/pro":
            return httpx.Response(200, content=self.cards_body, headers={"content-type": "application/json"})
        if path == "/v1/results":
            if self.results_status != 200:
                return httpx.Response(self.results_status, json={"detail": f"results said {self.results_status}"})
            return httpx.Response(200, json=self.results_page)
        if path.startswith("/v1/odds/"):
            ref = path[len("/v1/odds/"):]
            status = self.odds_status.get(ref, 200)
            if status != 200:
                return httpx.Response(status, json={"detail": f"odds said {status}"})
            return httpx.Response(200, json=ODDS)
        return httpx.Response(404, json={"detail": "Not Found"})

    def count(self, prefix: str) -> int:
        return sum(1 for c in self.calls if c.startswith(prefix))


@pytest.fixture(autouse=True)
def credentials_from_memory(monkeypatch):
    monkeypatch.setattr(racing_api, "get_credential", lambda name: {"racing_api_username": "fb12-user", "racing_api_password": "fb12-pass"}[name])


@pytest.fixture
def upstream():
    return Upstream()


@pytest.fixture
def recorder_app(app, upstream):
    app.state.store.values["request_rate_per_second"] = 5.0
    racing = RacingApiClient(app.state.store, transport=httpx.MockTransport(upstream.handler), base_url="https://racing.test/v1")
    app.state.racing = racing
    app.state.racing_stats = racing.stats
    app.state.recorder.racing = racing
    return app


def test_parse_mode():
    assert parse_mode(None) == ("backfill", None)
    assert parse_mode("backfill") == ("backfill", None)
    assert parse_mode("YESTERDAY") == ("yesterday", None)
    assert parse_mode("2026-10-08") == ("day", date(2026, 10, 8))
    with pytest.raises(ApiError) as excinfo:
        parse_mode("8/10/2026")
    assert excinfo.value.code == "INVALID_INPUT"


def test_keys_and_counts():
    day = date(2026, 10, 8)
    assert cards_key(day) == "cards/2026-10-08.json.gz"
    assert results_key(day, 1) == "results/2026-10-08/page-01.json.gz"
    assert odds_key(day, "rac_1", "hrs_2") == "odds/2026-10-08/rac_1/hrs_2.json.gz"
    assert manifest_key(day) == "manifest/2026-10-08.json"
    assert count_bsp([RESULTS_PAGE]) == (1, 8, 8)
    assert len(runners_from_cards({"racecards": [CARD]})) == 6


def test_backfill_window(recorder_app):
    recorder = recorder_app.state.recorder
    assert recorder.in_backfill_window(datetime(2026, 10, 9, 0, 0, tzinfo=UK)) is True
    assert recorder.in_backfill_window(datetime(2026, 10, 9, 5, 59, tzinfo=UK)) is True
    assert recorder.in_backfill_window(datetime(2026, 10, 9, 6, 0, tzinfo=UK)) is False
    assert recorder.in_backfill_window(datetime(2026, 10, 9, 14, 0, tzinfo=UK)) is False
    # A UTC instant is judged in UK time: 23:30 UTC in summer is 00:30 UK.
    assert recorder.in_backfill_window(datetime(2026, 7, 1, 23, 30, tzinfo=UTC)) is True


def test_records_a_day_raw_and_complete(recorder_app, client, operator_headers, upstream):
    day = yesterday_uk()
    response = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "day" and body["date"] == day.isoformat()
    assert body["complete"] is True and body["skipped"] is False and body["attempts"] == 1
    assert body["counts"] == {
        "cards_races": 1, "cards_runners": 6, "results_races": 1, "results_runners": 8, "results_with_bsp": 8,
        "odds_expected": 6, "odds_done": 6, "odds_missing": 0, "odds_failed": 0,
    }
    assert body["calls"] == 8 and body["errors"] == []

    store = recorder_app.state.recorder.store
    # The cards object is the upstream body byte for byte, gzip-compressed, served as JSON.
    stored, content_type, encoding = store.objects[cards_key(day)]
    assert content_type == "application/json" and encoding == "gzip"
    assert gzip.decompress(stored) == upstream.cards_body
    assert gunzip_if_needed(stored) == upstream.cards_body
    assert json.loads(gzip.decompress(store.objects[results_key(day, 1)][0])) == RESULTS_PAGE
    for runner in CARD["runners"]:
        key = odds_key(day, CARD["race_id"], runner["horse_id"])
        assert json.loads(gzip.decompress(store.objects[key][0])) == ODDS
    manifest = json.loads(store.objects[manifest_key(day)][0])
    assert manifest["complete"] is True
    assert manifest["cards"]["status"] == "ok" and manifest["cards"]["runners"] == 6
    assert manifest["results"]["all_bsp"] is True and manifest["results"]["pages"] == 1
    assert manifest["odds"]["status"] == "ok" and len(manifest["odds"]["done"]) == 6
    assert manifest["runs"][0]["by"] == "cloud@ascotwm.com"
    index = json.loads(store.objects[INDEX_KEY][0])
    assert index["days"][day.isoformat()]["complete"] is True
    # The requests carried the regions and the date as the API wants them.
    assert any(c.startswith("/v1/racecards/pro?date=") and "region_codes=gb&region_codes=ire" in c for c in upstream.calls)
    assert any(c.startswith("/v1/results?start_date=") and "region=gb&region=ire" in c and "limit=100" in c for c in upstream.calls)


def test_complete_day_is_skipped_without_calls(recorder_app, client, operator_headers, upstream):
    day = yesterday_uk()
    assert client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()["complete"] is True
    calls_before = len(upstream.calls)
    second = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()
    assert second["skipped"] is True and second["complete"] is True
    assert len(upstream.calls) == calls_before


def test_missing_bsp_leaves_the_day_incomplete_and_a_retry_refetches_results_only(recorder_app, client, operator_headers, upstream):
    day = yesterday_uk()
    without_bsp = json.loads(json.dumps(RESULTS_PAGE))
    without_bsp["results"][0]["runners"][2]["bsp"] = ""
    upstream.results_page = without_bsp
    first = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()
    assert first["complete"] is False
    assert first["counts"]["results_with_bsp"] == 7
    assert "no BSP yet" in json.loads(recorder_app.state.recorder.store.objects[manifest_key(day)][0])["results"]["detail"]
    assert upstream.count("/v1/racecards") == 1 and upstream.count("/v1/odds") == 6

    upstream.results_page = RESULTS_PAGE
    second = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()
    assert second["complete"] is True and second["attempts"] == 2
    assert upstream.count("/v1/racecards") == 1 and upstream.count("/v1/odds") == 6 and upstream.count("/v1/results") == 2


def test_odds_404_is_missing_not_failed_and_500_leaves_partial(recorder_app, client, operator_headers, upstream):
    day = yesterday_uk()
    upstream.odds_status[f"{CARD['race_id']}/hrs_29228423"] = 404
    upstream.odds_status[f"{CARD['race_id']}/hrs_45855166"] = 500
    recorder_app.state.store.values["retry_on_429_max"] = 0
    body = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()
    assert body["complete"] is False
    assert body["counts"]["odds_missing"] == 1 and body["counts"]["odds_failed"] == 1 and body["counts"]["odds_done"] == 4
    assert body["odds"] == "partial"
    assert any("odds" in e for e in body["errors"])


def test_results_plan_limit_is_recorded_as_unavailable_and_learned(recorder_app, client, operator_headers, upstream):
    day = yesterday_uk()
    upstream.results_status = 403
    body = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()
    assert body["results"] == "unavailable"
    assert body["complete"] is True  # cards and odds are there; results are not offered for that day
    state = json.loads(recorder_app.state.recorder.store.objects[STATE_KEY][0])
    assert state["results_available_from"] == (day + timedelta(days=1)).isoformat()


def test_empty_results_on_a_racing_day_is_not_complete_and_learns_the_boundary(recorder_app, client, operator_headers, upstream):
    day = yesterday_uk()
    upstream.results_page = {"results": [], "total": 0, "limit": 100, "skip": 0, "query": []}
    body = client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers).json()
    assert body["results"] == "empty" and body["complete"] is False
    state = json.loads(recorder_app.state.recorder.store.objects[STATE_KEY][0])
    assert state["results_available_from"] == (day + timedelta(days=1)).isoformat()


def test_backfill_outside_window_records_nothing(recorder_app, client, operator_headers, upstream, monkeypatch):
    monkeypatch.setattr(recorder_app.state.recorder, "in_backfill_window", lambda now=None: False)
    body = client.post("/api/record?date=backfill", headers=operator_headers).json()
    assert body["skipped"] is True and "outside the backfill window" in body["reason"]
    assert upstream.calls == []


def test_backfill_picks_the_newest_unrecorded_day(recorder_app, client, operator_headers, upstream, monkeypatch):
    monkeypatch.setattr(recorder_app.state.recorder, "in_backfill_window", lambda now=None: True)
    first = client.post("/api/record?date=backfill", headers=operator_headers).json()
    assert first["date"] == yesterday_uk().isoformat() and first["complete"] is True
    assert first["remaining_estimate"] > 300
    second = client.post("/api/record", headers=operator_headers).json()
    assert second["date"] == (yesterday_uk() - timedelta(days=1)).isoformat()


def test_yesterday_mode_retries_incomplete_recent_days(recorder_app, client, operator_headers, upstream):
    two_days_ago = yesterday_uk() - timedelta(days=1)
    without_bsp = json.loads(json.dumps(RESULTS_PAGE))
    without_bsp["results"][0]["runners"][0]["bsp"] = ""
    upstream.results_page = without_bsp
    assert client.post(f"/api/record?date={two_days_ago.isoformat()}", headers=operator_headers).json()["complete"] is False
    upstream.results_page = RESULTS_PAGE
    body = client.post("/api/record?date=yesterday", headers=operator_headers).json()
    assert body["mode"] == "yesterday" and body["date"] == yesterday_uk().isoformat() and body["complete"] is True
    assert [r["date"] for r in body["retried"]] == [two_days_ago.isoformat()]
    assert body["retried"][0]["complete"] is True


def test_day_not_over_is_invalid(recorder_app, client, operator_headers):
    today = datetime.now(UK).date().isoformat()
    response = client.post(f"/api/record?date={today}", headers=operator_headers)
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_INPUT"


def test_record_is_operator_only(recorder_app, client, keypair, cloudflare_enabled):
    response = client.post("/api/record?date=2026-10-08", headers={"Cf-Access-Jwt-Assertion": cloudflare_token(keypair)})
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "UNAUTHENTICATED", "message": "Not authenticated."}}
    scheduler = {"Authorization": f"Bearer {google_token(keypair, email='fb12-recorder-scheduler@chiops.iam.gserviceaccount.com')}"}
    assert client.post("/api/record?date=backfill", headers=scheduler).status_code == 200


def test_busy_lock_returns_409(recorder_app, client, operator_headers):
    import asyncio

    recorder = recorder_app.state.recorder
    recorder.current = {"mode": "day", "date": "2026-10-08", "started_at": "now"}

    async def hold_and_call():
        await recorder._lock.acquire()
        try:
            await recorder.record("day", date(2026, 10, 8), by="test")
        finally:
            recorder._lock.release()

    with pytest.raises(ApiError) as excinfo:
        asyncio.run(hold_and_call())
    assert excinfo.value.status_code == 409 and excinfo.value.code == "RECORDER_BUSY"
    recorder.current = None


def test_status_shows_recorder_progress(recorder_app, client, operator_headers):
    day = yesterday_uk()
    client.post(f"/api/record?date={day.isoformat()}", headers=operator_headers)
    status = client.get("/admin/status", headers=operator_headers).json()["recorder"]
    assert status["running"] is False and status["days_complete"] == 1
    assert status["last_run"]["date"] == day.isoformat() and status["last_run"]["complete"] is True
    assert status["bucket"] == "test-recordings"
    assert status["availability"]["odds_from"] == "2025-03-17"
