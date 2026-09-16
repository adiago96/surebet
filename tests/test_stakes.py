from surebet.engine.arbitrage import evaluate_market
from surebet.engine.stakes import compute_stake_plan
from surebet.models import MarketFamily, MarketKey, OddQuote, Period, SettlementRules

MARKET = MarketKey(
    sport_key="soccer_spain_la_liga",
    event_id="evt1",
    family=MarketFamily.HANDICAP,
    period=Period.FULL_TIME,
    rules=SettlementRules.STANDARD,
    line=-1.5,
)


def test_stake_plan_equalizes_payout():
    legs = {
        "home": OddQuote(bookmaker="Winamax", market=MARKET, selection="home", price_decimal=2.00),
        "away": OddQuote(bookmaker="Bet365", market=MARKET, selection="away", price_decimal=2.37),
    }
    opp = evaluate_market(MARKET, legs)
    plan = compute_stake_plan(opp, bankroll=100.0, default_increment=0.01)

    assert plan.arbitrage_survives_rounding
    assert plan.total_stake <= 100.0 + 1e-6
    # Los dos retornos deben ser prácticamente idénticos (redondeo mínimo)
    payouts = [leg.payout_if_wins for leg in plan.legs]
    assert abs(payouts[0] - payouts[1]) < 0.05
    assert plan.profit_worst_case > 0


def test_rounding_can_destroy_marginal_arbitrage():
    # Margen pequeño + reparto no múltiplo exacto del incremento de apuesta
    # (5€) debería poder destruir el arbitraje tras redondear hacia abajo.
    market = MarketKey(
        sport_key="x", event_id="e", family=MarketFamily.MONEYLINE_2WAY,
        period=Period.MATCH, rules=SettlementRules.STANDARD, line=None,
    )
    legs = {
        "home": OddQuote(bookmaker="A", market=market, selection="home", price_decimal=2.02),
        "away": OddQuote(bookmaker="B", market=market, selection="away", price_decimal=2.00),
    }
    opp = evaluate_market(market, legs)
    assert opp.is_mathematical_arbitrage
    plan = compute_stake_plan(opp, bankroll=10.0, default_increment=5.0)
    assert not plan.arbitrage_survives_rounding


def test_max_stake_limit_is_respected_and_flagged():
    legs = {
        "home": OddQuote(bookmaker="A", market=MARKET, selection="home", price_decimal=2.00, max_stake=5.0),
        "away": OddQuote(bookmaker="B", market=MARKET, selection="away", price_decimal=2.37),
    }
    opp = evaluate_market(MARKET, legs)
    plan = compute_stake_plan(opp, bankroll=1000.0, default_increment=0.01)
    home_leg = next(leg for leg in plan.legs if leg.selection == "home")
    assert home_leg.rounded_stake <= 5.0
    assert plan.limited_by_max_stake
