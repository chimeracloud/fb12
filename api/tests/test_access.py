"""Test 9 of the brief: no credential, or an invalid one, gets 401 on every /api and /admin route."""

from __future__ import annotations

import pytest

from tests.conftest import (
    CF_AUDIENCE,
    GCLOUD_CLIENT_AUDIENCE,
    NOT_AN_OPERATOR,
    OPERATOR,
    cloudflare_token,
    google_token,
)

ROUTES = [
    ("GET", "/admin/health"),
    ("GET", "/admin/status"),
    ("GET", "/admin/settings"),
    ("PUT", "/admin/settings"),
    ("GET", "/admin/config"),
    ("GET", "/admin/logs"),
    ("GET", "/admin/stream"),
    ("GET", "/api/races"),
    ("GET", "/api/races/rac_1"),
    ("GET", "/api/races/rac_1/runners/hrs_1/move"),
    ("GET", "/api/races/rac_1/runners/hrs_1/pace"),
    ("POST", "/api/calculate"),
    ("POST", "/api/paper"),
    ("GET", "/api/paper"),
    ("GET", "/api/paper/entry"),
    ("POST", "/api/paper/entry/settle"),
    ("GET", "/"),
    ("GET", "/docs"),
]

UNAUTHENTICATED = {"error": {"code": "UNAUTHENTICATED", "message": "Not authenticated."}}


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_no_credential_is_401_everywhere(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", [
    "Bearer not-a-token",
    "Bearer ",
    "Basic dXNlcjpwYXNz",
    "Bearer eyJhbGciOiJub25lIn0.eyJlbWFpbCI6ImNsb3VkQGFzY290d20uY29tIn0.",
])
def test_garbage_credentials_are_401(client, header):
    response = client.get("/admin/health", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_valid_operator_token_is_accepted(client, keypair):
    response = client.get("/admin/health", headers={"Authorization": f"Bearer {google_token(keypair)}"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_gcloud_client_audience_is_accepted(client, keypair):
    token = google_token(keypair, aud=GCLOUD_CLIENT_AUDIENCE)
    assert client.get("/admin/health", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_second_operator_is_accepted(client, keypair):
    token = google_token(keypair, email="admin@chimerasportstrading.com")
    assert client.get("/admin/health", headers={"Authorization": f"Bearer {token}"}).status_code == 200


@pytest.mark.parametrize("kwargs", [
    {"email": NOT_AN_OPERATOR},
    {"aud": "https://some-other-service.run.app"},
    {"email_verified": False},
    {"exp_delta": -60},
    {"iss": "https://evil.example.com"},
])
def test_google_token_variants_are_rejected(client, keypair, kwargs):
    token = google_token(keypair, **kwargs)
    response = client.get("/admin/health", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_cloudflare_path_rejects_everything_until_configured(client, keypair):
    token = cloudflare_token(keypair)
    response = client.get("/admin/health", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401


def test_cloudflare_token_accepted_once_configured(client, keypair, cloudflare_enabled):
    token = cloudflare_token(keypair, email=OPERATOR)
    response = client.get("/admin/health", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 200


@pytest.mark.parametrize("kwargs", [
    {"aud": "0" * 64},
    {"iss": "https://someone-else.cloudflareaccess.com"},
    {"exp_delta": -60},
])
def test_cloudflare_token_variants_are_rejected(client, keypair, cloudflare_enabled, kwargs):
    token = cloudflare_token(keypair, **kwargs)
    response = client.get("/admin/health", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_browser_authorization_header_is_ignored_when_cloudflare_token_valid(client, keypair, cloudflare_enabled):
    headers = {"Cf-Access-Jwt-Assertion": cloudflare_token(keypair), "Authorization": "Bearer junk"}
    assert client.get("/admin/health", headers=headers).status_code == 200


def test_saved_by_email_comes_from_the_credential(client, keypair, cloudflare_enabled):
    """The verified email is what PUT /admin/settings records as updated_by."""
    headers = {"Cf-Access-Jwt-Assertion": cloudflare_token(keypair, email="Admin@ChimeraSportsTrading.com")}
    response = client.put("/admin/settings", json={"values": {"past_runs": 6}}, headers=headers)
    assert response.status_code == 200
    assert response.json()["settings"]["updated_by"] == "admin@chimerasportstrading.com"
