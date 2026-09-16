"""Collector para cuotas introducidas a mano desde el dashboard ("Captura
rápida", ver `surebet/api/main.py`).

El usuario navega él mismo a la web/app de bet365, Winamax ES, William
Hill, Bwin, Unibet, Codere, Sportium... (casas sin fuente automática legítima
y gratuita, ver docs/INVESTIGACION_Y_DISENO.md) y teclea la cuota que ve.
No hay scraping, lectura de pantalla ni automatización de ningún tipo: es la
misma acción que apuntar el número en una hoja de cálculo, solo que entra
directamente en el mismo `MarketKey`/`OddQuote` que usan los collectors
automáticos, así que el motor de arbitraje, riesgo, stakes, alertas de
Telegram y backtest la tratan exactamente igual.

Este collector solo se encarga de que esas entradas también participen en el
ciclo normal del scanner (`run_forever`), además de en la evaluación
instantánea que ya hace el endpoint `POST /api/manual/quote` al guardarlas.
"""

from __future__ import annotations

from surebet.collectors.base import Collector
from surebet.models import Event, OddQuote
from surebet.storage.db import get_connection, init_db, list_manual_entries


class ManualCollector(Collector):
    name = "manual"

    async def fetch(self) -> tuple[list[Event], list[OddQuote]]:
        init_db()
        with get_connection() as conn:
            entries = list_manual_entries(conn, active_only=True)

        events: dict[str, Event] = {}
        quotes: list[OddQuote] = []
        for event, quote in entries:
            events[event.event_id] = event
            quotes.append(quote)
        return list(events.values()), quotes
