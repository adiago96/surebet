"""Dashboard web (Fase 10). FastAPI + una única página HTML con JS vanilla
que consulta `/api/opportunities`. Sin frameworks de frontend: mantenerlo
simple es parte del requisito de coste 0 y de no sobre-ingenierizar.

También expone la "Captura rápida" (`/api/manual/*`): el usuario navega él
mismo a bet365/Winamax ES/William Hill/Bwin/Unibet/Codere/Sportium y teclea
la cuota que ve, sin ningún tipo de automatización ni scraping (ver
docs/INVESTIGACION_Y_DISENO.md). Es la vía legal para cubrir las casas que
ninguna fuente automática gratuita ni de pago verificable ofrece.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules
from surebet.normalize.markets import best_price_per_selection, is_market_supported, required_selections
from surebet.scanner import process_market_group
from surebet.storage.db import (
    backtest_summary,
    bets_summary,
    get_connection,
    init_db,
    list_placed_bets,
    list_recent_events,
    market_state,
    recent_opportunities,
    save_placed_bet,
    settle_placed_bet,
    upsert_manual_entry,
)

app = FastAPI(title="Surebet Dashboard")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/api/opportunities")
def api_opportunities(limit: int = 300) -> list[dict]:
    with get_connection() as conn:
        rows = recent_opportunities(conn, limit=limit)
    out = []
    for r in rows:
        d = dict(r)
        d["legs"] = json.loads(d.pop("legs_json"))
        d["reasons"] = json.loads(d.pop("reasons_json"))
        out.append(d)
    return out


@app.get("/api/backtest")
def api_backtest() -> dict:
    with get_connection() as conn:
        return backtest_summary(conn)


# --- Captura rápida (entrada manual, ver surebet/collectors/manual.py) ---


class ManualQuoteIn(BaseModel):
    bookmaker: str
    sport_key: str
    event_id: str
    home: str
    away: str
    sport_group: str
    league: str
    commence_time: datetime
    family: str  # valor de MarketFamily, p.ej. "three_way"
    period: str = Period.FULL_TIME.value
    rules: str = SettlementRules.STANDARD.value
    line: float | None = None
    selection: str
    price_decimal: float
    min_stake: float = 0.0
    max_stake: float | None = None


@app.get("/api/manual/events")
def api_manual_events(limit: int = 50) -> list[dict]:
    """Eventos próximos ya conocidos (por fuentes automáticas o por entradas
    manuales previas), para rellenar el desplegable del formulario sin que
    haya que teclear el partido entero desde cero."""
    with get_connection() as conn:
        return list_recent_events(conn, limit=limit)


@app.get("/api/manual/market-fields")
def api_manual_market_fields(family: str) -> dict:
    """Qué selecciones exige esta familia de mercado (p.ej. home/draw/away
    para un 1X2), para que el formulario muestre exactamente esos campos."""
    try:
        fam = MarketFamily(family)
    except ValueError:
        raise HTTPException(400, f"Familia de mercado desconocida: {family}")
    selections = required_selections(fam)
    if selections is None:
        raise HTTPException(
            400,
            f"'{family}' no tiene un conjunto de resultados cerrado y verificable "
            "(outright/player prop): no se puede evaluar arbitraje automáticamente.",
        )
    return {"family": fam.value, "selections": sorted(selections)}


@app.get("/api/manual/market-state")
def api_manual_market_state(
    sport_key: str,
    event_id: str,
    family: str,
    period: str = Period.FULL_TIME.value,
    rules: str = SettlementRules.STANDARD.value,
    line: float | None = None,
) -> dict:
    """Mejor cuota ya conocida por selección para este mercado exacto
    (combinando fuentes automáticas y entradas manuales previas), para que el
    formulario muestre en vivo "esto es lo que ya hay" mientras el usuario
    rellena la cuota que ha visto en su casa."""
    try:
        market = MarketKey(
            sport_key=sport_key, event_id=event_id, family=MarketFamily(family),
            period=Period(period), rules=SettlementRules(rules), line=line,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    with get_connection() as conn:
        quotes = market_state(conn, market)
    best = best_price_per_selection(quotes)
    return {
        sel: {"bookmaker": q.bookmaker, "price_decimal": q.price_decimal, "source": q.source}
        for sel, q in best.items()
    }


@app.post("/api/manual/quote")
async def api_manual_quote(body: ManualQuoteIn) -> dict:
    try:
        family = MarketFamily(body.family)
        period = Period(body.period)
        rules = SettlementRules(body.rules)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if not is_market_supported(family):
        raise HTTPException(
            400,
            f"'{family.value}' no tiene un conjunto de resultados cerrado y verificable: "
            "no se puede evaluar arbitraje automáticamente para esta familia todavía.",
        )
    selections = required_selections(family) or frozenset()
    if body.selection not in selections:
        raise HTTPException(
            400, f"Selección '{body.selection}' no válida para '{family.value}' (válidas: {sorted(selections)})"
        )

    market = MarketKey(
        sport_key=body.sport_key, event_id=body.event_id, family=family,
        period=period, rules=rules, line=body.line,
    )
    event = Event(
        event_id=body.event_id, sport_key=body.sport_key, sport_group=body.sport_group,
        league=body.league, home=body.home, away=body.away, commence_time=body.commence_time,
    )
    quote = OddQuote(
        bookmaker=body.bookmaker, market=market, selection=body.selection,
        price_decimal=body.price_decimal, source="manual",
        min_stake=body.min_stake, max_stake=body.max_stake,
    )

    with get_connection() as conn:
        init_db()
        upsert_manual_entry(conn, event, quote)

        # Cuotas ya conocidas de otras casas/fuentes para este mismo mercado,
        # para poder evaluar arbitraje al instante sin esperar al siguiente
        # ciclo del scanner (que por defecto corre cada POLL_INTERVAL_SECONDS).
        known = market_state(conn, market)
        known = [q for q in known if not (q.bookmaker == quote.bookmaker and q.selection == quote.selection)]
        known.append(quote)

        result = await process_market_group(conn, event, known)
        conn.commit()

    if result is not None:
        return result
    return {
        "event": f"{event.home} vs {event.away}",
        "market": family.value,
        "line": body.line,
        "verdict": "NOT_ARBITRAGE",
        "message": (
            "Cuota guardada. Aún no hay arbitraje: o faltan cuotas de otras "
            "selecciones/casas para este mercado, o con las cuotas actuales no cuadra."
        ),
    }


# --- Mis apuestas (libro de apuestas realmente colocadas) ---


class BetLegIn(BaseModel):
    bookmaker: str
    selection: str
    odds: float
    stake: float


class PlacedBetIn(BaseModel):
    opportunity_id: int | None = None
    sport_key: str | None = None
    event_id: str | None = None
    home: str | None = None
    away: str | None = None
    market: str | None = None
    line: float | None = None
    legs: list[BetLegIn]
    notes: str | None = None


class SettleBetIn(BaseModel):
    total_returned: float
    notes: str | None = None


@app.get("/api/bets")
def api_list_bets(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        return list_placed_bets(conn, limit=limit)


@app.get("/api/bets/summary")
def api_bets_summary() -> dict:
    with get_connection() as conn:
        return bets_summary(conn)


@app.post("/api/bets")
def api_create_bet(body: PlacedBetIn) -> dict:
    if not body.legs:
        raise HTTPException(400, "Una apuesta necesita al menos una pierna (casa + selección + cuota + stake)")
    with get_connection() as conn:
        bet_id = save_placed_bet(
            conn,
            legs=[leg.model_dump() for leg in body.legs],
            opportunity_id=body.opportunity_id,
            sport_key=body.sport_key,
            event_id=body.event_id,
            home=body.home,
            away=body.away,
            market=body.market,
            line=body.line,
            notes=body.notes,
        )
        conn.commit()
    return {"id": bet_id}


@app.post("/api/bets/{bet_id}/settle")
def api_settle_bet(bet_id: int, body: SettleBetIn) -> dict:
    with get_connection() as conn:
        try:
            updated = settle_placed_bet(conn, bet_id, body.total_returned, body.notes)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        conn.commit()
    return updated
