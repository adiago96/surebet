"""Calculadora de stakes (Fase 7 y 8).

Reparte el bankroll proporcionalmente a 1/cuota para igualar el retorno en
cualquier resultado, y luego aplica las restricciones REALES de las casas:
incremento mínimo de apuesta y stake máximo. El redondeo puede destruir un
arbitraje marginal, así que el resultado siempre se recalcula DESPUÉS de
redondear, nunca antes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from surebet.engine.arbitrage import ArbitrageOpportunity
from surebet.models import OddQuote


@dataclass
class LegStake:
    selection: str
    bookmaker: str
    odd: OddQuote
    raw_stake: float
    rounded_stake: float
    payout_if_wins: float


@dataclass
class StakePlan:
    legs: list[LegStake]
    total_stake: float
    min_payout: float  # el peor de los escenarios (debería ser ~igual en todos si es "clean")
    max_payout: float
    profit_worst_case: float
    roi_pct: float
    arbitrage_survives_rounding: bool
    limited_by_max_stake: bool


def _round_down_to_increment(value: float, increment: float) -> float:
    if increment <= 0:
        return value
    return math.floor(value / increment) * increment


def compute_stake_plan(
    opportunity: ArbitrageOpportunity,
    bankroll: float,
    min_increment_by_bookmaker: dict[str, float] | None = None,
    max_stake_by_bookmaker: dict[str, float] | None = None,
    default_increment: float = 1.0,
    default_max_stake: float | None = None,
) -> StakePlan:
    min_increment_by_bookmaker = min_increment_by_bookmaker or {}
    max_stake_by_bookmaker = max_stake_by_bookmaker or {}

    inv_odds = {sel: 1.0 / q.price_decimal for sel, q in opportunity.legs.items()}
    total_inv = sum(inv_odds.values())

    legs: list[LegStake] = []
    limited_by_max_stake = False

    for selection, quote in opportunity.legs.items():
        raw_stake = bankroll * inv_odds[selection] / total_inv
        increment = min_increment_by_bookmaker.get(quote.bookmaker, default_increment)
        rounded = _round_down_to_increment(raw_stake, increment)
        # nunca por debajo del mínimo de la propia casa si lo conocemos
        if quote.min_stake and rounded < quote.min_stake:
            rounded = quote.min_stake

        cap = max_stake_by_bookmaker.get(quote.bookmaker, quote.max_stake or default_max_stake)
        if cap is not None and rounded > cap:
            rounded = _round_down_to_increment(cap, increment)
            limited_by_max_stake = True

        legs.append(
            LegStake(
                selection=selection,
                bookmaker=quote.bookmaker,
                odd=quote,
                raw_stake=raw_stake,
                rounded_stake=rounded,
                payout_if_wins=rounded * quote.price_decimal,
            )
        )

    total_stake = sum(leg.rounded_stake for leg in legs)
    payouts = [leg.payout_if_wins for leg in legs]
    min_payout = min(payouts) if payouts else 0.0
    max_payout = max(payouts) if payouts else 0.0
    profit_worst_case = min_payout - total_stake
    roi_pct = (profit_worst_case / total_stake * 100.0) if total_stake > 0 else 0.0

    return StakePlan(
        legs=legs,
        total_stake=total_stake,
        min_payout=min_payout,
        max_payout=max_payout,
        profit_worst_case=profit_worst_case,
        roi_pct=roi_pct,
        arbitrage_survives_rounding=profit_worst_case > 0,
        limited_by_max_stake=limited_by_max_stake,
    )
