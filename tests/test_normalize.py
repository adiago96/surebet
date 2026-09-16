import datetime as dt

from surebet.models import MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.normalize.events import name_similarity, same_fixture
from surebet.normalize.markets import (
    best_price_per_selection,
    group_by_market,
    handicap_home_perspective_line,
    is_exhaustive,
)


def test_handicap_home_perspective_line_matches_opposite_side():
    # "Real Madrid -1.5" y "Elche +1.5" deben acabar con el MISMO line
    # home-perspective para poder agruparse.
    madrid_line = handicap_home_perspective_line(is_home_selection=True, point=-1.5)
    elche_line = handicap_home_perspective_line(is_home_selection=False, point=1.5)
    assert madrid_line == elche_line == -1.5


def test_group_by_market_groups_complementary_handicap_sides():
    market = MarketKey(
        sport_key="soccer_spain_la_liga", event_id="e1", family=MarketFamily.HANDICAP,
        period=Period.FULL_TIME, rules=SettlementRules.STANDARD, line=-1.5,
    )
    q1 = OddQuote(bookmaker="Winamax", market=market, selection="home", price_decimal=2.00)
    q2 = OddQuote(bookmaker="Bet365", market=market, selection="away", price_decimal=2.37)
    groups = group_by_market([q1, q2])
    assert len(groups) == 1
    group = list(groups.values())[0]
    assert is_exhaustive(market, group)
    best = best_price_per_selection(group)
    assert best["home"].bookmaker == "Winamax"
    assert best["away"].bookmaker == "Bet365"


def test_different_period_never_groups_together():
    full = MarketKey(
        sport_key="s", event_id="e1", family=MarketFamily.MONEYLINE_2WAY,
        period=Period.FULL_TIME, rules=SettlementRules.STANDARD,
    )
    first_half = MarketKey(
        sport_key="s", event_id="e1", family=MarketFamily.MONEYLINE_2WAY,
        period=Period.FIRST_HALF, rules=SettlementRules.STANDARD,
    )
    q1 = OddQuote(bookmaker="A", market=full, selection="home", price_decimal=2.0)
    q2 = OddQuote(bookmaker="B", market=first_half, selection="away", price_decimal=2.5)
    groups = group_by_market([q1, q2])
    assert len(groups) == 2  # NUNCA deben mezclarse en un solo grupo


def test_non_exhaustive_market_is_rejected():
    market = MarketKey(
        sport_key="s", event_id="e1", family=MarketFamily.THREE_WAY,
        period=Period.FULL_TIME, rules=SettlementRules.STANDARD,
    )
    # Falta la selección "draw": no se puede evaluar como 1X2 completo.
    quotes = [
        OddQuote(bookmaker="A", market=market, selection="home", price_decimal=2.0),
        OddQuote(bookmaker="B", market=market, selection="away", price_decimal=3.0),
    ]
    assert not is_exhaustive(market, quotes)


def test_same_fixture_matches_despite_minor_name_differences():
    t = dt.datetime(2026, 9, 20, 18, 0, tzinfo=dt.timezone.utc)
    assert same_fixture("Real Madrid CF", "Elche CF", t, "Real Madrid", "Elche", t)


def test_same_fixture_rejects_different_kickoff_time():
    t1 = dt.datetime(2026, 9, 20, 18, 0, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2026, 9, 20, 21, 0, tzinfo=dt.timezone.utc)
    assert not same_fixture("Real Madrid", "Elche", t1, "Real Madrid", "Elche", t2)


def test_name_similarity_basic():
    assert name_similarity("FC Barcelona", "Barcelona") > 0.6
