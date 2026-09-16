"""Orquestador principal: collectors -> normalización -> motor de arbitraje ->
validación de riesgo -> stakes -> almacenamiento -> alertas.

Este módulo es deliberadamente "tonto": no contiene lógica de negocio propia,
solo conecta las piezas ya testeadas de forma aislada en `engine/` y
`normalize/`. Así el pipeline entero se puede razonar mirando este único
archivo de arriba a abajo.
"""

from __future__ import annotations

import asyncio
import logging

from surebet.alerts.telegram import format_alert, send_telegram_message
from surebet.collectors.base import Collector
from surebet.collectors.pinnacle_guest import PinnacleGuestCollector
from surebet.collectors.the_odds_api import TheOddsApiCollector
from surebet.config import settings
from surebet.engine.arbitrage import evaluate_market
from surebet.engine.risk import Verdict, assess
from surebet.engine.stakes import compute_stake_plan
from surebet.models import Event
from surebet.normalize.cross_source import unify
from surebet.normalize.markets import best_price_per_selection, group_by_market, is_exhaustive
from surebet.storage.db import get_connection, init_db, prune_old_snapshots, save_opportunity, save_snapshot

logger = logging.getLogger(__name__)


def default_collectors() -> list[Collector]:
    collectors: list[Collector] = []
    if settings.the_odds_api_key:
        collectors.append(TheOddsApiCollector())
    else:
        logger.warning("THE_ODDS_API_KEY vacío: ejecutando solo con Pinnacle (cobertura limitada)")
    if settings.pinnacle_enabled:
        collectors.append(PinnacleGuestCollector())
    return collectors


async def run_scan_once(collectors: list[Collector] | None = None) -> list[dict]:
    """Ejecuta una pasada completa y devuelve un resumen de oportunidades detectadas."""
    collectors = collectors if collectors is not None else default_collectors()

    results = await asyncio.gather(*(c.fetch() for c in collectors))
    for c, (events, quotes) in zip(collectors, results):
        logger.info("%s: %d eventos, %d cuotas", c.name, len(events), len(quotes))

    events, quotes = unify(list(results))
    events_by_id: dict[str, Event] = {e.event_id: e for e in events}

    groups = group_by_market(quotes)
    summary: list[dict] = []

    init_db()
    with get_connection() as conn:
        for group_key, group_quotes in groups.items():
            market = group_quotes[0].market
            event = events_by_id.get(market.event_id)
            if event is None:
                continue

            save_snapshot(conn, event, group_quotes)

            if not is_exhaustive(market, group_quotes):
                continue  # el mercado no cubre el 100% de resultados: no se puede evaluar

            best = best_price_per_selection(group_quotes)
            if len({q.bookmaker for q in best.values()}) < 2:
                continue  # todas las mejores cuotas son de la misma casa: no hay arbitraje real

            opportunity = evaluate_market(market, best)
            if not opportunity.is_mathematical_arbitrage:
                continue

            stake_plan = compute_stake_plan(
                opportunity,
                bankroll=settings.bankroll_eur,
                default_increment=settings.default_min_stake_increment,
                default_max_stake=settings.default_max_stake_per_bookmaker,
            )
            risk = assess(opportunity, is_live=event.is_live, stake_plan=stake_plan)

            save_opportunity(conn, event, opportunity, risk, stake_plan)

            entry = {
                "event": f"{event.home} vs {event.away}",
                "sport": event.sport_group,
                "market": market.family.value,
                "line": market.line,
                "profit_pct": opportunity.profit_pct,
                "verdict": risk.verdict.value,
                "execution_risk": risk.execution_risk_score,
                "max_age_seconds": risk.max_age_seconds,
            }
            summary.append(entry)

            if risk.verdict in (Verdict.VALID_ARB, Verdict.SUSPICIOUS_ARB) and (
                opportunity.profit_pct >= settings.min_profit_pct_to_alert
            ):
                text = format_alert(event, opportunity, risk, stake_plan)
                await send_telegram_message(text)

        pruned = prune_old_snapshots(conn)
        if pruned:
            logger.info("Purgados %d snapshots antiguos (> %d días)", pruned, settings.snapshot_retention_days)

        conn.commit()

    return summary


async def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    while True:
        try:
            summary = await run_scan_once()
            logger.info("Escaneo completo: %d oportunidades matemáticas encontradas", len(summary))
        except Exception:
            logger.exception("Error en el ciclo de escaneo")
        await asyncio.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_forever())
