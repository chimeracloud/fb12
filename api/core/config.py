"""Non-secret deployment configuration.

Everything here is committed and ships with the push: the file api/config/fb12.json
holds the team domain, audience tag, operator list, resource names and secret
NAMES (never values). Cloud Run's own identity variables (K_SERVICE, K_REVISION,
PORT) are read because they are deploy-time identity, not secrets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

VERSION = "0.2.0"

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "fb12.json"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FirestoreConfig(Strict):
    database: str
    collection: str
    document: str


class RacingApiConfig(Strict):
    base_url: str


class CredentialNames(Strict):
    """Logical credential name -> Secret Manager secret id. Names only."""

    racing_api_username: str
    racing_api_password: str


class CloudflareAccessConfig(Strict):
    team_domain: str = ""
    audience_tag: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.team_domain) and bool(self.audience_tag)

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}"

    @property
    def certs_url(self) -> str:
        return f"https://{self.team_domain}/cdn-cgi/access/certs"


class GoogleAccessConfig(Strict):
    operators: list[str] = Field(default_factory=list)
    extra_audiences: list[str] = Field(default_factory=list)

    def is_operator(self, email: str) -> bool:
        return email.lower() in {o.lower() for o in self.operators}


class AccessConfig(Strict):
    cloudflare: CloudflareAccessConfig
    google: GoogleAccessConfig


class Fb12Config(Strict):
    unit: str
    service_name: str
    gcp_project: str
    region: str
    firestore: FirestoreConfig
    paper_entries_bucket: str
    racing_api: RacingApiConfig
    credentials: CredentialNames
    access: AccessConfig


def load_config(path: Path = CONFIG_PATH) -> Fb12Config:
    with open(path, encoding="utf-8") as fh:
        return Fb12Config.model_validate(json.load(fh))


CONFIG: Fb12Config = load_config()


class Runtime:
    """Identity Cloud Run injects into the container. Empty outside Cloud Run."""

    service: str = os.environ.get("K_SERVICE", "")
    revision: str = os.environ.get("K_REVISION", "")
    configuration: str = os.environ.get("K_CONFIGURATION", "")
    port: int = int(os.environ.get("PORT", "8080"))
