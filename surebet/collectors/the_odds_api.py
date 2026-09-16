"""Collector para The Odds API (https://the-odds-api.com).

Comprobado por request HTTP directo en septiembre de 2026 (ver
docs/INVESTIGACION_Y_DISENO.md, Fase 3):

  - Free tier real: 500 créditos/mes (NO 500/día como afirman algunos blogs
    de terceros). coste = [nº mercados] x [nº regiones] POR LLAMADA, y esa
    única llamada devuelve TODOS los bookmakers de esa región para ese
    mercado y deporte.
  - region "eu" incluye, entre otros: pinnacle, marathonbet, betfair_ex_eu,
    unibet_fr/it/nl/se, winamax_de/fr, betclic_fr, williamhill, sport888,
    tipico_de. NO incluye bet365, Bwin, Codere España, Luckia ni Sportium.
  - bet365 SOLO existe como bookmaker "bet365_au" (región au), limitado a
    AFL/NRL, y solo en planes de pago. Para España/EU no está disponible
    por esta vía a ningún precio razonable.
"""

from __future__ import annotations

import logging

import httpx

from surebet.config import settings
from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.normalize.markets import handicap_home_perspective_line

logger = logging.getLogger(__name__)

_MARKET_FAMILY_BY_KEY = {
    "h2h": None,  # se decide dinámicamente según nº de outcomes (2 vs 3)
    "spreads": MarketFamily.HANDICAP,
    "totals": MarketFamily.TOTALS,
}


class TheOddsApiCollector:
    name = "the_odds_api"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.the_odds_api_key
        self.base_url = settings.the_odds_api_base_url
        self.last_credit_cost: int | None = None
        self.last_credits_remaining: int | None = None

    async def fetch(self) -> tuple[list[Event], list[OddQuote]]:
        if not self.api_key:
            logger.warning("THE_ODDS_API_KEY no configurada: se omite este collector")
            return [], []

        events: list[Event] = []
        quotes: list[OddQuote] = []

        cost_per_sport = len(settings.markets) * len(settings.the_odds_api_regions)

        async with httpx.AsyncClient(timeout=20) as client:
            for sport in settings.sports:
                if (
                    self.last_credits_remaining is not None
                    and self.last_credits_remaining - cost_per_sport < settings.the_odds_api_min_credits_reserve
                ):
                    logger.error(
                        "The Odds API: quedan %s créditos (reserva mínima configurada: %s). "
                        "Se detiene esta pasada para no agotar el free tier antes de fin de mes; "
                        "quedan %d deportes sin consultar (%s).",
                        self.last_credits_remaining,
                        settings.the_odds_api_min_credits_reserve,
                        len(settings.sports) - settings.sports.index(sport),
                        ", ".join(settings.sports[settings.sports.index(sport):]),
                    )
                    break

                url = f"{self.base_url}/sports/{sport}/odds"
                params = {
                    "apiKey": self.api_key,
                    "regions": ",".join(settings.the_odds_api_regions),
                    "markets": ",".join(settings.markets),
                    "oddsFormat": "decimal",
                    "dateFormat": "iso",
                }
                resp = await client.get(url, params=params)
                self.last_credits_remaining = _safe_int(resp.headers.get("x-requests-remaining"))
                self.last_credit_cost = _safe_int(resp.headers.get("x-requests-last"))
                if resp.status_code != 200:
                    logger.error("The Odds API error %s en %s: %s", resp.status_code, sport, resp.text[:300])
                    continue
                for match in resp.json():
                    ev, ev_quotes = _parse_match(sport, match)
                    events.append(ev)
                    quotes.extend(ev_quotes)

        return events, quotes


def _safe_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _parse_match(sport_key: str, match: dict) -> tuple[Event, list[OddQuote]]:
    import datetime as dt

    event_id = match["id"]
    commence_time = dt.datetime.fromisoformat(match["commence_time"].replace("Z", "+00:00"))
    home_team = match.get("home_team", "")
    away_team = match.get("away_team", "")

    event = Event(
        event_id=event_id,
        sport_key=sport_key,
        sport_group=sport_key.split("_")[0],
        league=sport_key,
        home=home_team,
        away=away_team,
        commence_time=commence_time,
        is_live=False,  # este endpoint es de pre-match/próximos; live requiere polling frecuente (ver Fase 11)
    )

    quotes: list[OddQuote] = []
    for bk in match.get("bookmakers", []):
        bookmaker = bk["key"]
        bk_last_update = None
        if bk.get("last_update"):
            bk_last_update = dt.datetime.fromisoformat(bk["last_update"].replace("Z", "+00:00"))

        for mkt in bk.get("markets", []):
            market_key_raw = mkt["key"]
            outcomes = mkt.get("outcomes", [])
            mkt_last_update = bk_last_update
            if mkt.get("last_update"):
                mkt_last_update = dt.datetime.fromisoformat(mkt["last_update"].replace("Z", "+00:00"))

            if market_key_raw == "h2h":
                family = MarketFamily.THREE_WAY if len(outcomes) == 3 else MarketFamily.MONEYLINE_2WAY
                mkey = MarketKey(
                    sport_key=sport_key,
                    event_id=event_id,
                    family=family,
                    period=Period.FULL_TIME,
                    rules=SettlementRules.STANDARD,
                    line=None,
                )
                for out in outcomes:
                    selection = _h2h_selection(out["name"], home_team, away_team)
                    if selection is None:
                        continue
                    quotes.append(
                        OddQuote(
                            bookmaker=bookmaker,
                            market=mkey,
                            selection=selection,
                            price_decimal=float(out["price"]),
                            bookmaker_last_update=mkt_last_update,
                            source="the_odds_api",
                        )
                    )

            elif market_key_raw == "spreads":
                for out in outcomes:
                    is_home = _is_home(out["name"], home_team)
                    point = float(out.get("point", 0.0))
                    home_line = handicap_home_perspective_line(is_home, point)
                    mkey = MarketKey(
                        sport_key=sport_key,
                        event_id=event_id,
                        family=MarketFamily.HANDICAP,
                        period=Period.FULL_TIME,
                        rules=SettlementRules.STANDARD,
                        line=home_line,
                    )
                    quotes.append(
                        OddQuote(
                            bookmaker=bookmaker,
                            market=mkey,
                            selection="home" if is_home else "away",
                            price_decimal=float(out["price"]),
                            bookmaker_last_update=mkt_last_update,
                            source="the_odds_api",
                        )
                    )

            elif market_key_raw == "totals":
                for out in outcomes:
                    point = float(out.get("point", 0.0))
                    mkey = MarketKey(
                        sport_key=sport_key,
                        event_id=event_id,
                        family=MarketFamily.TOTALS,
                        period=Period.FULL_TIME,
                        rules=SettlementRules.STANDARD,
                        line=point,
                    )
                    selection = out["name"].strip().lower()  # "Over" / "Under"
                    quotes.append(
                        OddQuote(
                            bookmaker=bookmaker,
                            market=mkey,
                            selection=selection,
                            price_decimal=float(out["price"]),
                            bookmaker_last_update=mkt_last_update,
                            source="the_odds_api",
                        )
                    )
            # Otros mercados (player props, outrights, periodos parciales) se ignoran
            # deliberadamente en el MVP: ver Fase 12/15 (roadmap) para su incorporación
            # progresiva una vez el matching de 2/3-way esté validado en producción.

    return event, quotes


def _is_home(name: str, home_team: str) -> bool:
    return name.strip().lower() == home_team.strip().lower()


def _h2h_selection(name: str, home_team: str, away_team: str) -> str | None:
    n = name.strip().lower()
    if n == home_team.strip().lower():
        return "home"
    if n == away_team.strip().lower():
        return "away"
    if n == "draw":
        return "draw"
    return None
