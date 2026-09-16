"""Alertas por Telegram (Fase 9).

Usa la API HTTP de Telegram Bot directamente (sin SDK) para minimizar
dependencias. Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en `.env`
(instrucciones en README.md).
"""

from __future__ import annotations

import logging

import httpx

from surebet.config import settings
from surebet.engine.arbitrage import ArbitrageOpportunity
from surebet.engine.risk import RiskAssessment, Verdict
from surebet.engine.stakes import StakePlan
from surebet.models import Event, MarketFamily, MarketKey

logger = logging.getLogger(__name__)

_SPORT_EMOJI = {
    "soccer": "⚽",
    "tennis": "🎾",
    "basketball": "🏀",
    "baseball": "⚾",
    "hockey": "🏒",
    "americanfootball": "🏈",
    "mma": "🥊",
    "volleyball": "🏐",
}


def _sport_emoji(sport_group: str) -> str:
    return _SPORT_EMOJI.get(sport_group, "🎯")


def _selection_label(market: MarketKey, selection: str, event: Event) -> str:
    """Traduce "home"/"away"/"draw"/"over"/"under" a un texto entendible:
    el nombre real del equipo, "Empate", o "Más/Menos de X"."""
    if market.family in (MarketFamily.MONEYLINE_2WAY, MarketFamily.THREE_WAY):
        if selection == "home":
            return event.home
        if selection == "away":
            return event.away
        if selection == "draw":
            return "Empate"
    if market.family == MarketFamily.HANDICAP and market.line is not None:
        if selection == "home":
            return f"{event.home} ({market.line:+.2f})"
        if selection == "away":
            return f"{event.away} ({-market.line:+.2f})"
    if market.family in (MarketFamily.TOTALS, MarketFamily.TEAM_TOTALS) and market.line is not None:
        if selection == "over":
            return f"Más de {market.line:g}"
        if selection == "under":
            return f"Menos de {market.line:g}"
    return selection


def format_alert(
    event: Event,
    opportunity: ArbitrageOpportunity,
    risk: RiskAssessment,
    stake_plan: StakePlan | None,
) -> str:
    """Mensaje corto en español: liga, a quién apostar, en qué casa, a qué
    cuota, y qué se gana. Sin jerga técnica ni desgloses de riesgo — eso
    queda para el dashboard, no para la alerta de Telegram."""
    emoji = _sport_emoji(event.sport_group)
    lines = [
        f"{emoji} {event.league}",
        f"{event.home} vs {event.away}",
        "",
    ]

    if stake_plan:
        for leg in stake_plan.legs:
            label = _selection_label(opportunity.market, leg.selection, event)
            lines.append(
                f"Apuesta {leg.rounded_stake:.2f} € a \"{label}\" @ {leg.odd.price_decimal:.2f} "
                f"en {leg.bookmaker}"
            )
        lines.append("")
        lines.append(f"Inviertes: {stake_plan.total_stake:.2f} €")
        lines.append(f"Ganas (pase lo que pase): {stake_plan.profit_worst_case:+.2f} € ({opportunity.profit_pct:.2f}%)")
    else:
        lines.append(f"Arbitraje: {opportunity.profit_pct:+.2f}%")

    if risk.verdict != Verdict.VALID_ARB:
        lines.append("")
        lines.append(f"⚠️ {risk.verdict.value}: revisa antes de apostar")

    lines.append("")
    lines.append("⚠️ No garantizado hasta que ambas apuestas estén aceptadas")
    return "\n".join(lines)


async def send_telegram_message(text: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram no configurado (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID vacíos)")
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url, json={"chat_id": settings.telegram_chat_id, "text": text}
        )
        if resp.status_code != 200:
            logger.error("Error enviando alerta Telegram: %s", resp.text[:300])
            return False
    return True
