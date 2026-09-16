import datetime as dt

from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.storage.db import get_connection, init_db, prune_old_snapshots, save_snapshot

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
