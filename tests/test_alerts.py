import datetime as dt

from surebet.alerts.telegram import format_alert
from surebet.engine.arbitrage import evaluate_market
from surebet.engine.risk import assess
from surebet.engine.stakes import compute_stake_plan
from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules

MARKET = MarketKey(
    sport_key="soccer_spain_la_liga", event_id="e1", family=MarketFamily.THREE_WAY,
    period=Period.FULL_TIME, rules=SettlementRules.STANDARD,
)
EVENT = Event(
    event_id="e1", sport_key="soccer_spain_la_liga", sport_group="soccer",
    league="LaLiga", home="Espanyol", away="Elche CF",
    commence_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2),
)


def test_alert_is_short_and_uses_team_names_not_home_away():
    legs = {
        "home": OddQuote(bookmaker="Marathonbet", market=MARKET, selection="home", price_decimal=1.95),
        "draw": OddQuote(bookmaker="Pinnacle", market=MARKET, selection="draw", price_decimal=4.00),
        "away": OddQuote(bookmaker="Unibet", market=MARKET, selection="away", price_decimal=4.50),
    }
    opp = evaluate_market(MARKET, legs)
    assert opp.is_mathematical_arbitrage
    plan = compute_stake_plan(opp, bankroll=100.0, default_increment=0.10)
    risk = assess(opp, is_live=False, stake_plan=plan)

    msg = format_alert(EVENT, opp, risk, plan)

    # Debe usar nombres reales, no "home"/"away"/"draw" en crudo
    assert "Espanyol" in msg
    assert "Elche CF" in msg
    assert "Empate" in msg
    assert "home" not in msg and "away" not in msg and "draw" not in msg

    # Debe mencionar la casa y la cuota de cada pata
    assert "Marathonbet" in msg and "Pinnacle" in msg and "Unibet" in msg
    assert "1.95" in msg and "4.00" in msg and "4.50" in msg

    # Debe decir cuánto se gana y no debe llevar el desglose técnico de riesgo
    assert "Ganas" in msg
    assert "execution_risk" not in msg.lower().replace(" ", "_")
    assert "Motivos" not in msg

    # Corto: sin las ~20 líneas del formato técnico anterior
    assert len(msg.splitlines()) <= 12


def test_handicap_selection_label_shows_team_and_signed_line():
    market = MarketKey(
        sport_key="s", event_id="e1", family=MarketFamily.HANDICAP,
        period=Period.FULL_TIME, rules=SettlementRules.STANDARD, line=-1.5,
    )
    legs = {
        "home": OddQuote(bookmaker="Winamax", market=market, selection="home", price_decimal=2.00),
        "away": OddQuote(bookmaker="Bet365", market=market, selection="away", price_decimal=2.37),
    }
    opp = evaluate_market(market, legs)
    plan = compute_stake_plan(opp, bankroll=100.0, default_increment=0.10)
    risk = assess(opp, is_live=False, stake_plan=plan)
    msg = format_alert(EVENT, opp, risk, plan)

    assert "Espanyol (-1.50)" in msg
    assert "Elche CF (+1.50)" in msg
