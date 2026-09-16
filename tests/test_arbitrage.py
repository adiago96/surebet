from surebet.engine.arbitrage import evaluate_market
from surebet.models import MarketFamily, MarketKey, OddQuote, Period, SettlementRules


def _mk(family=MarketFamily.MONEYLINE_2WAY, line=None):
    return MarketKey(
        sport_key="tennis_atp_us_open",
        event_id="evt1",
        family=family,
        period=Period.MATCH,
        rules=SettlementRules.STANDARD,
        line=line,
    )


def test_two_way_arbitrage_detected():
    market = _mk()
    legs = {
        "home": OddQuote(bookmaker="A", market=market, selection="home", price_decimal=2.00),
        "away": OddQuote(bookmaker="B", market=market, selection="away", price_decimal=2.37),
    }
    opp = evaluate_market(market, legs)
    assert opp.is_mathematical_arbitrage
    assert opp.profit_pct > 0
    # 1/2.00 + 1/2.37 = 0.9219... -> profit ~ 8.47%
    assert 8.0 < opp.profit_pct < 9.0


def test_two_way_no_arbitrage():
    market = _mk()
    legs = {
        "home": OddQuote(bookmaker="A", market=market, selection="home", price_decimal=1.80),
        "away": OddQuote(bookmaker="B", market=market, selection="away", price_decimal=1.90),
    }
    opp = evaluate_market(market, legs)
    assert not opp.is_mathematical_arbitrage
    assert opp.profit_pct < 0


def test_three_way_arbitrage():
    market = _mk(family=MarketFamily.THREE_WAY)
    legs = {
        "home": OddQuote(bookmaker="A", market=market, selection="home", price_decimal=4.20),
        "draw": OddQuote(bookmaker="B", market=market, selection="draw", price_decimal=4.00),
        "away": OddQuote(bookmaker="C", market=market, selection="away", price_decimal=2.10),
    }
    opp = evaluate_market(market, legs)
    assert opp.is_mathematical_arbitrage
    assert opp.num_bookmakers_involved == 3
