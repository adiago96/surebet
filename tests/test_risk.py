import datetime as dt

from surebet.engine.arbitrage import evaluate_market
from surebet.engine.risk import DataFreshness, Verdict, assess, classify_freshness
from surebet.engine.stakes import compute_stake_plan
from surebet.models import MarketFamily, MarketKey, OddQuote, Period, SettlementRules, utcnow

MARKET = MarketKey(
    sport_key="s", event_id="e1", family=MarketFamily.MONEYLINE_2WAY,
    period=Period.MATCH, rules=SettlementRules.STANDARD,
)


def test_fresh_prematch_odds_yield_valid_arb():
    legs = {
        "home": OddQuote(bookmaker="A", market=MARKET, selection="home", price_decimal=2.05),
        "away": OddQuote(bookmaker="B", market=MARKET, selection="away", price_decimal=2.05),
    }
    opp = evaluate_market(MARKET, legs)
    plan = compute_stake_plan(opp, bankroll=100.0, default_increment=0.01)
    risk = assess(opp, is_live=False, stake_plan=plan)
    assert risk.is_mathematical_arbitrage
    assert risk.verdict == Verdict.VALID_ARB
    assert risk.freshness == DataFreshness.FRESH


def test_stale_odds_are_flagged_do_not_bet():
    old = utcnow() - dt.timedelta(seconds=3600)
    legs = {
        "home": OddQuote(bookmaker="A", market=MARKET, selection="home", price_decimal=2.05, received_at=old),
        "away": OddQuote(bookmaker="B", market=MARKET, selection="away", price_decimal=2.05),
    }
    opp = evaluate_market(MARKET, legs)
    risk = assess(opp, is_live=False)
    assert risk.verdict == Verdict.STALE_DO_NOT_BET
    assert not risk.is_executable_candidate


def test_suspiciously_high_margin_is_flagged():
    legs = {
        "home": OddQuote(bookmaker="A", market=MARKET, selection="home", price_decimal=5.0),
        "away": OddQuote(bookmaker="B", market=MARKET, selection="away", price_decimal=5.0),
    }
    opp = evaluate_market(MARKET, legs)  # profit_pct = 100%: claramente sospechoso
    risk = assess(opp, is_live=False)
    assert risk.verdict == Verdict.SUSPICIOUS_ARB


def test_classify_freshness_thresholds():
    assert classify_freshness(10, is_live=False) == DataFreshness.FRESH
    assert classify_freshness(500, is_live=False) == DataFreshness.AGING
    assert classify_freshness(1000, is_live=False) == DataFreshness.STALE
    assert classify_freshness(3, is_live=True) == DataFreshness.FRESH
    assert classify_freshness(15, is_live=True) == DataFreshness.AGING
    assert classify_freshness(30, is_live=True) == DataFreshness.STALE


def test_rounding_unprofitable_is_never_labeled_valid_arb():
    # Margen matemático positivo pero minúsculo: con un incremento de apuesta
    # de 5€ el redondeo se lo come. Antes de este fix, `assess()` etiquetaba
    # esto como VALID_ARB (y el scanner lo alertaba por Telegram) pese a que
    # el plan de stakes real da pérdidas. Ver conversación: "todos los
    # resultados... tienen pérdidas y me lo saca como surebets".
    legs = {
        "home": OddQuote(bookmaker="A", market=MARKET, selection="home", price_decimal=2.02),
        "away": OddQuote(bookmaker="B", market=MARKET, selection="away", price_decimal=2.00),
    }
    opp = evaluate_market(MARKET, legs)
    assert opp.is_mathematical_arbitrage
    plan = compute_stake_plan(opp, bankroll=10.0, default_increment=5.0)
    assert not plan.arbitrage_survives_rounding

    risk = assess(opp, is_live=False, stake_plan=plan)
    assert risk.verdict == Verdict.ROUNDING_UNPROFITABLE
    assert risk.verdict != Verdict.VALID_ARB
    assert not risk.is_executable_candidate


def test_no_arbitrage_when_margin_negative():
    legs = {
        "home": OddQuote(bookmaker="A", market=MARKET, selection="home", price_decimal=1.80),
        "away": OddQuote(bookmaker="B", market=MARKET, selection="away", price_decimal=1.80),
    }
    opp = evaluate_market(MARKET, legs)
    risk = assess(opp, is_live=False)
    assert risk.verdict == Verdict.NOT_ARBITRAGE
    assert not risk.is_executable_candidate
