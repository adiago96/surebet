"""Capa de normalización de mercados (Fase 5 / Fase 12).

Convención OBLIGATORIA que deben respetar todos los collectors al construir
un `MarketKey` con `family=HANDICAP`:

    `line` siempre se expresa en perspectiva del equipo/participante "home"
    (o, si no hay local/visitante, del primer participante devuelto por la
    fuente). Así:

        Real Madrid -1.5   -> selection="home", line=-1.5
        Elche      +1.5   -> selection="away", line=-1.5   (¡MISMO line!)

    porque "Elche +1.5" es matemáticamente "Real Madrid -1.5" visto desde el
    otro lado. Si dos casas usan esta misma convención, agrupan bajo el
    mismo `MarketKey.group_key()` automáticamente y sabemos que sus reglas de
    liquidación cubren el mismo evento exhaustivamente.

Esto es lo que impide el falso arbitraje del enunciado: "Real Madrid gana por
al menos 2 goles" NO se traduce jamás a esta representación (no es un
hándicap de la casa, es una pregunta con reglas de liquidación propias), así
que nunca podrá agruparse por accidente con "Elche +1.5 Asian Handicap".
"""

from __future__ import annotations

from collections import defaultdict

from surebet.models import MarketFamily, MarketKey, OddQuote

# Selecciones que DEBEN estar presentes (y ser las ÚNICAS) para que el grupo
# cubra el 100% de los resultados posibles. `None` = familia no soportada
# todavía para arbitraje automático (ver docs, Fase 12: outrights y player
# props no tienen un conjunto de resultados cerrado y verificable de forma
# genérica).
_REQUIRED_SELECTIONS: dict[MarketFamily, frozenset[str] | None] = {
    MarketFamily.MONEYLINE_2WAY: frozenset({"home", "away"}),
    MarketFamily.THREE_WAY: frozenset({"home", "draw", "away"}),
    MarketFamily.HANDICAP: frozenset({"home", "away"}),
    MarketFamily.TOTALS: frozenset({"over", "under"}),
    MarketFamily.TEAM_TOTALS: frozenset({"over", "under"}),
    MarketFamily.OUTRIGHT: None,
    MarketFamily.PLAYER_PROP: None,
}


def handicap_home_perspective_line(is_home_selection: bool, point: float) -> float:
    """Convierte el `point` crudo de una fuente a la convención home-perspective."""
    return point if is_home_selection else -point


def is_market_supported(family: MarketFamily) -> bool:
    return _REQUIRED_SELECTIONS.get(family) is not None


def required_selections(family: MarketFamily) -> frozenset[str] | None:
    """Selecciones que un grupo debe tener (y solo esas) para ser evaluable.

    Expuesto para que la UI de "Captura rápida" (`surebet/api/main.py`) sepa
    qué campos pedir al usuario sin duplicar `_REQUIRED_SELECTIONS`.
    """
    return _REQUIRED_SELECTIONS.get(family)


def group_by_market(quotes: list[OddQuote]) -> dict[tuple, list[OddQuote]]:
    groups: dict[tuple, list[OddQuote]] = defaultdict(list)
    for q in quotes:
        groups[q.market.group_key()].append(q)
    return dict(groups)


def is_exhaustive(market: MarketKey, quotes_in_group: list[OddQuote]) -> bool:
    """¿Las selecciones presentes cubren TODOS los resultados posibles de este mercado?

    No basta con "hay al menos 2 selecciones distintas": tienen que ser
    EXACTAMENTE el conjunto requerido por la familia de mercado. Si falta una
    (p.ej. no hay cuota de "draw" en un 1X2) no se puede construir arbitraje
    ni ejecutable ni matemático con ese grupo.
    """
    required = _REQUIRED_SELECTIONS.get(market.family)
    if required is None:
        return False
    present = {q.selection for q in quotes_in_group}
    return required.issubset(present)


def best_price_per_selection(quotes_in_group: list[OddQuote]) -> dict[str, OddQuote]:
    """Mejor cuota (mayor precio decimal) para cada selección, cruzando bookmakers.

    Si hay empate de precio, se conserva la cuota más reciente (menor `age_seconds`).
    """
    best: dict[str, OddQuote] = {}
    for q in quotes_in_group:
        current = best.get(q.selection)
        if current is None:
            best[q.selection] = q
            continue
        if q.price_decimal > current.price_decimal:
            best[q.selection] = q
        elif q.price_decimal == current.price_decimal and q.age_seconds < current.age_seconds:
            best[q.selection] = q
    return best
