"""Credential access is an abstraction, not a dependency (CHI-POL-040).

get_credential(name) is the one interface. Secret Manager sits behind it today;
swap this module for one with the same interface and nothing else changes.
Values live in memory only, for the life of the process, and are never logged,
never stored and never returned by an endpoint. The secret NAMES come from the
committed config, so no secret path appears in code.
"""

from __future__ import annotations

import logging
import threading

from core.config import CONFIG
from core.logging import log

logger = logging.getLogger("fb12.credentials")

_LOGICAL_TO_SECRET: dict[str, str] = {
    "racing_api_username": CONFIG.credentials.racing_api_username,
    "racing_api_password": CONFIG.credentials.racing_api_password,
}
_cache: dict[str, str] = {}
_versions: dict[str, str] = {}
_lock = threading.Lock()


class CredentialError(Exception):
    pass


def credential_names() -> dict[str, str]:
    """Logical name -> secret id. Names only; safe to show in admin."""
    return dict(_LOGICAL_TO_SECRET)


def credential_state(name: str) -> str:
    with _lock:
        return "loaded" if name in _cache else "not loaded"


def get_credential(name: str) -> str:
    if name not in _LOGICAL_TO_SECRET:
        raise CredentialError(f"unknown credential {name!r}")
    with _lock:
        if name in _cache:
            return _cache[name]
    value, version = _fetch(_LOGICAL_TO_SECRET[name])
    with _lock:
        _cache[name] = value
        _versions[name] = version
    log(logger, logging.INFO, "credential fetched", credential=name, secret=_LOGICAL_TO_SECRET[name], version=version)
    return value


def reload_credentials() -> None:
    with _lock:
        _cache.clear()
        _versions.clear()
    log(logger, logging.INFO, "credential cache cleared")


def _fetch(secret_id: str) -> tuple[str, str]:
    try:
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover
        raise CredentialError("google-cloud-secret-manager is not installed") from exc
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{CONFIG.gcp_project}/secrets/{secret_id}/versions/latest"
    try:
        response = client.access_secret_version(request={"name": path})
    except Exception as exc:  # noqa: BLE001
        raise CredentialError(f"could not read secret {secret_id!r}: {type(exc).__name__}") from exc
    value = response.payload.data.decode("utf-8").strip()
    version = response.name.rsplit("/", 1)[-1]
    return value, version
