"""Modelos de datos centrales del sistema.

Estos modelos son deliberadamente explícitos (en vez de genéricos) porque la
fuente #1 de "falsos arbitrajes" en este tipo de sistemas es comparar dos
mercados que PARECEN el mismo resultado pero se liquidan con reglas distintas.
Por eso `MarketKey` obliga a fijar deporte, periodo y reglas de liquidación
además del propio mercado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Period(str, Enum):
    """Periodo del evento al que aplica el mercado.

    Dos cuotas SOLO pueden combinarse en un arbitraje si su `Period` coincide
    exactamente. "Partido completo incluyendo prórroga" y "tiempo reglamentario"
    NO son el mismo periodo aunque en el 90% de los partidos coincidan.
    """

    FULL_TIME = "full_time"  # 90 min / tiempo reglamentario (fútbol), sin prórroga
    FULL_MATCH_OT = "full_match_incl_ot"  # incluye prórroga (y a veces penaltis según deporte)
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"
    FIRST_SET = "first_set"
    FIRST_QUARTER = "first_quarter"
    PERIOD_1 = "period_1"
    PERIOD_2 = "period_2"
    PERIOD_3 = "period_3"
    MATCH = "match"  # tenis/MMA: partido completo (best-of-N), walkover incluido según reglas


class SettlementRules(str, Enum):
    """Reglas especiales de liquidación que deben coincidir para poder combinar dos cuotas."""

    STANDARD = "standard"
    # Tenis: si hay retirada/walkover, algunas casas anulan (void) y otras pagan según
    # el resultado parcial. Si dos casas difieren aquí, el "arbitraje" puede convertirse
    # en una posición perdedora o en un void unilateral.
    TENNIS_RETIREMENT_VOID = "tennis_retirement_void"
    TENNIS_RETIREMENT_ACTION = "tennis_retirement_settled_on_completed_sets"
    # Fútbol: partido suspendido/abandonado. "Abandoned = void" vs "settled si se
    # completaron X minutos" son reglas distintas.
    SOCCER_ABANDONED_VOID = "soccer_abandoned_void"
    SOCCER_ABANDONED_SETTLED_IF_PLAYED = "soccer_abandoned_settled_if_played"
    # Baloncesto: hándicap/total que incluye o excluye prórroga.
    BASKETBALL_INCLUDES_OT = "basketball_includes_ot"
    BASKETBALL_EXCLUDES_OT = "basketball_excludes_ot"


class MarketFamily(str, Enum):
    MONEYLINE_2WAY = "moneyline_2way"  # tenis, baloncesto, MLB, NHL sin empate posible
    THREE_WAY = "three_way"  # 1X2 fútbol
    HANDICAP = "handicap"  # spread / Asian handicap (2 lados, línea simétrica)
    TOTALS = "totals"  # over/under
    TEAM_TOTALS = "team_totals"
    OUTRIGHT = "outright"  # no arbitrable de forma trivial (N corredores, mercado abierto)
    PLAYER_PROP = "player_prop"


@dataclass(frozen=True)
class MarketKey:
    """Identifica de forma única e inequívoca "el mismo mercado" entre dos bookmakers.

    Dos `OddQuote` solo se consideran combinables si sus `MarketKey.group_key()`
    (todo menos la selección) coinciden exactamente.
    """

    sport_key: str  # p.ej. "soccer_spain_la_liga", clave estilo The Odds API
    event_id: str  # id normalizado del evento (ver normalize/events.py)
    family: MarketFamily
    period: Period
    rules: SettlementRules
    line: Optional[float] = None  # p.ej. +1.5 / -1.5 (handicap) o 2.5 (total)

    def group_key(self) -> tuple:
        return (self.sport_key, self.event_id, self.family, self.period, self.rules, self.line)


@dataclass(frozen=True)
class OddQuote:
    """Una cuota concreta: una selección, en una casa, en un momento dado."""

    bookmaker: str
    market: MarketKey
    selection: str  # "home", "away", "draw", "over", "under", nombre de equipo/jugador
    price_decimal: float
    received_at: datetime = field(default_factory=utcnow)
    bookmaker_last_update: Optional[datetime] = None  # si la fuente lo reporta
    source: str = "unknown"
    min_stake: float = 0.0
    max_stake: Optional[float] = None  # None = desconocido/sin límite reportado

    @property
    def age_seconds(self) -> float:
        ref = self.bookmaker_last_update or self.received_at
        return max(0.0, (utcnow() - ref).total_seconds())


@dataclass(frozen=True)
class Event:
    event_id: str
    sport_key: str
    sport_group: str  # "soccer", "tennis", "basketball", ...
    league: str
    home: str
    away: str
    commence_time: datetime
    is_live: bool = False
