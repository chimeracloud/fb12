"""The graded dutch maths. The one code path (standing rule 9): POST /api/calculate
and paper entries both call calculate(); nothing else works out a figure.

Total stake T, back bets at decimal price B, q = 1 / B.
Target return R: PROFIT T + P; BREAK_EVEN T; PART part_fraction x T; OUT 0.
Stake s = R / B. The stakes sum to T.
P = T x (1 - sum of q over PROFIT and BREAK_EVEN - sum of part_fraction x q over PART) / (sum of q over PROFIT)
No PROFIT runner, or P at or below zero: feasible is false. Never force a number.
net_after_commission: only a positive net is reduced.
book_pct: sum of q over every runner, as a percent; needs every price.
market_chance: q / book. Expected value: sum of market_chance x net_if_wins.
break_even_chance for runner x: E = expected net given x does not win, the other
runners' chances rescaled to sum to 1; L = the loss if x wins; E / (E + L).
wins_wiped_out: L / P.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.errors import ApiError

TIERS = ("PROFIT", "BREAK_EVEN", "PART", "OUT")
MONEY_DP = 2
CHANCE_DP = 4
PCT_DP = 2


@dataclass(frozen=True)
class RunnerInput:
    horse_id: str
    horse: str
    tier: str
    price: float | None
    part_fraction: float | None


@dataclass
class RunnerFigures:
    horse_id: str
    horse: str
    tier: str
    price: float | None
    stake: float | None = None
    return_if_wins: float | None = None
    net_if_wins: float | None = None
    net_after_commission: float | None = None
    market_chance: float | None = None
    break_even_chance: float | None = None
    can_break_even: bool | None = None
    wins_wiped_out: float | None = None


@dataclass
class DutchResult:
    stake_total: float
    commission_rate: float
    feasible: bool
    message: str | None
    profit_per_win: float | None
    book_pct: float | None
    expected_value_gbp: float | None
    expected_value_pct: float | None
    runners: list[RunnerFigures] = field(default_factory=list)

    def to_contract(self) -> dict[str, Any]:
        """The response shape, rounded: money 2 dp, chances 4 dp, percents 2 dp."""
        return {
            "feasible": self.feasible,
            "message": self.message,
            "profit_per_win": _round(self.profit_per_win, MONEY_DP),
            "book_pct": _round(self.book_pct, PCT_DP),
            "expected_value_gbp": _round(self.expected_value_gbp, MONEY_DP),
            "expected_value_pct": _round(self.expected_value_pct, PCT_DP),
            "runners": [
                {
                    "horse_id": r.horse_id,
                    "horse": r.horse,
                    "tier": r.tier,
                    "price": r.price,
                    "stake": _round(r.stake, MONEY_DP),
                    "return_if_wins": _round(r.return_if_wins, MONEY_DP),
                    "net_if_wins": _round(r.net_if_wins, MONEY_DP),
                    "net_after_commission": _round(r.net_after_commission, MONEY_DP),
                    "market_chance": _round(r.market_chance, CHANCE_DP),
                    "break_even_chance": _round(r.break_even_chance, CHANCE_DP),
                    "can_break_even": r.can_break_even,
                    "wins_wiped_out": _round(r.wins_wiped_out, PCT_DP),
                }
                for r in self.runners
            ],
        }


def _round(value: float | None, places: int) -> float | None:
    if value is None:
        return None
    rounded = round(value + 0.0, places)
    return 0.0 if rounded == 0 else rounded  # no negative zero


def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def validate(stake_total: Any, commission_rate: Any, runners: list[dict[str, Any]]) -> tuple[float, float, list[RunnerInput]]:
    problems: list[str] = []
    try:
        total = float(stake_total)
    except (TypeError, ValueError):
        total = 0.0
        problems.append("stake_total must be a number.")
    if total <= 0:
        problems.append("stake_total must be greater than zero.")
    try:
        commission = float(commission_rate)
    except (TypeError, ValueError):
        commission = -1.0
        problems.append("commission_rate must be a number.")
    if not 0 <= commission < 1:
        problems.append("commission_rate must be a fraction from 0 up to but not including 1 (0.02 is 2%).")
    if not runners:
        problems.append("runners must list at least one runner.")

    seen: set[str] = set()
    parsed: list[RunnerInput] = []
    for index, raw in enumerate(runners or []):
        horse_id = str(raw.get("horse_id") or "").strip()
        horse = str(raw.get("horse") or "").strip() or horse_id or f"runner {index + 1}"
        tier = str(raw.get("tier") or "").strip().upper()
        price = raw.get("price")
        fraction = raw.get("part_fraction")
        if not horse_id:
            problems.append(f"{horse}: horse_id is required.")
        elif horse_id in seen:
            problems.append(f"{horse_id} appears more than once.")
        seen.add(horse_id)
        if tier not in TIERS:
            problems.append(f"{horse}: tier must be one of PROFIT, BREAK_EVEN, PART or OUT, not {raw.get('tier')!r}.")
            continue
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                problems.append(f"{horse}: price must be decimal odds.")
                price = None
            else:
                if price <= 1.0:
                    problems.append(f"{horse}: price must be decimal odds above 1.0, not {price}.")
        if price is None and tier != "OUT":
            problems.append(f"{horse}: price is required for a {tier} runner.")
        if tier == "PART":
            if fraction is None:
                problems.append(f"{horse}: part_fraction is required for a PART runner (0 to 1).")
            else:
                try:
                    fraction = float(fraction)
                except (TypeError, ValueError):
                    problems.append(f"{horse}: part_fraction must be a number from 0 to 1.")
                    fraction = None
                else:
                    if not 0 <= fraction <= 1:
                        problems.append(f"{horse}: part_fraction must be between 0 and 1, not {fraction}.")
        elif fraction is not None:
            problems.append(f"{horse}: part_fraction only applies to PART runners.")
        parsed.append(RunnerInput(horse_id=horse_id, horse=horse, tier=tier, price=price, part_fraction=fraction))

    if problems:
        raise ApiError(400, "INVALID_INPUT", "Invalid input. " + " ".join(problems))
    return total, commission, parsed


def calculate(stake_total: Any, commission_rate: Any, runners: list[dict[str, Any]]) -> DutchResult:
    total, commission, inputs = validate(stake_total, commission_rate, runners)
    q: dict[str, float | None] = {r.horse_id: (1.0 / r.price if r.price else None) for r in inputs}

    profit_runners = [r for r in inputs if r.tier == "PROFIT"]
    break_even_runners = [r for r in inputs if r.tier == "BREAK_EVEN"]
    part_runners = [r for r in inputs if r.tier == "PART"]

    messages: list[str] = []
    feasible = True
    profit_per_win: float | None = None

    sum_q_profit = sum(q[r.horse_id] or 0.0 for r in profit_runners)
    committed = sum(q[r.horse_id] or 0.0 for r in break_even_runners) + sum(
        (r.part_fraction or 0.0) * (q[r.horse_id] or 0.0) for r in part_runners
    )
    if not profit_runners:
        feasible = False
        messages.append("No profit is possible: no runner is set to PROFIT.")
    else:
        candidate = total * (1.0 - sum_q_profit - committed) / sum_q_profit
        if candidate <= 0:
            feasible = False
            needed = total * (sum_q_profit + committed)
            messages.append(
                "No profit is possible at these prices: returning the stake on the PROFIT and BREAK_EVEN runners "
                f"and the part stakes on the PART runners already needs £{needed:.2f} of the £{total:.2f}."
            )
        else:
            profit_per_win = candidate

    figures: list[RunnerFigures] = []
    for r in inputs:
        fig = RunnerFigures(horse_id=r.horse_id, horse=r.horse, tier=r.tier, price=r.price)
        if feasible:
            if r.tier == "PROFIT":
                target = total + (profit_per_win or 0.0)
            elif r.tier == "BREAK_EVEN":
                target = total
            elif r.tier == "PART":
                target = (r.part_fraction or 0.0) * total
            else:
                target = 0.0
            fig.stake = (target / r.price) if (r.price and target) else 0.0
            fig.return_if_wins = target
            fig.net_if_wins = target - total
            fig.net_after_commission = fig.net_if_wins * (1.0 - commission) if fig.net_if_wins > 0 else fig.net_if_wins
        figures.append(fig)

    missing = [r.horse for r in inputs if q[r.horse_id] is None]
    book_q: float | None = None
    if missing:
        verb = "has" if len(missing) == 1 else "have"
        messages.append(
            f"{_join_names(missing)} {verb} no price, so the book, market chances and expected value cannot be worked out."
        )
    else:
        book_q = sum(v for v in q.values() if v is not None)
        for fig in figures:
            fig.market_chance = (q[fig.horse_id] or 0.0) / book_q

    expected_value = expected_value_pct = None
    if feasible and book_q is not None:
        expected_value = sum((fig.market_chance or 0.0) * (fig.net_if_wins or 0.0) for fig in figures)
        expected_value_pct = expected_value / total * 100.0

    for fig in figures:
        if fig.tier not in ("OUT", "PART") or not feasible:
            continue
        loss = -(fig.net_if_wins or 0.0)  # positive: the whole stake for OUT, the unreturned part for PART
        fig.wins_wiped_out = loss / profit_per_win if profit_per_win else None
        if book_q is None:
            continue
        others_q = book_q - (q[fig.horse_id] or 0.0)
        if others_q <= 0:
            continue
        expected_without = sum(
            (q[other.horse_id] or 0.0) * (other.net_if_wins or 0.0) for other in figures if other is not fig
        ) / others_q
        if expected_without > 0:
            fig.break_even_chance = expected_without / (expected_without + loss)
            fig.can_break_even = True
        else:
            fig.break_even_chance = None
            fig.can_break_even = False

    return DutchResult(
        stake_total=total,
        commission_rate=commission,
        feasible=feasible,
        message=" ".join(messages) if messages else None,
        profit_per_win=profit_per_win,
        book_pct=book_q * 100.0 if book_q is not None else None,
        expected_value_gbp=expected_value,
        expected_value_pct=expected_value_pct,
        runners=figures,
    )
