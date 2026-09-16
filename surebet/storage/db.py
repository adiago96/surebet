"""Persistencia en SQLite: snapshots de cuotas (para backtest, Fase 13) y
oportunidades detectadas (para el dashboard y el histórico de alertas).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from surebet.config import settings
from surebet.engine.arbitrage import ArbitrageOpportunity
from surebet.engine.risk import RiskAssessment
from surebet.engine.stakes import StakePlan
from surebet.models import Event, OddQuote

SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    source TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    home TEXT,
    away TEXT,
    family TEXT NOT NULL,
    period TEXT NOT NULL,
    rules TEXT NOT NULL,
    line REAL,
    selection TEXT NOT NULL,
    price_decimal REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_event ON odds_snapshots (sport_key, event_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_time ON odds_snapshots (received_at);

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
CREATE INDEX IF NOT EXISTS idx_opps_time ON opportunities (detected_at);
CREATE INDEX IF NOT EXISTS idx_opps_sport ON opportunities (sport_key);
"""


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
        conn.executescript(SCHEMA)
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
            family, period, rules, line, selection, price_decimal)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
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
    cur = conn.execute(
        f"DELETE FROM odds_snapshots WHERE received_at < datetime('now', '-{int(days)} days')"
    )
    return cur.rowcount


def recent_opportunities(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities ORDER BY detected_at DESC LIMIT ?", (limit,)
    ).fetchall()


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
