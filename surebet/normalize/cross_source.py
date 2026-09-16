"""Unifica eventos de varias fuentes (The Odds API, Pinnacle guest...) bajo un
mismo `event_id`/`sport_key` canónico cuando son, con alta probabilidad, el
mismo partido real (Fase 5 + Fase 12: "no asumir complementariedad, comprobarla").

Sin este paso, dos fuentes que ven el mismo Real Madrid-Elche con IDs internos
distintos nunca se agruparían en `normalize.markets.group_by_market`, y
perderíamos la mitad de las oportunidades de arbitraje cruzado entre fuentes.
"""

from __future__ import annotations

from dataclasses import replace

from surebet.models import Event, MarketKey, OddQuote
from surebet.normalize.events import same_fixture


def unify(
    collector_results: list[tuple[list[Event], list[OddQuote]]],
) -> tuple[list[Event], list[OddQuote]]:
    canonical_events: list[Event] = []
    # (índice de fuente, event_id original) -> (event_id canónico, sport_key canónico)
    remap: dict[tuple[int, str], tuple[str, str]] = {}

    for source_idx, (events, _) in enumerate(collector_results):
        for ev in events:
            match = _find_match(ev, canonical_events)
            if match is not None:
                remap[(source_idx, ev.event_id)] = (match.event_id, match.sport_key)
            else:
                canonical_events.append(ev)
                remap[(source_idx, ev.event_id)] = (ev.event_id, ev.sport_key)

    unified_quotes: list[OddQuote] = []
    for source_idx, (_, quotes) in enumerate(collector_results):
        for q in quotes:
            canon_id, canon_sport = remap.get(
                (source_idx, q.market.event_id), (q.market.event_id, q.market.sport_key)
            )
            new_market = replace(q.market, event_id=canon_id, sport_key=canon_sport)
            unified_quotes.append(replace(q, market=new_market))

    return canonical_events, unified_quotes


def _find_match(ev: Event, canonical: list[Event]) -> Event | None:
    for other in canonical:
        if other.sport_group != ev.sport_group:
            continue
        if same_fixture(ev.home, ev.away, ev.commence_time, other.home, other.away, other.commence_time):
            return other
    return None
