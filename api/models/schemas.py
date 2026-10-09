"""Pydantic v2 request models. extra="forbid" everywhere: an unknown field is an error."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsUpdate(Strict):
    values: dict[str, Any] = Field(..., description="Setting key -> new value")
