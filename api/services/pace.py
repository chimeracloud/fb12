"""Pacemaker evidence from the horse's own running comments in its past runs.

The runner's last N runs before the race date, from GET /horses/{horse_id}/results.
Each run's comment for this horse is normalised (lower case, hyphens to spaces,
single spaces) and matched against the keyword lists in order, first match wins:
LED, PROMINENT, HELD_UP, MIDFIELD. Anything else is UNCLASSIFIED. Never guess.
The lists are settings.
"""

from __future__ import annotations

import re
from typing import Any

CATEGORIES = ("LED", "PROMINENT", "HELD_UP", "MIDFIELD")
ALL_CATEGORIES = ("LED", "PROMINENT", "MIDFIELD", "HELD_UP", "UNCLASSIFIED")

_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalise(text: Any) -> str:
    """Lower case, hyphens and other punctuation to spaces, single spaces."""
    if not text or not isinstance(text, str):
        return ""
    lowered = text.lower().replace("-", " ").replace("\u2013", " ").replace("\u2014", " ")
    return _SPACES.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def classify(comment: Any, lists: dict[str, list[str]]) -> str:
    """lists: {"LED": [...], "PROMINENT": [...], "HELD_UP": [...], "MIDFIELD": [...]}.
    Whole phrases on word boundaries, lists in order, first match wins. Never guess."""
    text = normalise(comment)
    if not text:
        return "UNCLASSIFIED"
    padded = f" {text} "
    for category in CATEGORIES:
        for phrase in lists.get(category, []):
            needle = normalise(phrase)
            if needle and f" {needle} " in padded:
                return category
    return "UNCLASSIFIED"


def own_row(race: dict[str, Any], horse_id: str) -> dict[str, Any] | None:
    for runner in race.get("runners") or []:
        if runner.get("horse_id") == horse_id:
            return runner
    return None


def compute_pace(horse_id: str, results_page: dict[str, Any], lists: dict[str, list[str]], runs: int) -> dict[str, Any]:
    races = results_page.get("results") or []
    races = sorted(races, key=lambda r: str(r.get("date") or ""), reverse=True)[:runs]
    counts = {c: 0 for c in ALL_CATEGORIES}
    rows: list[dict[str, Any]] = []
    for race in races:
        row = own_row(race, horse_id)
        comment = row.get("comment") if row else None
        category = classify(comment, lists)
        counts[category] += 1
        rows.append({
            "date": race.get("date"),
            "course": race.get("course"),
            "race_name": race.get("race_name"),
            "position": (row or {}).get("position"),
            "class": race.get("class"),
            "comment": comment if comment else None,
            "category": category,
        })
    return {"horse_id": horse_id, "counts": counts, "runs": rows}
