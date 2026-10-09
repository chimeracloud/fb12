"""The brief's TESTS, tolerance one penny. Real prices: Challenge Stakes, Newmarket,
9 October 2026, Betfair Exchange prices on the 08:12 card. T = £100."""

from __future__ import annotations

import pytest

from core.errors import ApiError
from models.schemas import CalculateResponse
from services.dutch import calculate

PENNY = 0.005
CHANCE = 0.00005

FLORA = ("hrs_35445375", "Flora of Bermuda", 2.94)
TIME_TO_TURN = ("hrs_52830953", "Time To Turn", 4.1)
NEVER_SO_BRAVE = ("hrs_35625688", "Never So Brave", 6.0)
PINA_SONATA = ("hrs_45855166", "Pina Sonata", 7.6)
WITNESS_STAND = ("hrs_35149667", "Witness Stand", 11.0)
HOLGUIN = ("hrs_29228423", "Holguin", 17.5)


def runner(entry, tier, part_fraction=None):
    horse_id, horse, price = entry
    return {"horse_id": horse_id, "horse": horse, "price": price, "tier": tier, "part_fraction": part_fraction}


def version_1():
    return [runner(FLORA, "PROFIT"), runner(TIME_TO_TURN, "PROFIT"), runner(NEVER_SO_BRAVE, "OUT"),
            runner(PINA_SONATA, "OUT"), runner(WITNESS_STAND, "OUT"), runner(HOLGUIN, "OUT")]


def version_2():
    return [runner(FLORA, "PROFIT"), runner(TIME_TO_TURN, "PROFIT"), runner(NEVER_SO_BRAVE, "BREAK_EVEN"),
            runner(PINA_SONATA, "BREAK_EVEN"), runner(WITNESS_STAND, "OUT"), runner(HOLGUIN, "OUT")]


def version_3():
    return [runner(FLORA, "PROFIT"), runner(TIME_TO_TURN, "PROFIT"), runner(NEVER_SO_BRAVE, "BREAK_EVEN"),
            runner(PINA_SONATA, "BREAK_EVEN"), runner(WITNESS_STAND, "PART", 0.5), runner(HOLGUIN, "OUT")]


def by_name(result):
    return {r["horse"]: r for r in result["runners"]}


def test_1_top_two_only():
    result = calculate(100, 0, version_1()).to_contract()
    assert result["feasible"] is True and result["message"] is None
    assert result["profit_per_win"] == pytest.approx(71.22, abs=PENNY)
    r = by_name(result)
    assert r["Flora of Bermuda"]["stake"] == pytest.approx(58.24, abs=PENNY)
    assert r["Time To Turn"]["stake"] == pytest.approx(41.76, abs=PENNY)
    for name in ("Never So Brave", "Pina Sonata", "Witness Stand", "Holguin"):
        assert r[name]["stake"] == 0.0
        assert r[name]["net_if_wins"] == pytest.approx(-100.0, abs=PENNY)


def test_2_four_horses():
    result = calculate(100, 0, version_2()).to_contract()
    assert result["profit_per_win"] == pytest.approx(20.16, abs=PENNY)
    r = by_name(result)
    assert r["Flora of Bermuda"]["stake"] == pytest.approx(40.87, abs=PENNY)
    assert r["Time To Turn"]["stake"] == pytest.approx(29.31, abs=PENNY)
    assert r["Never So Brave"]["stake"] == pytest.approx(16.67, abs=PENNY)
    assert r["Pina Sonata"]["stake"] == pytest.approx(13.16, abs=PENNY)
    assert r["Never So Brave"]["net_if_wins"] == pytest.approx(0.0, abs=PENNY)
    assert r["Pina Sonata"]["return_if_wins"] == pytest.approx(100.0, abs=PENNY)


def test_3_cautious():
    result = calculate(100, 0, version_3()).to_contract()
    assert result["profit_per_win"] == pytest.approx(12.37, abs=PENNY)
    r = by_name(result)
    assert r["Flora of Bermuda"]["stake"] == pytest.approx(38.22, abs=PENNY)
    assert r["Time To Turn"]["stake"] == pytest.approx(27.41, abs=PENNY)
    assert r["Never So Brave"]["stake"] == pytest.approx(16.67, abs=PENNY)
    assert r["Pina Sonata"]["stake"] == pytest.approx(13.16, abs=PENNY)
    assert r["Witness Stand"]["stake"] == pytest.approx(4.55, abs=PENNY)
    assert r["Witness Stand"]["net_if_wins"] == pytest.approx(-50.0, abs=PENNY)
    assert r["Witness Stand"]["return_if_wins"] == pytest.approx(50.0, abs=PENNY)
    assert r["Holguin"]["stake"] == 0.0


@pytest.mark.parametrize("version", [version_1, version_2, version_3])
def test_4_book_and_expected_value(version):
    result = calculate(100, 0, version()).to_contract()
    assert result["book_pct"] == pytest.approx(103.03, abs=0.005)
    assert result["expected_value_gbp"] == pytest.approx(-2.94, abs=PENNY)
    assert result["expected_value_pct"] == pytest.approx(-2.94, abs=0.005)


def test_5_holguin():
    expected_wipe = {version_1: 1.40, version_2: 4.96, version_3: 8.08}
    for version, wipe in expected_wipe.items():
        r = by_name(calculate(100, 0, version()).to_contract())["Holguin"]
        assert r["market_chance"] == pytest.approx(0.0555, abs=CHANCE)
        assert r["break_even_chance"] == pytest.approx(0.0268, abs=CHANCE)
        assert r["can_break_even"] is True
        assert r["wins_wiped_out"] == pytest.approx(wipe, abs=0.005)


def test_6_witness_stand_in_version_3():
    r = by_name(calculate(100, 0, version_3()).to_contract())["Witness Stand"]
    assert r["market_chance"] == pytest.approx(0.0882, abs=CHANCE)
    assert r["break_even_chance"] == pytest.approx(0.0312, abs=CHANCE)
    assert r["can_break_even"] is True
    assert r["wins_wiped_out"] == pytest.approx(50 / 12.3727, abs=0.005)


def test_7_commission_only_reduces_a_positive_net():
    result = calculate(100, 0.02, version_3()).to_contract()
    r = by_name(result)
    assert r["Flora of Bermuda"]["net_if_wins"] == pytest.approx(12.37, abs=PENNY)
    assert r["Flora of Bermuda"]["net_after_commission"] == pytest.approx(12.13, abs=PENNY)
    assert r["Time To Turn"]["net_after_commission"] == pytest.approx(12.13, abs=PENNY)
    assert r["Never So Brave"]["net_after_commission"] == pytest.approx(0.0, abs=PENNY)
    assert r["Witness Stand"]["net_after_commission"] == pytest.approx(-50.0, abs=PENNY)
    assert r["Holguin"]["net_after_commission"] == pytest.approx(-100.0, abs=PENNY)
    # Commission changes nothing else.
    plain = calculate(100, 0, version_3()).to_contract()
    assert plain["profit_per_win"] == result["profit_per_win"]
    assert plain["book_pct"] == result["book_pct"]


@pytest.mark.parametrize("version", [version_1, version_2, version_3])
@pytest.mark.parametrize("total", [100, 37.5, 1000, 0.5])
def test_8_unrounded_stakes_sum_to_total_and_out_is_zero(version, total):
    result = calculate(total, 0.02, version())
    assert sum(r.stake for r in result.runners) == pytest.approx(total, abs=1e-9)
    for r in result.runners:
        if r.tier == "OUT":
            assert r.stake == 0.0
        else:
            assert r.stake > 0
    # Identity check: at the market's own odds the expected value is T x (1 / book - 1) whatever the tiers.
    book = result.book_pct / 100
    assert result.expected_value_gbp == pytest.approx(total * (1 / book - 1), abs=1e-9)


def test_profit_and_break_even_runners_have_no_out_figures():
    r = by_name(calculate(100, 0, version_3()).to_contract())
    for name in ("Flora of Bermuda", "Time To Turn", "Never So Brave", "Pina Sonata"):
        assert r[name]["break_even_chance"] is None
        assert r[name]["can_break_even"] is None
        assert r[name]["wins_wiped_out"] is None
        assert r[name]["market_chance"] is not None


def test_no_profit_runner_is_infeasible():
    result = calculate(100, 0, [runner(FLORA, "BREAK_EVEN"), runner(HOLGUIN, "OUT")]).to_contract()
    assert result["feasible"] is False
    assert result["message"] == "No profit is possible: no runner is set to PROFIT."
    assert result["profit_per_win"] is None
    assert result["expected_value_gbp"] is None
    assert result["book_pct"] == pytest.approx((1 / 2.94 + 1 / 17.5) * 100, abs=0.005)
    for r in result["runners"]:
        assert r["stake"] is None and r["net_if_wins"] is None and r["wins_wiped_out"] is None
        assert r["market_chance"] is not None


def test_prices_too_short_are_infeasible_and_say_why():
    result = calculate(100, 0, [
        runner(("a", "Alpha", 1.5), "PROFIT"), runner(("b", "Beta", 1.8), "PROFIT"), runner(("c", "Gamma", 12.0), "OUT"),
    ]).to_contract()
    assert result["feasible"] is False
    assert result["profit_per_win"] is None
    assert result["message"].startswith("No profit is possible at these prices: ")
    assert "£122.22 of the £100.00" in result["message"]


def test_missing_out_price_leaves_book_and_chances_null_and_names_the_runner():
    runners = version_3()
    runners[-1]["price"] = None  # Holguin OUT without a price
    result = calculate(100, 0, runners).to_contract()
    assert result["feasible"] is True
    assert result["profit_per_win"] == pytest.approx(12.37, abs=PENNY)
    assert result["book_pct"] is None and result["expected_value_gbp"] is None and result["expected_value_pct"] is None
    assert result["message"] == "Holguin has no price, so the book, market chances and expected value cannot be worked out."
    r = by_name(result)
    assert all(x["market_chance"] is None for x in result["runners"])
    assert r["Holguin"]["stake"] == 0.0 and r["Holguin"]["net_if_wins"] == -100.0
    assert r["Holguin"]["wins_wiped_out"] == pytest.approx(8.08, abs=0.005)
    assert r["Holguin"]["break_even_chance"] is None and r["Holguin"]["can_break_even"] is None
    runners[-2]["price"] = None
    runners[-2]["tier"] = "OUT"
    runners[-2]["part_fraction"] = None
    message = calculate(100, 0, runners).to_contract()["message"]
    assert message.startswith("Witness Stand and Holguin have no price")


def test_cannot_break_even_when_the_rest_of_the_book_loses():
    # Two PROFIT runners carry the book; a PART runner at 1.0 fraction loses nothing and breaks even trivially.
    runners = [runner(FLORA, "PROFIT"), runner(TIME_TO_TURN, "PROFIT"), runner(HOLGUIN, "PART", 1.0)]
    r = by_name(calculate(100, 0, runners).to_contract())["Holguin"]
    assert r["net_if_wins"] == 0.0 and r["wins_wiped_out"] == 0.0
    assert r["can_break_even"] is True and r["break_even_chance"] == 1.0
    # When the rest of the book loses money on balance there is nothing to break even against:
    # Alpha 1.2 PROFIT wins +16, Beta 1.5 OUT loses 100 and carries two thirds of the remaining book.
    runners = [runner(("a", "Alpha", 1.2), "PROFIT"), runner(("b", "Beta", 1.5), "OUT"), runner(("c", "Gamma", 3.0), "PART", 0.1)]
    result = calculate(100, 0, runners).to_contract()
    assert result["feasible"] is True
    assert result["profit_per_win"] == pytest.approx(16.0, abs=PENNY)
    gamma = by_name(result)["Gamma"]
    assert gamma["can_break_even"] is False
    assert gamma["break_even_chance"] is None
    assert gamma["wins_wiped_out"] == pytest.approx(90 / 16, abs=0.005)
    beta = by_name(result)["Beta"]
    assert beta["can_break_even"] is False and beta["break_even_chance"] is None


@pytest.mark.parametrize(("stake", "commission", "runners", "fragment"), [
    (0, 0, version_1(), "stake_total must be greater than zero"),
    (100, 1, version_1(), "commission_rate must be a fraction"),
    (100, -0.1, version_1(), "commission_rate must be a fraction"),
    (100, 0, [], "at least one runner"),
    (100, 0, [runner(FLORA, "WIN")], "tier must be one of"),
    (100, 0, [runner(("x", "No Price", None), "PROFIT")], "No Price: price is required for a PROFIT runner"),
    (100, 0, [runner(("x", "Evens", 1.0), "PROFIT")], "price must be decimal odds above 1.0"),
    (100, 0, [runner(FLORA, "PROFIT"), runner(HOLGUIN, "PART")], "Holguin: part_fraction is required"),
    (100, 0, [runner(FLORA, "PROFIT"), runner(HOLGUIN, "PART", 1.5)], "between 0 and 1"),
    (100, 0, [runner(FLORA, "PROFIT"), runner(HOLGUIN, "OUT", 0.5)], "part_fraction only applies to PART"),
    (100, 0, [runner(FLORA, "PROFIT"), runner(FLORA, "OUT")], "appears more than once"),
])
def test_invalid_input(stake, commission, runners, fragment):
    with pytest.raises(ApiError) as excinfo:
        calculate(stake, commission, runners)
    assert excinfo.value.status_code == 400 and excinfo.value.code == "INVALID_INPUT"
    assert fragment in excinfo.value.message


def test_contract_shape_validates():
    for version in (version_1, version_2, version_3):
        CalculateResponse.model_validate(calculate(100, 0.02, version()).to_contract())


def test_endpoint_matches_the_function_and_touches_nothing(client, operator_headers, app):
    body = {"stake_total": 100, "commission_rate": 0.02, "runners": version_3()}
    response = client.post("/api/calculate", json=body, headers=operator_headers)
    assert response.status_code == 200, response.text
    assert response.json() == calculate(100, 0.02, version_3()).to_contract()
    assert app.state.racing.stats.calls == 0
    assert response.json()["runners"][5]["break_even_chance"] == pytest.approx(0.0268, abs=CHANCE)


def test_endpoint_rejects_unknown_fields_and_bad_values(client, operator_headers):
    bad = client.post("/api/calculate", json={"stake_total": 100, "commission_rate": 0, "runners": version_1(), "extra": 1}, headers=operator_headers)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_INPUT"
    short = client.post("/api/calculate", json={"stake_total": 100, "commission_rate": 0,
                        "runners": [runner(("x", "Evens", 1.0), "PROFIT")]}, headers=operator_headers)
    assert short.status_code == 400
    assert "Evens: price must be decimal odds above 1.0" in short.json()["error"]["message"]
