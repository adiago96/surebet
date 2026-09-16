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
from surebet.collectors.manual import ManualCollector
from surebet.collectors.pinnacle_guest import PinnacleGuestCollector
from surebet.collectors.the_odds_api import TheOddsApiCollector
from surebet.config import settings
from surebet.engine.arbitrage import evaluate_market
from surebet.engine.risk import Verdict, assess
from surebet.engine.stakes import compute_stake_plan
from surebet.models import Event, OddQuote
from surebet.normalize.cross_source import unify
from surebet.normalize.markets import best_price_per_selection, group_by_market, is_exhaustive
from surebet.storage.db import (
    already_alerted,
    get_connection,
    init_db,
    mark_alerted,
    prune_finished_events,
    prune_old_snapshots,
    save_opportunity,
    save_snapshot,
)

logger = logging.getLogger(__name__)


def default_collectors() -> list[Collector]:
    collectors: list[Collector] = []
    if settings.the_odds_api_key:
        collectors.append(TheOddsApiCollector())
    else:
        logger.warning("THE_ODDS_API_KEY vacío: ejecutando solo con Pinnacle (cobertura limitada)")
    if settings.pinnacle_enabled:
        collectors.append(PinnacleGuestCollector())
    # Siempre activo: no depende de ninguna API key ni cuota, y es la única
    # fuente con cobertura de bet365/Winamax ES/William Hill/Bwin/Unibet/
    # Codere/Sportium (ver docs/INVESTIGACION_Y_DISENO.md, "Captura rápida").
    collectors.append(ManualCollector())
    return collectors


async def process_market_group(conn, event: Event, group_quotes: list[OddQuote]) -> dict | None:
    """Evalúa un único grupo de cuotas (mismo `MarketKey.group_key()`):
    guarda snapshot, comprueba exhaustividad, calcula arbitraje/riesgo/stakes,
    persiste la oportunidad y alerta por Telegram si corresponde.

    Extraído de `run_scan_once` para poder reutilizarlo también desde el
    endpoint `POST /api/manual/quote`, que necesita el mismo cálculo pero de
    forma inmediata (sin esperar al siguiente ciclo del scanner) justo
    después de que el usuario teclee una cuota nueva.

    Devuelve el resumen de la oportunidad, o `None` si el grupo no llega a
    ser un arbitraje matemático evaluable (mercado incompleto, todas las
    cuotas de la misma casa, o no hay margen).
    """
    market = group_quotes[0].market
    save_snapshot(conn, event, group_quotes)

    if not is_exhaustive(market, group_quotes):
        return None  # el mercado no cubre el 100% de resultados: no se puede evaluar

    best = best_price_per_selection(group_quotes)
    if len({q.bookmaker for q in best.values()}) < 2:
        return None  # todas las mejores cuotas son de la misma casa: no hay arbitraje real

    opportunity = evaluate_market(market, best)
    if not opportunity.is_mathematical_arbitrage:
        return None

    stake_plan = compute_stake_plan(
        opportunity,
        bankroll=settings.bankroll_eur,
        default_increment=settings.default_min_stake_increment,
        default_max_stake=settings.default_max_stake_per_bookmaker,
    )
    risk = assess(opportunity, is_live=event.is_live, stake_plan=stake_plan)

    save_opportunity(conn, event, opportunity, risk, stake_plan)

    already_sent = already_alerted(conn, market)

    entry = {
        "event": f"{event.home} vs {event.away}",
        "sport": event.sport_group,
        "market": market.family.value,
        "line": market.line,
        "profit_pct": opportunity.profit_pct,
        "verdict": risk.verdict.value,
        "execution_risk": risk.execution_risk_score,
        "max_age_seconds": risk.max_age_seconds,
        "already_alerted": already_sent,
    }

    should_alert = (
        risk.verdict in (Verdict.VALID_ARB, Verdict.SUSPICIOUS_ARB)
        and opportunity.profit_pct >= settings.min_profit_pct_to_alert
    )
    if should_alert and not already_sent:
        # Una alerta por mercado (evento+familia+periodo+reglas+línea), no
        # una por pasada: mientras el partido no empiece, la cuota puede
        # moverse un poco sin que eso justifique repetir el mismo aviso en
        # Telegram cada vez que corre el scanner.
        text = format_alert(event, opportunity, risk, stake_plan)
        await send_telegram_message(text)
        mark_alerted(conn, event, market, opportunity.profit_pct)
    elif should_alert and already_sent:
        # Seguimos registrando el profit_pct más reciente aunque no
        # reenviemos el mensaje, para que el dashboard/backtest vea cómo
        # evolucionó la oportunidad.
        mark_alerted(conn, event, market, opportunity.profit_pct)

    return entry


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

            entry = await process_market_group(conn, event, group_quotes)
            if entry is not None:
                summary.append(entry)

        snaps_pruned, alerts_pruned = prune_finished_events(conn)
        old_snaps_pruned = prune_old_snapshots(conn)
        total_pruned = snaps_pruned + old_snaps_pruned
        if total_pruned or alerts_pruned:
            logger.info(
                "Purgados %d snapshots (partido ya jugado o > %d días) y %d registros de alerta de partidos terminados",
                total_pruned,
                settings.snapshot_retention_days,
                alerts_pruned,
            )

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
