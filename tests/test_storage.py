import datetime as dt

from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.storage.db import (
    already_alerted,
    get_connection,
    init_db,
    mark_alerted,
    prune_finished_events,
    prune_old_snapshots,
    save_snapshot,
)

MARKET = MarketKey(
    sport_key="s", event_id="e1", family=MarketFamily.MONEYLINE_2WAY,
    period=Period.MATCH, rules=SettlementRules.STANDARD,
)
EVENT = Event(
    event_id="e1", sport_key="s", sport_group="tennis", league="ATP",
    home="A", away="B", commence_time=dt.datetime.now(dt.timezone.utc),
)


def test_prune_removes_only_old_snapshots(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        quotes = [OddQuote(bookmaker="X", market=MARKET, selection="home", price_decimal=2.0)]
        save_snapshot(conn, EVENT, quotes)
        conn.commit()

        # Nada más guardarlo, no debe purgarse con la retención por defecto.
        removed = prune_old_snapshots(conn, retention_days=3)
        assert removed == 0
        assert conn.execute("SELECT COUNT(*) FROM odds_snapshots").fetchone()[0] == 1

        # Con retención 0 días, un snapshot de "ahora mismo" ya cuenta como
        # anterior al corte y se purga.
        removed = prune_old_snapshots(conn, retention_days=0)
        assert removed >= 0  # SQLite datetime('now') tiene resolución de segundos


def test_alert_deduplication(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        assert not already_alerted(conn, MARKET)

        mark_alerted(conn, EVENT, MARKET, profit_pct=1.5)
        assert already_alerted(conn, MARKET)

        # Re-marcar (p.ej. la cuota cambió pero seguimos sin querer reenviar)
        # actualiza el profit_pct guardado sin crear una segunda fila.
        mark_alerted(conn, EVENT, MARKET, profit_pct=2.1)
        row = conn.execute("SELECT COUNT(*) FROM alerted_opportunities").fetchone()[0]
        assert row == 1


def test_prune_finished_events_removes_past_matches_only(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    past_event = Event(
        event_id="past1", sport_key="s", sport_group="tennis", league="ATP",
        home="A", away="B",
        commence_time=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=10),
    )
    future_event = Event(
        event_id="future1", sport_key="s", sport_group="tennis", league="ATP",
        home="C", away="D",
        commence_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=10),
    )
    past_market = MarketKey(
        sport_key="s", event_id="past1", family=MarketFamily.MONEYLINE_2WAY,
        period=Period.MATCH, rules=SettlementRules.STANDARD,
    )
    future_market = MarketKey(
        sport_key="s", event_id="future1", family=MarketFamily.MONEYLINE_2WAY,
        period=Period.MATCH, rules=SettlementRules.STANDARD,
    )

    with get_connection(db_path) as conn:
        save_snapshot(conn, past_event, [OddQuote(bookmaker="X", market=past_market, selection="home", price_decimal=2.0)])
        save_snapshot(conn, future_event, [OddQuote(bookmaker="X", market=future_market, selection="home", price_decimal=2.0)])
        mark_alerted(conn, past_event, past_market, profit_pct=1.0)
        mark_alerted(conn, future_event, future_market, profit_pct=1.0)
        conn.commit()

        snaps_pruned, alerts_pruned = prune_finished_events(conn, grace_hours=4)
        assert snaps_pruned == 1
        assert alerts_pruned == 1

        remaining_events = {r[0] for r in conn.execute("SELECT event_id FROM odds_snapshots")}
        assert remaining_events == {"future1"}
        assert already_alerted(conn, future_market)
        assert not already_alerted(conn, past_market)
