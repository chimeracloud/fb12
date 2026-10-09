"""Race list and race card mapping, against the real Challenge Stakes card of 9 October 2026."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.schemas import RaceCard, RaceList
from services.races import exchange_and_best, map_race_card, map_race_summary, parse_updated, runner_status, uk_time

FIXTURE = Path(__file__).parent / "fixtures" / "challenge_stakes_card.json"


@pytest.fixture(scope="module")
def card() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_uk_time_from_off_dt():
    assert uk_time("2026-10-09T14:25:00+01:00") == "14:25"
    assert uk_time("2026-12-26T13:30:00+00:00") == "13:30"
    assert uk_time("2026-10-09T13:25:00+00:00") == "14:25"  # UTC in October is one hour behind UK
    assert uk_time("") is None
    assert uk_time(None) is None


def test_card_updated_time_is_read_as_uk_time():
    assert parse_updated("2026-10-09 09:53:06") == "2026-10-09T09:53:06+01:00"
    assert parse_updated("2026-01-15 09:53:06") == "2026-01-15T09:53:06+00:00"
    assert parse_updated("") is None


@pytest.mark.parametrize(("number", "status"), [
    ("1", "DECLARED"), ("12", "DECLARED"), ("NR", "NON_RUNNER"), ("nr", "NON_RUNNER"),
    ("R1", "RESERVE"), ("R2", "RESERVE"), ("", "DECLARED"),
])
def test_runner_status(number, status):
    assert runner_status(number) == status


def test_exchange_and_best_leave_out_the_exchanges():
    odds = [
        {"bookmaker": "Smarkets", "decimal": "30", "updated": "2026-10-09 09:53:06"},
        {"bookmaker": "Matchbook", "decimal": "31", "updated": "2026-10-09 09:53:06"},
        {"bookmaker": "Bet365", "decimal": "17", "updated": "2026-10-09 09:53:06"},
        {"bookmaker": "Betfair Exchange", "decimal": "17.5", "updated": "2026-10-09 09:53:06"},
        {"bookmaker": "Betfair Sportsbook", "decimal": "19", "updated": "2026-10-09 09:53:06"},
    ]
    assert exchange_and_best(odds) == (17.5, "2026-10-09T09:53:06+01:00", 19.0, "Betfair Sportsbook")
    assert exchange_and_best([]) == (None, None, None, None)
    assert exchange_and_best(None) == (None, None, None, None)


def test_race_summary(card):
    summary = map_race_summary(card)
    assert summary == {
        "race_id": "rac_32300820643",
        "off_dt": "2026-10-09T14:25:00+01:00",
        "off_time_uk": "14:25",
        "course": "Newmarket",
        "race_name": "Thoroughbred Industry Employee Awards Challenge Stakes (Group 2)",
        "pattern": "Group 2",
        "race_class": "Class 1",
        "field_size": 6,
        "region": "GB",
    }
    RaceList.model_validate({"date": "2026-10-09", "races": [summary]})


def test_race_card_six_runners(card):
    mapped = map_race_card(card, "2026-10-09T08:53:06+00:00")
    RaceCard.model_validate(mapped)
    assert mapped["race"] == {
        "race_id": "rac_32300820643",
        "off_dt": "2026-10-09T14:25:00+01:00",
        "off_time_uk": "14:25",
        "course": "Newmarket",
        "race_name": "Thoroughbred Industry Employee Awards Challenge Stakes (Group 2)",
        "pattern": "Group 2",
        "distance": "7f",
        "going": "Good",
        "field_size": 6,
    }
    assert mapped["fetched_at"] == "2026-10-09T08:53:06+00:00"
    runners = {r["horse"]: r for r in mapped["runners"]}
    assert list(runners) == ["Holguin", "Never So Brave", "Witness Stand", "Time To Turn", "Flora of Bermuda", "Pina Sonata"]
    assert all(r["status"] == "DECLARED" for r in runners.values())

    flora = runners["Flora of Bermuda"]
    assert flora["number"] == "5" and flora["draw"] == 5
    assert flora["official_rating"] == 111 and flora["form"] == "101102"
    assert flora["exchange_price"] == 2.78
    assert flora["exchange_updated"] == "2026-10-09T09:53:06+01:00"
    assert flora["best_bookmaker_price"] == 2.63 and flora["best_bookmaker"] == "10 Bet"
    assert flora["trainer"] == "Andrew Balding" and flora["jockey"] == "James Doyle"

    holguin = runners["Holguin"]
    assert holguin["exchange_price"] == 17.5
    assert holguin["best_bookmaker_price"] == 19.0 and holguin["best_bookmaker"] == "Betfair Sportsbook"
    assert runners["Time To Turn"]["best_bookmaker"] == "SmarketsSBK"
    assert runners["Time To Turn"]["best_bookmaker_price"] == 5.0
    assert runners["Witness Stand"]["best_bookmaker"] == "10 Bet"
    assert runners["Never So Brave"]["best_bookmaker"] == "Bet365"
    assert runners["Pina Sonata"]["exchange_price"] == 7.2


def test_raw_passthrough_is_exactly_as_received(card):
    mapped = map_race_card(card, "x")
    expected_race = {k: v for k, v in card.items() if k != "runners"}
    assert mapped["raw_race"] == expected_race
    assert "runners" not in mapped["raw_race"]
    assert mapped["raw_race"]["race_status"] == "declared"
    for runner_in, runner_out in zip(card["runners"], mapped["runners"], strict=True):
        assert runner_out["raw"] == runner_in
        assert runner_out["raw"]["odds"] == runner_in["odds"]


def test_same_owner_markers(card):
    runners = {r["horse"]: r for r in map_race_card(card, "x")["runners"]}
    # Wathnan Racing owns Holguin and Flora of Bermuda, with different trainers.
    assert runners["Holguin"]["same_owner_as"] == ["Flora of Bermuda"]
    assert runners["Holguin"]["same_trainer_too"] is False
    assert runners["Flora of Bermuda"]["same_owner_as"] == ["Holguin"]
    assert runners["Flora of Bermuda"]["same_trainer_too"] is False
    # Never So Brave shares a trainer with Flora of Bermuda but not an owner: no marker.
    for name in ("Never So Brave", "Witness Stand", "Time To Turn", "Pina Sonata"):
        assert runners[name]["same_owner_as"] == []
        assert runners[name]["same_trainer_too"] is False


def test_same_owner_marker_includes_trainer_match_and_skips_non_runners(card):
    """Logic check with the real runners re-labelled: if Flora of Bermuda were a non runner she
    would drop out of Holguin's marker; if Holguin shared her trainer the flag would be true."""
    altered = json.loads(json.dumps(card))
    by_name = {r["horse"]: r for r in altered["runners"]}
    by_name["Flora of Bermuda"]["number"] = "NR"
    runners = {r["horse"]: r for r in map_race_card(altered, "x")["runners"]}
    assert runners["Flora of Bermuda"]["status"] == "NON_RUNNER"
    assert runners["Holguin"]["same_owner_as"] == []
    assert runners["Flora of Bermuda"]["same_owner_as"] == []

    altered = json.loads(json.dumps(card))
    by_name = {r["horse"]: r for r in altered["runners"]}
    by_name["Holguin"]["trainer_id"] = by_name["Flora of Bermuda"]["trainer_id"]
    runners = {r["horse"]: r for r in map_race_card(altered, "x")["runners"]}
    assert runners["Holguin"]["same_trainer_too"] is True
    assert runners["Flora of Bermuda"]["same_trainer_too"] is True


def test_card_without_exchange_price(card):
    altered = json.loads(json.dumps(card))
    altered["runners"][0]["odds"] = [o for o in altered["runners"][0]["odds"] if o["bookmaker"] != "Betfair Exchange"]
    runner = map_race_card(altered, "x")["runners"][0]
    assert runner["exchange_price"] is None and runner["exchange_updated"] is None
    assert runner["best_bookmaker_price"] == 19.0
