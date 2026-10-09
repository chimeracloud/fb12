"""Test fixtures. The app runs with an in-memory settings backend and a local RSA
key standing in for Google's and Cloudflare's published signing keys, so the
gate's logic is tested end to end without the network. No Racing API data is
faked anywhere: the endpoint tests use the real prices named in the brief."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

KID = "fb12-test-key"
OPERATOR = "cloud@ascotwm.com"
NOT_AN_OPERATOR = "nobody@example.com"
TEST_HOST_AUDIENCE = "https://testserver"  # TestClient sends Host: testserver
GCLOUD_CLIENT_AUDIENCE = "32555940559.apps.googleusercontent.com"
CF_TEAM_DOMAIN = "fb12-tests.cloudflareaccess.com"
CF_AUDIENCE = "f" * 64


@pytest.fixture(scope="session")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return SimpleNamespace(private_pem=pem, public_key=private.public_key())


class FakeJWKClient:
    """Stands in for PyJWKClient: returns the test public key for the test kid."""

    def __init__(self, public_key) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token: str):
        header = jwt.get_unverified_header(token)
        if header.get("kid") != KID:
            raise jwt.exceptions.PyJWKClientError("kid not found")
        return SimpleNamespace(key=self.public_key)


def sign(keypair, claims: dict) -> str:
    return jwt.encode(claims, keypair.private_pem, algorithm="RS256", headers={"kid": KID})


def google_token(keypair, email=OPERATOR, aud=TEST_HOST_AUDIENCE, iss="https://accounts.google.com",
                 email_verified=True, exp_delta=3600) -> str:
    now = int(time.time())
    return sign(keypair, {
        "iss": iss, "aud": aud, "sub": "100000000000000000001", "email": email,
        "email_verified": email_verified, "iat": now - 10, "exp": now + exp_delta,
    })


def cloudflare_token(keypair, email=OPERATOR, aud=CF_AUDIENCE, iss=f"https://{CF_TEAM_DOMAIN}", exp_delta=3600) -> str:
    now = int(time.time())
    return sign(keypair, {
        "aud": [aud], "email": email, "exp": now + exp_delta, "iat": now - 10, "nbf": now - 10,
        "iss": iss, "type": "app", "identity_nonce": "nonce", "sub": "subject", "country": "GB",
    })


@pytest.fixture
def app(keypair, monkeypatch):
    from core.settings import MemoryBackend
    import main as main_module

    application = main_module.create_app(settings_backend=MemoryBackend())
    fake = FakeJWKClient(keypair.public_key)
    verifier = application.state.verifier
    monkeypatch.setattr(verifier, "_google_jwks", fake)
    monkeypatch.setattr(verifier, "cf_jwks", lambda: fake)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def cloudflare_enabled(app, monkeypatch):
    cf = app.state.verifier.config.access.cloudflare
    monkeypatch.setattr(cf, "team_domain", CF_TEAM_DOMAIN)
    monkeypatch.setattr(cf, "audience_tag", CF_AUDIENCE)
    return cf


@pytest.fixture
def operator_headers(keypair):
    return {"Authorization": f"Bearer {google_token(keypair)}"}
