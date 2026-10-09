"""The Racing API client: auth header, caching, 429 back-off, error mapping, and the two race endpoints
through the app. Upstream answers are served by an httpx MockTransport from the real card fixture."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from core.errors import ApiError
from core.settings import MemoryBackend, SettingsStore
from services import racing_api
from services.racing_api import RacingApiClient

FIXTURE = Path(__file__).parent / "fixtures" / "challenge_stakes_card.json"
CARD = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def fast_store():
    store = SettingsStore(MemoryBackend())
    store.values["request_rate_per_second"] = 5.0
    return store


@pytest.fixture(autouse=True)
def credentials_from_memory(monkeypatch):
    """The credential module is bypassed in tests; the client still sends Basic Auth with what it gets."""
    monkeypatch.setattr(racing_api, "get_credential", lambda name: {"racing_api_username": "fb12-user", "racing_api_password": "fb12-pass"}[name])


def make_client(store, handler):
    return RacingApiClient(store, transport=httpx.MockTransport(handler), base_url="https://racing.test/v1")


def test_sends_basic_auth_and_caches_the_card(fast_store):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=CARD)

    client = make_client(fast_store, handler)

    async def run():
        first = await client.get("/racecards/rac_32300820643/pro", None, cache_kind="race_card", describe="race card")
        second = await client.get("/racecards/rac_32300820643/pro", None, cache_kind="race_card", describe="race card")
        await client.aclose()
        return first, second

    (data1, fetched1), (data2, fetched2) = asyncio.run(run())
    assert len(seen) == 1
    assert seen[0].headers["authorization"].startswith("Basic ")
    assert seen[0].url.path == "/v1/racecards/rac_32300820643/pro"
    assert data1["race_id"] == "rac_32300820643" and data2 is data1 and fetched1 == fetched2
    assert client.stats.calls == 1 and client.stats.cache_hits == 1 and client.stats.cache_entries == 1


def test_region_codes_are_repeated_query_params(fast_store):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"racecards": [CARD], "total": 1, "limit": 500, "skip": 0, "query": []})

    client = make_client(fast_store, handler)
    asyncio.run(client.get("/racecards/pro", {"date": "2026-10-09", "region_codes": ["gb", "ire"]}, cache_kind="race_list", describe="list"))
    assert seen == ["https://racing.test/v1/racecards/pro?date=2026-10-09&region_codes=gb&region_codes=ire"]


def test_429_is_retried_with_retry_after(fast_store):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "Too many requests"})
        return httpx.Response(200, json=CARD)

    client = make_client(fast_store, handler)
    data, _ = asyncio.run(client.get("/racecards/rac_32300820643/pro", None, cache_kind=None, describe="race card"))
    assert data["course"] == "Newmarket"
    assert len(calls) == 2 and client.stats.retries_429 == 1


def test_429_beyond_the_retry_limit_is_an_upstream_error(fast_store):
    fast_store.values["retry_on_429_max"] = 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "Too many requests"})

    client = make_client(fast_store, handler)
    with pytest.raises(ApiError) as excinfo:
        asyncio.run(client.get("/racecards/rac_1/pro", None, cache_kind=None, describe="race card rac_1"))
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "UPSTREAM_ERROR" and excinfo.value.upstream_status == 429


@pytest.mark.parametrize(("status", "code", "http"), [
    (404, "NOT_FOUND", 404),
    (401, "UPSTREAM_ERROR", 502),
    (403, "UPSTREAM_ERROR", 502),
    (500, "UPSTREAM_ERROR", 502),
])
def test_upstream_errors_are_returned_with_their_status_and_body(fast_store, status, code, http):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": f"upstream said {status}"})

    client = make_client(fast_store, handler)
    with pytest.raises(ApiError) as excinfo:
        asyncio.run(client.get("/racecards/rac_1/pro", None, cache_kind=None, describe="race card rac_1"))
    err = excinfo.value
    assert err.status_code == http and err.code == code and err.upstream_status == status
    assert f'{{"detail":"upstream said {status}"}}' in err.message
    if status == 401:
        assert "overdue invoice" in err.message


def test_401_reloads_credentials_once_and_retries(fast_store, monkeypatch):
    """A rotated password: the first 401 makes the client re-read Secret Manager and retry."""
    current = {"creds": ("old-user", "old-pass"), "reloads": 0}

    def fake_get_credential(name):
        return {"racing_api_username": current["creds"][0], "racing_api_password": current["creds"][1]}[name]

    def fake_reload():
        current["reloads"] += 1
        current["creds"] = ("fb12-user", "new-pass")

    monkeypatch.setattr(racing_api, "get_credential", fake_get_credential)
    monkeypatch.setattr(racing_api, "reload_credentials", fake_reload)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        if request.headers["authorization"] == httpx.BasicAuth("old-user", "old-pass")._auth_header:
            return httpx.Response(401, json={"detail": "Invalid credentials"})
        return httpx.Response(200, json=CARD)

    client = make_client(fast_store, handler)
    data, _ = asyncio.run(client.get("/racecards/rac_32300820643/pro", None, cache_kind=None, describe="race card"))
    assert data["course"] == "Newmarket"
    assert len(seen) == 2 and seen[0] != seen[1] and current["reloads"] == 1
    # A second 401 with the fresh credentials is a real error, not a loop: one reload, then the body as is.
    always_401 = make_client(fast_store, lambda r: httpx.Response(401, json={"detail": "Invalid credentials"}))
    with pytest.raises(ApiError) as excinfo:
        asyncio.run(always_401.get("/racecards/rac_1/pro", None, cache_kind=None, describe="race card rac_1"))
    assert excinfo.value.upstream_status == 401 and '{"detail":"Invalid credentials"}' in excinfo.value.message
    assert current["reloads"] == 2


def test_network_failure_is_an_upstream_error(fast_store):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = make_client(fast_store, handler)
    with pytest.raises(ApiError) as excinfo:
        asyncio.run(client.get("/racecards/rac_1/pro", None, cache_kind=None, describe="race card rac_1"))
    assert excinfo.value.code == "UPSTREAM_ERROR" and "did not answer" in excinfo.value.message


def test_missing_credentials_are_reported_not_hidden(fast_store, monkeypatch):
    def failing(name):
        raise racing_api.CredentialError("could not read secret 'racingapi-username': PermissionDenied")

    monkeypatch.setattr(racing_api, "get_credential", failing)
    client = make_client(fast_store, lambda request: httpx.Response(200, json=CARD))
    with pytest.raises(ApiError) as excinfo:
        asyncio.run(client.get("/racecards/rac_1/pro", None, cache_kind=None, describe="race card rac_1"))
    assert excinfo.value.code == "UPSTREAM_ERROR" and "credentials" in excinfo.value.message


# --- through the app -----------------------------------------------------------

@pytest.fixture
def app_with_racing(app):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/racecards/pro":
            return httpx.Response(200, json={"racecards": [CARD], "total": 1, "limit": 500, "skip": 0, "query": []})
        if request.url.path == "/v1/racecards/rac_32300820643/pro":
            return httpx.Response(200, json=CARD)
        return httpx.Response(404, json={"detail": "Not Found"})

    app.state.store.values["request_rate_per_second"] = 5.0
    racing = RacingApiClient(app.state.store, transport=httpx.MockTransport(handler), base_url="https://racing.test/v1")
    app.state.racing = racing
    app.state.racing_stats = racing.stats
    return app


def test_race_list_endpoint(app_with_racing, client, operator_headers):
    response = client.get("/api/races?date=2026-10-09&regions=gb,ire", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == "2026-10-09"
    assert body["races"][0]["race_id"] == "rac_32300820643"
    assert body["races"][0]["off_time_uk"] == "14:25"
    assert client.get("/api/races?date=2026-10-09&pattern_only=true", headers=operator_headers).json()["races"][0]["pattern"] == "Group 2"


def test_race_list_rejects_bad_input(app_with_racing, client, operator_headers):
    for query in ("date=9/10/2026", "date=2026-13-45", "regions=g b", "regions=,"):
        response = client.get(f"/api/races?{query}", headers=operator_headers)
        assert response.status_code == 400, query
        assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_race_card_endpoint(app_with_racing, client, operator_headers):
    response = client.get("/api/races/rac_32300820643", headers=operator_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["race"]["course"] == "Newmarket"
    assert len(body["runners"]) == 6
    assert body["runners"][4]["horse"] == "Flora of Bermuda" and body["runners"][4]["exchange_price"] == 2.78
    assert body["fetched_at"]


def test_race_card_not_found_and_bad_id(app_with_racing, client, operator_headers):
    response = client.get("/api/races/rac_0", headers=operator_headers)
    assert response.status_code == 404
    assert response.json()["error"] == {"code": "NOT_FOUND", "message": 'The Racing API has no race card rac_0: {"detail":"Not Found"}.', "upstream_status": 404}
    assert client.get("/api/races/nonsense", headers=operator_headers).status_code == 400


def test_status_reports_racing_api_counters(app_with_racing, client, operator_headers):
    client.get("/api/races/rac_32300820643", headers=operator_headers)
    body = client.get("/admin/status", headers=operator_headers).json()
    assert body["racing_api"]["calls"] == 1 and body["racing_api"]["last_status"] == 200
