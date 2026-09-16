"""Collector para la API "guest" pública de Pinnacle.

Comprobado directamente en septiembre 2026 (ver docs/INVESTIGACION_Y_DISENO.md,
Fase 2): `guest.api.arcadia.pinnacle.com/0.1/...` responde JSON sin API key,
sin cabeceras de autenticación y sin cuota de peticiones documentada. Es el
mismo endpoint que usa pinnacle.com en el navegador para cargar su propia web
(XHR interno), no un scraping de HTML.

IMPORTANTE (riesgo legal/ToS, ver Fase 2 y docs): Pinnacle no publica una
política pública que autorice explícitamente este uso automatizado por
terceros. Es una zona gris tolerada de facto por la comunidad de apuestas
deportivas desde hace años, pero no una API "oficial" ni soportada. Está aquí
porque el usuario pidió expresamente NO evadir CAPTCHAs/anti-bot/auth: este
endpoint no tiene ninguno de esos controles, se limita a servir JSON público,
pero se recomienda uso estrictamente personal, con frecuencia moderada, y
dejar de usarlo si Pinnacle empieza a devolver errores/bloqueos.

Pinnacle es UN bookmaker (no un agregador): por sí solo nunca genera un
arbitraje. Su valor aquí es servir de "pata sharp" gratuita e ilimitada para
cruzar contra los bookmakers que sí trae The Odds API con nuestro presupuesto
de créditos limitado.
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx

from surebet.config import settings
from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.normalize.markets import handicap_home_perspective_line
from surebet.oddsconv import american_to_decimal

logger = logging.getLogger(__name__)

# Deporte Pinnacle -> sport_group interno + sport_key "sintético" usado en MarketKey.
# Los ids se comprobaron contra /0.1/sports en septiembre 2026.
DEFAULT_SPORTS = {
    29: ("soccer", "pinnacle_soccer"),
    33: ("tennis", "pinnacle_tennis"),
    4: ("basketball", "pinnacle_basketball"),
    19: ("hockey", "pinnacle_hockey"),
    3: ("baseball", "pinnacle_baseball"),
    15: ("americanfootball", "pinnacle_football"),
    22: ("mma", "pinnacle_mma"),
    34: ("volleyball", "pinnacle_volleyball"),
}

_TYPE_TO_FAMILY = {
    "moneyline": None,  # 2-way o 3-way según nº de precios; se decide al vuelo
    "spread": MarketFamily.HANDICAP,
    "total": MarketFamily.TOTALS,
}


class PinnacleGuestCollector:
    name = "pinnacle_guest"

    def __init__(self, sport_ids: dict[int, tuple[str, str]] | None = None):
        self.sport_ids = sport_ids or DEFAULT_SPORTS
        self.base_url = settings.pinnacle_base_url

    async def fetch(self) -> tuple[list[Event], list[OddQuote]]:
        if not settings.pinnacle_enabled:
            return [], []

        all_events: list[Event] = []
        all_quotes: list[OddQuote] = []

        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as client:
            for sport_id, (sport_group, sport_key) in self.sport_ids.items():
                try:
                    matchups = await _get(client, f"{self.base_url}/sports/{sport_id}/matchups")
                    markets = await _get(client, f"{self.base_url}/sports/{sport_id}/markets/straight")
                except httpx.HTTPError as exc:
                    logger.warning("Pinnacle: fallo consultando sport %s: %s", sport_id, exc)
                    continue

                matchup_by_id = {m["id"]: m for m in matchups if m.get("type") == "matchup"}
                events, quotes = _parse_sport(sport_group, sport_key, matchup_by_id, markets)
                all_events.extend(events)
                all_quotes.extend(quotes)

        return all_events, all_quotes


async def _get(client: httpx.AsyncClient, url: str) -> list[dict]:
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()


def _parse_sport(
    sport_group: str,
    sport_key: str,
    matchup_by_id: dict[int, dict],
    markets: list[dict],
) -> tuple[list[Event], list[OddQuote]]:
    events: dict[int, Event] = {}
    quotes: list[OddQuote] = []
    now = dt.datetime.now(dt.timezone.utc)

    for mkt in markets:
        # MVP: solo periodo 0 (partido/juego completo). Periodos parciales
        # (mitades, sets, cuartos...) se dejan para una fase posterior del
        # roadmap una vez el matching principal esté validado (Fase 15).
        if mkt.get("period") != 0:
            continue
        if mkt.get("status") not in (None, "open"):
            continue

        matchup_id = mkt.get("matchupId")
        matchup = matchup_by_id.get(matchup_id)
        if matchup is None:
            continue

        raw_type = mkt.get("type")
        prices = mkt.get("prices", [])
        # Solo soportamos precios con "designation" explícita (home/away/over/under).
        # Los que solo traen participantId (frecuente en tenis/e-sports sin home/away
        # definido por Pinnacle) requerirían cruzar con `participants` del matchup;
        # se omiten en el MVP para no arriesgar una asignación incorrecta.
        if not all("designation" in p for p in prices):
            continue

        event = events.get(matchup_id)
        if event is None:
            event = _build_event(sport_group, sport_key, matchup)
            if event is None:
                continue
            events[matchup_id] = event

        if raw_type == "moneyline":
            family = MarketFamily.THREE_WAY if len(prices) == 3 else MarketFamily.MONEYLINE_2WAY
            mkey = MarketKey(
                sport_key=sport_key,
                event_id=str(matchup_id),
                family=family,
                period=Period.FULL_TIME,
                rules=SettlementRules.STANDARD,
                line=None,
            )
            for p in prices:
                selection = _moneyline_selection(p["designation"])
                if selection is None:
                    continue
                quotes.append(_make_quote(mkey, p, selection, now))

        elif raw_type == "spread":
            for p in prices:
                is_home = p["designation"] == "home"
                point = float(p.get("points", 0.0))
                home_line = handicap_home_perspective_line(is_home, point)
                mkey = MarketKey(
                    sport_key=sport_key,
                    event_id=str(matchup_id),
                    family=MarketFamily.HANDICAP,
                    period=Period.FULL_TIME,
                    rules=SettlementRules.STANDARD,
                    line=home_line,
                )
                quotes.append(_make_quote(mkey, p, "home" if is_home else "away", now))

        elif raw_type == "total":
            for p in prices:
                point = float(p.get("points", 0.0))
                mkey = MarketKey(
                    sport_key=sport_key,
                    event_id=str(matchup_id),
                    family=MarketFamily.TOTALS,
                    period=Period.FULL_TIME,
                    rules=SettlementRules.STANDARD,
                    line=point,
                )
                quotes.append(_make_quote(mkey, p, p["designation"], now))

    return list(events.values()), quotes


def _make_quote(mkey: MarketKey, price_obj: dict, selection: str, received_at) -> OddQuote:
    return OddQuote(
        bookmaker="pinnacle",
        market=mkey,
        selection=selection,
        price_decimal=american_to_decimal(float(price_obj["price"])),
        received_at=received_at,
        bookmaker_last_update=None,  # Pinnacle no expone timestamp de última actualización por precio
        source="pinnacle_guest",
    )


def _moneyline_selection(designation: str) -> str | None:
    if designation in ("home", "away", "draw"):
        return designation
    return None


def _build_event(sport_group: str, sport_key: str, matchup: dict) -> Event | None:
    participants = matchup.get("participants", [])
    home = next((p["name"] for p in participants if p.get("alignment") == "home"), None)
    away = next((p["name"] for p in participants if p.get("alignment") == "away"), None)
    if home is None or away is None:
        return None
    start = dt.datetime.fromisoformat(matchup["startTime"].replace("Z", "+00:00"))
    league = matchup.get("league", {})
    return Event(
        event_id=str(matchup["id"]),
        sport_key=sport_key,
        sport_group=sport_group,
        league=league.get("name", sport_group),
        home=home,
        away=away,
        commence_time=start,
        is_live=bool(matchup.get("isLive", False)),
    )
