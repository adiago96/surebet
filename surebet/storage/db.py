"""Persistencia en SQLite: snapshots de cuotas (para backtest, Fase 13) y
oportunidades detectadas (para el dashboard y el histórico de alertas).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from surebet.config import settings
from surebet.engine.arbitrage import ArbitrageOpportunity
from surebet.engine.risk import RiskAssessment
from surebet.engine.stakes import StakePlan
from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules

# Separado en dos scripts (tablas / índices) a propósito: `CREATE TABLE IF
# NOT EXISTS` no migra columnas nuevas a una tabla que ya existía con un
# esquema más antiguo (p.ej. un data/surebet.db de una fase anterior del
# proyecto sin `commence_time`), así que si un `CREATE INDEX` sobre esa
# columna se ejecutara justo después, fallaría con "no such column". El paso
# `_ensure_columns()` entre medias (ver `init_db`) migra esas tablas viejas
# antes de que se creen los índices que dependen de las columnas nuevas.
_TABLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    source TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    home TEXT,
    away TEXT,
    commence_time TEXT,
    family TEXT NOT NULL,
    period TEXT NOT NULL,
    rules TEXT NOT NULL,
    line REAL,
    selection TEXT NOT NULL,
    price_decimal REAL NOT NULL
);

-- Evita reenviar la misma alerta de Telegram en cada pasada mientras el
-- partido siga sin empezar: una fila por mercado (evento+familia+periodo+
-- reglas+línea) ya alertado. Se purga junto con odds_snapshots cuando el
-- partido ya ha empezado (ver prune_finished_events).
CREATE TABLE IF NOT EXISTS alerted_opportunities (
    market_key TEXT PRIMARY KEY,
    sport_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    commence_time TEXT,
    first_alerted_at TEXT NOT NULL,
    last_profit_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    home TEXT,
    away TEXT,
    family TEXT NOT NULL,
    period TEXT NOT NULL,
    line REAL,
    profit_pct REAL NOT NULL,
    verdict TEXT NOT NULL,
    freshness TEXT NOT NULL,
    execution_risk INTEGER NOT NULL,
    max_age_seconds REAL NOT NULL,
    total_stake REAL,
    profit_worst_case REAL,
    roi_pct REAL,
    legs_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL
);

-- Cuotas introducidas a mano desde el dashboard ("Captura rápida"): el
-- usuario navega él mismo a bet365/Winamax ES/William Hill/Bwin/Unibet/
-- Codere/Sportium (casas sin fuente automática gratuita, ver
-- docs/INVESTIGACION_Y_DISENO.md) y teclea la cuota que ve. No hay scraping
-- ni automatización de ningún tipo: es una entrada de datos manual que
-- alimenta el mismo `MarketKey`/motor de arbitraje que las fuentes automáticas.
CREATE TABLE IF NOT EXISTS manual_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    sport_group TEXT NOT NULL,
    league TEXT NOT NULL,
    commence_time TEXT NOT NULL,
    family TEXT NOT NULL,
    period TEXT NOT NULL,
    rules TEXT NOT NULL,
    line REAL,
    selection TEXT NOT NULL,
    price_decimal REAL NOT NULL,
    min_stake REAL NOT NULL DEFAULT 0,
    max_stake REAL
);

-- Libro de apuestas REALMENTE colocadas por el usuario ("Mis apuestas" en el
-- dashboard) — distinto de `opportunities`, que son detecciones automáticas
-- o candidatas, no confirmación de que se apostó de verdad. Guarda en qué
-- casas se apostó cada pierna, a qué cuota y con qué stake, y el resultado
-- real una vez se liquida, para poder comparar beneficio teórico vs real.
CREATE TABLE IF NOT EXISTS placed_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placed_at TEXT NOT NULL,
    opportunity_id INTEGER,
    sport_key TEXT,
    event_id TEXT,
    home TEXT,
    away TEXT,
    market TEXT,
    line REAL,
    legs_json TEXT NOT NULL,
    total_staked REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    total_returned REAL,
    profit REAL,
    notes TEXT
);
"""

_INDEXES_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_snapshots_event ON odds_snapshots (sport_key, event_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON odds_snapshots (received_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_commence ON odds_snapshots (commence_time);
CREATE INDEX IF NOT EXISTS idx_alerted_commence ON alerted_opportunities (commence_time);
CREATE INDEX IF NOT EXISTS idx_opps_time ON opportunities (detected_at);
CREATE INDEX IF NOT EXISTS idx_opps_sport ON opportunities (sport_key);
CREATE INDEX IF NOT EXISTS idx_manual_event ON manual_entries (sport_key, event_id);
CREATE INDEX IF NOT EXISTS idx_manual_lookup
    ON manual_entries (bookmaker, sport_key, event_id, family, period, rules, line, selection);
CREATE INDEX IF NOT EXISTS idx_bets_time ON placed_bets (placed_at);
CREATE INDEX IF NOT EXISTS idx_bets_status ON placed_bets (status);
"""

# Columnas añadidas al esquema en versiones posteriores a la creación
# original de la tabla. Una base de datos real creada con una versión más
# antigua del código (como puede pasar tras semanas de uso) puede tener la
# tabla sin esa columna: `CREATE TABLE IF NOT EXISTS` no la añade sola.
_COLUMNS_ADDED_LATER: dict[str, list[tuple[str, str]]] = {
    "odds_snapshots": [("commence_time", "TEXT")],
    "alerted_opportunities": [("commence_time", "TEXT")],
}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, columns in _COLUMNS_ADDED_LATER.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # la tabla no existe todavía: el script de tablas ya la crea completa
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


@contextmanager
def get_connection(path: str | None = None):
    db_path = path or settings.sqlite_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with get_connection(path) as conn:
        conn.executescript(_TABLES_SCHEMA)
        _ensure_columns(conn)
        conn.executescript(_INDEXES_SCHEMA)
        conn.commit()


def save_snapshot(conn: sqlite3.Connection, event: Event, quotes: list[OddQuote]) -> None:
    rows = [
        (
            q.received_at.isoformat(),
            q.bookmaker,
            q.source,
            q.market.sport_key,
            q.market.event_id,
            event.home,
            event.away,
            event.commence_time.isoformat(),
            q.market.family.value,
            q.market.period.value,
            q.market.rules.value,
            q.market.line,
            q.selection,
            q.price_decimal,
        )
        for q in quotes
    ]
    conn.executemany(
        """INSERT INTO odds_snapshots
           (received_at, bookmaker, source, sport_key, event_id, home, away,
            commence_time, family, period, rules, line, selection, price_decimal)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )


def _market_key_str(market: MarketKey) -> str:
    m = market
    return f"{m.sport_key}|{m.event_id}|{m.family.value}|{m.period.value}|{m.rules.value}|{m.line}"


def already_alerted(conn: sqlite3.Connection, market: MarketKey) -> bool:
    row = conn.execute(
        "SELECT 1 FROM alerted_opportunities WHERE market_key = ?", (_market_key_str(market),)
    ).fetchone()
    return row is not None


def mark_alerted(conn: sqlite3.Connection, event: Event, market: MarketKey, profit_pct: float) -> None:
    conn.execute(
        """INSERT INTO alerted_opportunities
               (market_key, sport_key, event_id, commence_time, first_alerted_at, last_profit_pct)
           VALUES (?,?,?,?,datetime('now'),?)
           ON CONFLICT(market_key) DO UPDATE SET last_profit_pct = excluded.last_profit_pct""",
        (_market_key_str(market), market.sport_key, market.event_id, event.commence_time.isoformat(), profit_pct),
    )


def save_opportunity(
    conn: sqlite3.Connection,
    event: Event,
    opportunity: ArbitrageOpportunity,
    risk: RiskAssessment,
    stake_plan: StakePlan | None,
) -> int:
    legs = {
        sel: {
            "bookmaker": q.bookmaker,
            "price_decimal": q.price_decimal,
            "age_seconds": q.age_seconds,
        }
        for sel, q in opportunity.legs.items()
    }
    cur = conn.execute(
        """INSERT INTO opportunities
           (detected_at, sport_key, event_id, home, away, family, period, line,
            profit_pct, verdict, freshness, execution_risk, max_age_seconds,
            total_stake, profit_worst_case, roi_pct, legs_json, reasons_json)
           VALUES (datetime('now'), ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            opportunity.market.sport_key,
            opportunity.market.event_id,
            event.home,
            event.away,
            opportunity.market.family.value,
            opportunity.market.period.value,
            opportunity.market.line,
            opportunity.profit_pct,
            risk.verdict.value,
            risk.freshness.value,
            risk.execution_risk_score,
            risk.max_age_seconds,
            stake_plan.total_stake if stake_plan else None,
            stake_plan.profit_worst_case if stake_plan else None,
            stake_plan.roi_pct if stake_plan else None,
            json.dumps(legs),
            json.dumps(risk.reasons),
        ),
    )
    return cur.lastrowid


def prune_old_snapshots(conn: sqlite3.Connection, retention_days: int | None = None) -> int:
    """Borra snapshots de cuotas antiguos para que la base de datos no crezca
    sin límite. Un solo pase de Pinnacle ya genera ~47.000 filas (~40 MB); sin
    esto, un sistema "corriendo infinitamente" (Fase 13/objetivo del usuario)
    acabaría llenando el disco. `opportunities` (mucho más pequeña, una fila
    por oportunidad detectada, no por cuota cruda) nunca se purga: es el
    histórico real para el backtest.
    """
    days = retention_days if retention_days is not None else settings.snapshot_retention_days
    # `received_at`/`commence_time` se guardan con `datetime.isoformat()` de
    # Python ("...T...+00:00"), mientras que `datetime('now', ...)` de SQLite
    # produce "... ..." sin "T" ni offset. Comparar las cadenas crudas falla
    # cuando ambas fechas caen en el mismo día calendario (el carácter "T",
    # 0x54, ordena por encima del espacio, 0x20). Envolver la columna en
    # `datetime(...)` normaliza ambos lados al mismo formato comparable.
    cur = conn.execute(
        f"DELETE FROM odds_snapshots WHERE datetime(received_at) < datetime('now', '-{int(days)} days')"
    )
    return cur.rowcount


def prune_finished_events(conn: sqlite3.Connection, grace_hours: int | None = None) -> tuple[int, int]:
    """Borra snapshots y alertas ya registradas de partidos cuya hora de
    inicio (`commence_time`) ya pasó (+ un margen de gracia para cubrir la
    duración del partido). Esto es lo que de verdad mantiene la base de datos
    pequeña: no tiene sentido seguir guardando ni "recordando" un partido que
    ya se ha jugado. `prune_old_snapshots` sigue existiendo como red de
    seguridad para filas sin `commence_time` fiable.

    Devuelve (snapshots_borrados, alertas_olvidadas).
    """
    hours = grace_hours if grace_hours is not None else settings.finished_event_grace_hours
    cutoff = f"datetime('now', '-{int(hours)} hours')"
    # Ver comentario de `prune_old_snapshots`: `datetime(commence_time)`
    # normaliza el ISO 8601 con "T"/offset de Python al formato de SQLite
    # antes de comparar.
    snap_cur = conn.execute(
        f"DELETE FROM odds_snapshots WHERE commence_time IS NOT NULL AND datetime(commence_time) < {cutoff}"
    )
    alert_cur = conn.execute(
        f"DELETE FROM alerted_opportunities WHERE commence_time IS NOT NULL AND datetime(commence_time) < {cutoff}"
    )
    return snap_cur.rowcount, alert_cur.rowcount


def recent_opportunities(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities ORDER BY detected_at DESC LIMIT ?", (limit,)
    ).fetchall()


def upsert_manual_entry(conn: sqlite3.Connection, event: Event, quote: OddQuote) -> None:
    """Inserta o actualiza (mismo bookmaker+mercado+selección) una cuota
    introducida a mano. Usa un SELECT+UPDATE/INSERT explícito en vez de un
    UNIQUE + ON CONFLICT porque SQLite trata cada NULL de `line` como
    distinto en un índice único (los mercados sin línea, como 1X2, tienen
    `line IS NULL`), lo que rompería el upsert precisamente en esos mercados.
    """
    m = quote.market
    existing = conn.execute(
        """SELECT id FROM manual_entries
           WHERE bookmaker = ? AND sport_key = ? AND event_id = ? AND family = ?
             AND period = ? AND rules = ? AND line IS ? AND selection = ?""",
        (quote.bookmaker, m.sport_key, m.event_id, m.family.value, m.period.value,
         m.rules.value, m.line, quote.selection),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE manual_entries
               SET updated_at = datetime('now'), price_decimal = ?, min_stake = ?,
                   max_stake = ?, home = ?, away = ?, commence_time = ?
               WHERE id = ?""",
            (quote.price_decimal, quote.min_stake, quote.max_stake, event.home, event.away,
             event.commence_time.isoformat(), existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO manual_entries
                   (entered_at, updated_at, bookmaker, sport_key, event_id, home, away,
                    sport_group, league, commence_time, family, period, rules, line,
                    selection, price_decimal, min_stake, max_stake)
               VALUES (datetime('now'), datetime('now'), ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (quote.bookmaker, m.sport_key, m.event_id, event.home, event.away,
             event.sport_group, event.league, event.commence_time.isoformat(),
             m.family.value, m.period.value, m.rules.value, m.line,
             quote.selection, quote.price_decimal, quote.min_stake, quote.max_stake),
        )


def list_manual_entries(conn: sqlite3.Connection, active_only: bool = True) -> list[tuple[Event, OddQuote]]:
    """Reconstruye (Event, OddQuote) de cada entrada manual. `active_only`
    excluye partidos cuya hora de inicio ya pasó (mismo criterio que
    `prune_finished_events` para las fuentes automáticas)."""
    query = "SELECT * FROM manual_entries"
    if active_only:
        # Ver comentario de `prune_old_snapshots` sobre normalizar con
        # `datetime(...)` antes de comparar contra `datetime('now')`.
        query += " WHERE datetime(commence_time) > datetime('now')"
    rows = conn.execute(query).fetchall()

    out: list[tuple[Event, OddQuote]] = []
    for r in rows:
        event = Event(
            event_id=r["event_id"], sport_key=r["sport_key"], sport_group=r["sport_group"],
            league=r["league"], home=r["home"], away=r["away"],
            commence_time=datetime.fromisoformat(r["commence_time"]),
        )
        market = MarketKey(
            sport_key=r["sport_key"], event_id=r["event_id"],
            family=MarketFamily(r["family"]), period=Period(r["period"]),
            rules=SettlementRules(r["rules"]), line=r["line"],
        )
        quote = OddQuote(
            bookmaker=r["bookmaker"], market=market, selection=r["selection"],
            price_decimal=r["price_decimal"], source="manual",
            received_at=datetime.fromisoformat(r["updated_at"]),
            min_stake=r["min_stake"], max_stake=r["max_stake"],
        )
        out.append((event, quote))
    return out


def list_recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Eventos próximos conocidos (por fuentes automáticas o ya introducidos a
    mano), para rellenar el desplegable de "Captura rápida" sin que el usuario
    tenga que teclear el evento entero desde cero."""
    rows = conn.execute(
        """SELECT sport_key, event_id, home, away, commence_time FROM (
               SELECT sport_key, event_id, home, away, commence_time
               FROM odds_snapshots WHERE datetime(commence_time) > datetime('now')
               UNION
               SELECT sport_key, event_id, home, away, commence_time
               FROM manual_entries WHERE datetime(commence_time) > datetime('now')
           )
           GROUP BY sport_key, event_id
           ORDER BY commence_time ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def market_state(conn: sqlite3.Connection, market: MarketKey) -> list[OddQuote]:
    """Todas las cuotas conocidas (automáticas + manuales) para un `MarketKey`
    exacto. Se usa para evaluar arbitraje al instante cuando se añade una
    cuota manual, sin esperar al siguiente ciclo del scanner."""
    quotes: list[OddQuote] = []

    snap_rows = conn.execute(
        """SELECT bookmaker, source, selection, price_decimal, received_at
           FROM odds_snapshots
           WHERE sport_key = ? AND event_id = ? AND family = ? AND period = ?
             AND rules = ? AND line IS ?""",
        (market.sport_key, market.event_id, market.family.value, market.period.value,
         market.rules.value, market.line),
    ).fetchall()
    for r in snap_rows:
        quotes.append(OddQuote(
            bookmaker=r["bookmaker"], market=market, selection=r["selection"],
            price_decimal=r["price_decimal"], source=r["source"],
            received_at=datetime.fromisoformat(r["received_at"]),
        ))

    manual_rows = conn.execute(
        """SELECT bookmaker, selection, price_decimal, updated_at, min_stake, max_stake
           FROM manual_entries
           WHERE sport_key = ? AND event_id = ? AND family = ? AND period = ?
             AND rules = ? AND line IS ?""",
        (market.sport_key, market.event_id, market.family.value, market.period.value,
         market.rules.value, market.line),
    ).fetchall()
    for r in manual_rows:
        quotes.append(OddQuote(
            bookmaker=r["bookmaker"], market=market, selection=r["selection"],
            price_decimal=r["price_decimal"], source="manual",
            received_at=datetime.fromisoformat(r["updated_at"]),
            min_stake=r["min_stake"], max_stake=r["max_stake"],
        ))

    return quotes


def save_placed_bet(
    conn: sqlite3.Connection,
    legs: list[dict],
    opportunity_id: int | None = None,
    sport_key: str | None = None,
    event_id: str | None = None,
    home: str | None = None,
    away: str | None = None,
    market: str | None = None,
    line: float | None = None,
    notes: str | None = None,
) -> int:
    """`legs` es una lista de `{"bookmaker": ..., "selection": ..., "odds": ...,
    "stake": ...}`, una por casa/pierna del surebet. `total_staked` se
    recalcula aquí a partir de las piernas (nunca se confía en un total que
    venga ya calculado del cliente)."""
    total_staked = sum(float(leg["stake"]) for leg in legs)
    cur = conn.execute(
        """INSERT INTO placed_bets
               (placed_at, opportunity_id, sport_key, event_id, home, away, market, line,
                legs_json, total_staked, status, notes)
           VALUES (datetime('now'), ?,?,?,?,?,?,?,?,?, 'pending', ?)""",
        (opportunity_id, sport_key, event_id, home, away, market, line,
         json.dumps(legs), total_staked, notes),
    )
    return cur.lastrowid


def list_placed_bets(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM placed_bets ORDER BY placed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["legs"] = json.loads(d.pop("legs_json"))
        out.append(d)
    return out


def settle_placed_bet(
    conn: sqlite3.Connection, bet_id: int, total_returned: float, notes: str | None = None
) -> dict:
    """Marca una apuesta como liquidada y calcula el beneficio real
    (`total_returned - total_staked`). Devuelve la fila actualizada."""
    row = conn.execute("SELECT * FROM placed_bets WHERE id = ?", (bet_id,)).fetchone()
    if row is None:
        raise ValueError(f"No existe la apuesta con id {bet_id}")

    profit = total_returned - row["total_staked"]
    final_notes = notes if notes is not None else row["notes"]
    conn.execute(
        "UPDATE placed_bets SET status = 'settled', total_returned = ?, profit = ?, notes = ? WHERE id = ?",
        (total_returned, profit, final_notes, bet_id),
    )
    d = dict(row)
    d.update(status="settled", total_returned=total_returned, profit=profit, notes=final_notes)
    d["legs"] = json.loads(d.pop("legs_json"))
    return d


def bets_summary(conn: sqlite3.Connection) -> dict:
    """Beneficio REAL acumulado (solo apuestas liquidadas), para comparar con
    el beneficio matemático teórico que ya reporta `backtest_summary`."""
    total_bets = conn.execute("SELECT COUNT(*) AS c FROM placed_bets").fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM placed_bets WHERE status = 'pending'"
    ).fetchone()["c"]
    settled = conn.execute(
        """SELECT COUNT(*) AS c, COALESCE(SUM(total_staked), 0) AS staked,
                  COALESCE(SUM(total_returned), 0) AS returned, COALESCE(SUM(profit), 0) AS profit
           FROM placed_bets WHERE status = 'settled'"""
    ).fetchone()
    staked = settled["staked"]
    roi_pct = (settled["profit"] / staked * 100.0) if staked else 0.0
    return {
        "total_bets": total_bets,
        "pending": pending,
        "settled": settled["c"],
        "total_staked_settled": staked,
        "total_returned_settled": settled["returned"],
        "total_profit_settled": settled["profit"],
        "roi_pct_settled": roi_pct,
    }


def backtest_summary(conn: sqlite3.Connection) -> dict:
    """Estadísticas simples para la Fase 13 (backtest)."""
    total = conn.execute("SELECT COUNT(*) AS c FROM opportunities").fetchone()["c"]
    by_verdict = conn.execute(
        "SELECT verdict, COUNT(*) AS c, AVG(profit_pct) AS avg_profit FROM opportunities GROUP BY verdict"
    ).fetchall()
    by_sport = conn.execute(
        """SELECT sport_key, COUNT(*) AS c, AVG(profit_pct) AS avg_profit, MAX(profit_pct) AS max_profit
           FROM opportunities GROUP BY sport_key ORDER BY c DESC"""
    ).fetchall()
    return {
        "total_opportunities": total,
        "by_verdict": [dict(r) for r in by_verdict],
        "by_sport": [dict(r) for r in by_sport],
    }
