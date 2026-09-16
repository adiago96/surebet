import datetime as dt

import pytest
from fastapi.testclient import TestClient

import surebet.scanner as scanner_module
from surebet.collectors.manual import ManualCollector
from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.storage.db import (
    get_connection,
    init_db,
    list_manual_entries,
    list_recent_events,
    market_state,
    upsert_manual_entry,
)

FUTURE = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)

EVENT = Event(
    event_id="manual_e1", sport_key="soccer_spain_la_liga", sport_group="soccer",
    league="LaLiga", home="Real Madrid", away="Elche", commence_time=FUTURE,
)
MARKET = MarketKey(
    sport_key="soccer_spain_la_liga", event_id="manual_e1",
    family=MarketFamily.THREE_WAY, period=Period.FULL_TIME, rules=SettlementRules.STANDARD,
)


def test_upsert_manual_entry_updates_in_place_instead_of_duplicating(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        q1 = OddQuote(bookmaker="bet365", market=MARKET, selection="home", price_decimal=2.00)
        upsert_manual_entry(conn, EVENT, q1)
        upsert_manual_entry(conn, EVENT, q1)  # mismo bookmaker+mercado+selección otra vez

        q2 = OddQuote(bookmaker="bet365", market=MARKET, selection="home", price_decimal=2.05)
        upsert_manual_entry(conn, EVENT, q2)  # misma clave, precio distinto -> debe actualizar, no duplicar
        conn.commit()

        rows = conn.execute("SELECT COUNT(*) FROM manual_entries").fetchone()[0]
        assert rows == 1

        entries = list_manual_entries(conn)
        assert len(entries) == 1
        _, stored_quote = entries[0]
        assert stored_quote.price_decimal == 2.05


def test_upsert_manual_entry_handles_null_line_markets_correctly(tmp_path):
    """THREE_WAY/MONEYLINE_2WAY tienen line=None. SQLite trata cada NULL como
    distinto en comparaciones normales; el lookup debe usar `IS` para que el
    upsert siga funcionando (ver comentario en storage/db.py)."""
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        home_quote = OddQuote(bookmaker="bet365", market=MARKET, selection="home", price_decimal=2.0)
        away_quote = OddQuote(bookmaker="bet365", market=MARKET, selection="away", price_decimal=3.0)
        upsert_manual_entry(conn, EVENT, home_quote)
        upsert_manual_entry(conn, EVENT, away_quote)
        upsert_manual_entry(conn, EVENT, home_quote)  # no debe crear una tercera fila
        conn.commit()

        rows = conn.execute("SELECT COUNT(*) FROM manual_entries").fetchone()[0]
        assert rows == 2


def test_market_state_combines_snapshots_and_manual_entries(tmp_path):
    from surebet.storage.db import save_snapshot

    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        auto_quote = OddQuote(
            bookmaker="pinnacle", market=MARKET, selection="away", price_decimal=2.10, source="pinnacle"
        )
        save_snapshot(conn, EVENT, [auto_quote])

        manual_quote = OddQuote(bookmaker="bet365", market=MARKET, selection="home", price_decimal=2.05)
        upsert_manual_entry(conn, EVENT, manual_quote)
        conn.commit()

        combined = market_state(conn, MARKET)
        sources = {(q.bookmaker, q.selection, q.source) for q in combined}
        assert ("pinnacle", "away", "pinnacle") in sources
        assert ("bet365", "home", "manual") in sources


def test_list_recent_events_only_returns_future_matches(tmp_path):
    from surebet.storage.db import save_snapshot

    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    past_event = Event(
        event_id="past1", sport_key="s", sport_group="tennis", league="ATP",
        home="A", away="B", commence_time=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2),
    )
    past_market = MarketKey(
        sport_key="s", event_id="past1", family=MarketFamily.MONEYLINE_2WAY,
        period=Period.MATCH, rules=SettlementRules.STANDARD,
    )
    with get_connection(db_path) as conn:
        save_snapshot(conn, past_event, [OddQuote(bookmaker="x", market=past_market, selection="home", price_decimal=1.5)])
        upsert_manual_entry(conn, EVENT, OddQuote(bookmaker="bet365", market=MARKET, selection="home", price_decimal=2.0))
        conn.commit()

        events = list_recent_events(conn)
        event_ids = {e["event_id"] for e in events}
        assert "manual_e1" in event_ids
        assert "past1" not in event_ids


@pytest.mark.asyncio
async def test_manual_collector_returns_active_entries_as_odd_quotes(tmp_path, monkeypatch):
    # `settings` es el mismo objeto compartido que usan `scanner`, `storage.db`
    # y `collectors.manual`, así que parchear este atributo basta para
    # redirigir también a `ManualCollector.fetch()` (que no recibe el path
    # explícitamente, igual que el resto de collectors).
    monkeypatch.setattr(scanner_module.settings, "sqlite_path", str(tmp_path / "collector.db"))

    init_db()
    with get_connection() as conn:
        upsert_manual_entry(conn, EVENT, OddQuote(bookmaker="bet365", market=MARKET, selection="home", price_decimal=2.0))
        conn.commit()

    events, quotes = await ManualCollector().fetch()
    assert len(events) == 1 and events[0].event_id == "manual_e1"
    assert len(quotes) == 1 and quotes[0].bookmaker == "bet365" and quotes[0].source == "manual"


@pytest.mark.asyncio
async def test_manual_quote_endpoint_detects_arbitrage_against_known_odds(tmp_path, monkeypatch):
    """Simula el flujo real: ya hay una cuota automática (Pinnacle) para
    'away', y el usuario mete a mano una cuota de bet365 para 'home' que
    cierra un arbitraje. La respuesta debe reflejarlo al instante, sin
    esperar a un ciclo del scanner."""
    from surebet.api import main as api_main
    from surebet.storage.db import save_snapshot

    db_path = str(tmp_path / "api.db")
    monkeypatch.setattr(scanner_module.settings, "sqlite_path", db_path)

    sent = []

    async def fake_send(text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(scanner_module, "send_telegram_message", fake_send)

    init_db(db_path)
    with get_connection(db_path) as conn:
        # draw/away ya conocidos por Pinnacle; falta "home". Con home=2.10 el
        # margen es ~5% (1/2.10 + 1/4.20 + 1/4.20 = 0.9524), por debajo del
        # umbral de sospechoso (12%) -> debe salir VALID_ARB, no SUSPICIOUS_ARB.
        auto_quote = OddQuote(
            bookmaker="pinnacle", market=MARKET, selection="draw", price_decimal=4.20, source="pinnacle"
        )
        away_quote = OddQuote(
            bookmaker="pinnacle", market=MARKET, selection="away", price_decimal=4.20, source="pinnacle"
        )
        save_snapshot(conn, EVENT, [auto_quote, away_quote])
        conn.commit()

    payload = {
        "bookmaker": "bet365",
        "sport_key": MARKET.sport_key,
        "event_id": MARKET.event_id,
        "home": EVENT.home,
        "away": EVENT.away,
        "sport_group": EVENT.sport_group,
        "league": EVENT.league,
        "commence_time": EVENT.commence_time.isoformat(),
        "family": "three_way",
        "selection": "home",
        "price_decimal": 2.10,
    }
    with TestClient(api_main.app) as client:
        resp = client.post("/api/manual/quote", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "VALID_ARB"
    assert data["profit_pct"] > 0
    assert len(sent) == 1  # se alertó por Telegram igual que con fuentes automáticas
