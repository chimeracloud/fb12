"""Every admin endpoint of ADR 010 answers 200 with an operator token, and behaves."""

from __future__ import annotations

import asyncio

from core.settings import MASK
from tests.conftest import OPERATOR

ADMIN_GETS = ["/admin/health", "/admin/status", "/admin/settings", "/admin/config", "/admin/logs"]


def test_admin_gets_return_200(client, operator_headers):
    for path in ADMIN_GETS:
        response = client.get(path, headers=operator_headers)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("application/json")


def test_health_shape(client, operator_headers):
    body = client.get("/admin/health", headers=operator_headers).json()
    assert body["status"] == "ok"
    assert body["service"] == "fb12-dutch-api"
    assert body["unit"] == "FB12"
    assert "version" in body and "time" in body and "uptime_seconds" in body


def test_status_shape(client, operator_headers):
    client.get("/admin/health", headers=operator_headers)  # counted once its response is sent
    body = client.get("/admin/status", headers=operator_headers).json()
    assert body["mode"] == "paper"
    assert body["requests"]["total"] >= 1
    assert body["access"]["accepted"]["google_id_token"] >= 1
    assert body["credentials"] == {"racing_api_username": "not loaded", "racing_api_password": "not loaded"}
    assert set(body["settings"]) == {"source", "updated_at", "updated_by", "last_error"}


def test_settings_form_masks_credentials_and_lists_groups(client, operator_headers):
    body = client.get("/admin/settings", headers=operator_headers).json()
    groups = {g["id"]: g for g in body["groups"]}
    assert set(groups) == {"dutch", "racing", "cache", "pace", "recorder", "credentials"}
    by_key = {f["key"]: f for g in body["groups"] for f in g["fields"]}
    assert by_key["commission_rate"]["value"] == 0.02
    assert by_key["default_stake"]["value"] == 100.0
    assert by_key["default_part_fraction"]["value"] == 0.5
    assert by_key["past_runs"]["value"] == 5
    assert by_key["regions"]["value"] == ["gb", "ire"]
    assert by_key["request_rate_per_second"]["value"] == 3.0
    assert by_key["cache_race_list_seconds"]["value"] == 300
    assert by_key["cache_race_card_seconds"]["value"] == 60
    assert by_key["cache_odds_seconds"]["value"] == 60
    assert by_key["cache_past_runs_seconds"]["value"] == 86400
    assert "made the running" in by_key["pace_led"]["value"]
    for key in ("racing_api_username", "racing_api_password"):
        field = by_key[key]
        assert field["type"] == "secret"
        assert field["value"] == MASK
        assert field["writable"] is False
        assert field["secret"] in ("racingapi-username", "racingapi-password")
    # No secret value anywhere in the response.
    text = client.get("/admin/settings", headers=operator_headers).text
    assert "racingapi-username" in text and MASK in text


def test_settings_put_applies_rejects_and_persists(client, operator_headers):
    response = client.put("/admin/settings", headers=operator_headers, json={"values": {
        "commission_rate": 0.05,
        "past_runs": 7,
        "pace_led": "made all, bounced out to lead",
        "regions": ["gb"],
        "racing_api_username": "attempt",
        "nonsense": 1,
        "default_stake": -5,
        "cache_odds_seconds": 1.5,
    }})
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == ["commission_rate", "pace_led", "past_runs", "regions"]
    rejected = {r["key"]: r["reason"] for r in body["rejected"]}
    assert rejected == {
        "racing_api_username": "read only",
        "nonsense": "unknown setting",
        "default_stake": "must be at least 0.01",
        "cache_odds_seconds": "must be a whole number",
    }
    assert body["settings"]["updated_by"] == OPERATOR
    assert body["settings"]["source"] == "memory"

    again = client.get("/admin/settings", headers=operator_headers).json()
    by_key = {f["key"]: f for g in again["groups"] for f in g["fields"]}
    assert by_key["commission_rate"]["value"] == 0.05
    assert by_key["past_runs"]["value"] == 7
    assert by_key["pace_led"]["value"] == ["made all", "bounced out to lead"]
    assert by_key["regions"]["value"] == ["gb"]
    assert by_key["default_stake"]["value"] == 100.0


def test_settings_put_with_bad_body_is_invalid_input(client, operator_headers):
    response = client.put("/admin/settings", headers=operator_headers, json={"nope": {}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_config_shows_names_not_values(client, operator_headers):
    body = client.get("/admin/config", headers=operator_headers).json()
    assert body["project"] == "chiops"
    assert body["region"] == "europe-west1"
    assert body["paper_entries_bucket"] == "chiops-fb12-paper-entries"
    assert body["firestore"] == {"database": "(default)", "collection": "fsu-admin-settings", "document": "fb12"}
    assert body["credentials"]["racing_api_username"] == {"secret": "racingapi-username", "value": MASK, "state": "not loaded"}
    assert "cloud@ascotwm.com" in body["access"]["google"]["operators"]


def test_logs_are_newest_first_and_paginate(client, operator_headers):
    client.get("/admin/health", headers=operator_headers)
    body = client.get("/admin/logs?limit=2", headers=operator_headers).json()
    assert body["count"] == 2
    assert body["entries"][0]["seq"] > body["entries"][1]["seq"]
    entry = body["entries"][0]
    assert {"timestamp", "severity", "service_name", "trace_id", "message"} <= set(entry)
    older = client.get(f"/admin/logs?limit=2&before={body['entries'][1]['seq']}", headers=operator_headers).json()
    assert all(e["seq"] < body["entries"][1]["seq"] for e in older["entries"])


def test_request_logs_never_carry_tokens(client, operator_headers):
    client.get("/admin/health", headers=operator_headers)
    text = client.get("/admin/logs?limit=200", headers=operator_headers).text
    token = operator_headers["Authorization"].split(" ", 1)[1]
    assert token not in text


def test_stream_starts_with_hello_then_forwards_events(app):
    from routers.admin import event_stream

    async def run():
        app.state.bus.bind_loop(asyncio.get_running_loop())
        stream = event_stream(app.state)
        first = await stream.__anext__()
        app.state.bus.publish("settings", {"keys": ["past_runs"]})
        second = await asyncio.wait_for(stream.__anext__(), timeout=2)
        await stream.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first.startswith("event: hello\n")
    assert '"status": "ok"' not in first  # hello carries the status snapshot, not health
    assert '"mode": "paper"' in first
    assert second.startswith("event: settings\n")
    assert first.endswith("\n\n") and second.endswith("\n\n")


def test_stream_endpoint_answers_with_server_sent_events(app):
    """The endpoint itself, not the framework's route table: a streaming SSE response."""
    from starlette.requests import Request

    from routers.admin import admin_stream

    request = Request({"type": "http", "app": app, "method": "GET", "path": "/admin/stream",
                       "headers": [], "query_string": b""})
    response = asyncio.run(admin_stream(request))
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-type"].startswith("text/event-stream")


def test_unknown_route_with_token_is_not_found(client, operator_headers):
    response = client.get("/api/nothing-here", headers=operator_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
