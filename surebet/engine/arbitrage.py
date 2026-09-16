"""Motor matemático de arbitraje (Fase 4).

Funciona para cualquier mercado de N resultados exhaustivos y mutuamente
excluyentes (2-way, 3-way, hándicap de 2 lados, totals de 2 lados...) porque
matemáticamente todos son el mismo problema:

    arbitraje  <=>  sum(1 / odd_i) < 1   para i en TODAS las selecciones

El motor en sí NO sabe nada de fútbol, tenis o hándicaps: esa responsabilidad
es de `normalize/markets.py`, que es quien garantiza que las cuotas que
llegan aquí realmente cubren el 100% de los resultados posibles con las
mismas reglas de liquidación. Este módulo confía ciegamente en esa garantía.
"""

from __future__ import annotations

from dataclasses import dataclass

from surebet.models import MarketKey, OddQuote


@dataclass
class ArbitrageOpportunity:
    market: MarketKey
    legs: dict[str, OddQuote]  # selection -> mejor cuota
    total_implied_prob: float
    profit_pct: float  # >0 si es arbitraje matemático

    @property
    def is_mathematical_arbitrage(self) -> bool:
        return self.total_implied_prob < 1.0

    @property
    def num_bookmakers_involved(self) -> int:
        return len({q.bookmaker for q in self.legs.values()})

    @property
    def max_leg_age_seconds(self) -> float:
        return max(q.age_seconds for q in self.legs.values())


def evaluate_market(market: MarketKey, legs: dict[str, OddQuote]) -> ArbitrageOpportunity:
    """`legs` debe contener EXACTAMENTE el conjunto de selecciones exhaustivo
    para `market.family` (verificado previamente con
    `normalize.markets.is_exhaustive`). Esta función no vuelve a comprobarlo:
    separar responsabilidades hace que cada capa sea testeable de forma aislada.
    """
    total_implied = sum(1.0 / q.price_decimal for q in legs.values())
    profit_pct = (1.0 / total_implied - 1.0) * 100.0 if total_implied > 0 else float("-inf")
    return ArbitrageOpportunity(
        market=market,
        legs=dict(legs),
        total_implied_prob=total_implied,
        profit_pct=profit_pct,
    )
