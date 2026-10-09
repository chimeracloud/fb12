"""The gate. Every /api and /admin request carries one of two credentials.

1. A Cloudflare Access token (header Cf-Access-Jwt-Assertion), forwarded by the
   GUI's Pages Function. Signature against the team domain's published keys,
   audience against the FB12 Access application's tag, issuer against the team
   domain, expiry. Until team domain and audience tag are set in config, this
   path rejects everything.
2. A Google ID token (Authorization: Bearer) for FB12's own URL from an email on
   the operator list, checked against Google's published certificates. A user
   token minted by gcloud carries the gcloud client id as its audience, which
   Cloud Run's own IAM check also accepts; that id is the one entry in
   extra_audiences.

Anything else gets 401 with no detail. The verified email becomes saved_by.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from core.config import CONFIG, Fb12Config
from core.errors import error_body
from core.logging import log

logger = logging.getLogger("fb12.auth")

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

METHOD_CLOUDFLARE = "cloudflare_access"
METHOD_GOOGLE = "google_id_token"


@dataclass(frozen=True)
class Credential:
    email: str
    method: str


class AuthError(Exception):
    pass


class Verifier:
    def __init__(self, config: Fb12Config = CONFIG) -> None:
        self.config = config
        self._google_jwks = PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)
        self._cf_jwks: PyJWKClient | None = None
        self._cf_jwks_domain = ""
        self.accepted = {METHOD_CLOUDFLARE: 0, METHOD_GOOGLE: 0}
        self.rejected = 0

    # --- Cloudflare Access -------------------------------------------------

    def cf_jwks(self) -> PyJWKClient:
        domain = self.config.access.cloudflare.team_domain
        if self._cf_jwks is None or self._cf_jwks_domain != domain:
            self._cf_jwks = PyJWKClient(self.config.access.cloudflare.certs_url, cache_keys=True, lifespan=3600)
            self._cf_jwks_domain = domain
        return self._cf_jwks

    def verify_cloudflare(self, token: str) -> Credential:
        cf = self.config.access.cloudflare
        if not cf.configured:
            raise AuthError("cloudflare access is not configured")
        signing_key = self.cf_jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=cf.audience_tag,
            issuer=cf.issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise AuthError("cloudflare token has no email claim")
        return Credential(email=email, method=METHOD_CLOUDFLARE)

    # --- Google ID token ---------------------------------------------------

    def verify_google(self, token: str, host: str) -> Credential:
        signing_key = self._google_jwks.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"require": ["exp", "iat", "aud", "iss"], "verify_aud": False},
        )
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise AuthError("google token issuer is wrong")
        allowed = set(self.config.access.google.extra_audiences)
        if host:
            allowed.add(f"https://{host}")
        aud = claims.get("aud")
        audiences = set(aud) if isinstance(aud, list) else {aud}
        if not audiences & allowed:
            raise AuthError("google token audience is not FB12")
        if claims.get("email_verified") is not True:
            raise AuthError("google token email is not verified")
        email = str(claims.get("email") or "").strip().lower()
        if not email or not self.config.access.google.is_operator(email):
            raise AuthError("email is not on the operator list")
        return Credential(email=email, method=METHOD_GOOGLE)

    # --- Entry point -------------------------------------------------------

    def authenticate(self, headers: Headers) -> Credential | None:
        attempts: list[str] = []
        cf_token = headers.get("cf-access-jwt-assertion")
        if cf_token:
            attempts.append(METHOD_CLOUDFLARE)
            try:
                cred = self.verify_cloudflare(cf_token)
                self.accepted[METHOD_CLOUDFLARE] += 1
                return cred
            except Exception as exc:  # noqa: BLE001 - any failure is a rejection
                log(logger, logging.WARNING, "cloudflare token rejected", reason=f"{type(exc).__name__}: {exc}")
        authorization = headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            attempts.append(METHOD_GOOGLE)
            token = authorization[7:].strip()
            try:
                cred = self.verify_google(token, headers.get("host", ""))
                self.accepted[METHOD_GOOGLE] += 1
                return cred
            except Exception as exc:  # noqa: BLE001
                log(logger, logging.WARNING, "google token rejected", reason=f"{type(exc).__name__}: {exc}")
        self.rejected += 1
        if not attempts:
            log(logger, logging.WARNING, "request without credential")
        return None


class AccessGate:
    """Pure ASGI middleware: authenticate or answer 401 with no detail."""

    def __init__(self, app: ASGIApp, verifier: Verifier) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        credential = await asyncio.to_thread(self.verifier.authenticate, headers)
        if credential is None:
            response = JSONResponse(
                status_code=401,
                content=error_body("UNAUTHENTICATED", "Not authenticated."),
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["credential"] = credential
        await self.app(scope, receive, send)
