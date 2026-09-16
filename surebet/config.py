"""Configuración centralizada, leída de variables de entorno (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Resuelto de forma absoluta porque el scanner puede lanzarse desde el
# Programador de tareas de Windows, cuyo directorio de trabajo por defecto
# NO es la carpeta del proyecto (por eso `.env` o `data/surebet.db` como
# rutas relativas al "directorio actual" fallarían silenciosamente ahí).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    val = os.getenv(name, default)
    return [x.strip() for x in val.split(",") if x.strip()]


@dataclass
class Settings:
    # --- The Odds API (https://the-odds-api.com) ---
    # Free tier real (comprobado en septiembre 2026): 500 créditos/mes.
    # coste = nº mercados x nº regiones POR LLAMADA (no por bookmaker).
    the_odds_api_key: str = field(default_factory=lambda: os.getenv("THE_ODDS_API_KEY", ""))
    the_odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    the_odds_api_regions: list[str] = field(default_factory=lambda: _list("THE_ODDS_API_REGIONS", "eu"))
    the_odds_api_monthly_credit_budget: int = field(
        default_factory=lambda: _int("THE_ODDS_API_MONTHLY_CREDIT_BUDGET", 480)
    )
    # Freno de seguridad: si el crédito restante que reporta la API (cabecera
    # x-requests-remaining) bajara de este umbral, el collector deja de pedir
    # más deportes en esa misma pasada. Es un backstop ante un mal cálculo de
    # SPORTS/MARKETS/POLL_INTERVAL_SECONDS, no el mecanismo principal de
    # control de gasto (ese es simplemente pedir menos/menos a menudo).
    the_odds_api_min_credits_reserve: int = field(
        default_factory=lambda: _int("THE_ODDS_API_MIN_CREDITS_RESERVE", 5)
    )

    # --- Pinnacle guest API (pública, sin key, ver docs/INVESTIGACION_Y_DISENO.md) ---
    pinnacle_enabled: bool = field(default_factory=lambda: _bool("PINNACLE_ENABLED", True))
    pinnacle_base_url: str = "https://guest.api.arcadia.pinnacle.com/0.1"

    # --- Deportes a vigilar (claves estilo The Odds API) ---
    sports: list[str] = field(
        default_factory=lambda: _list(
            "SPORTS",
            "soccer_spain_la_liga,soccer_uefa_champs_league,tennis_atp_us_open,basketball_nba",
        )
    )
    markets: list[str] = field(default_factory=lambda: _list("MARKETS", "h2h,spreads,totals"))

    # --- Bankroll / stakes ---
    bankroll_eur: float = field(default_factory=lambda: _float("BANKROLL_EUR", 100.0))
    default_min_stake_increment: float = field(
        default_factory=lambda: _float("DEFAULT_MIN_STAKE_INCREMENT", 1.0)
    )
    default_max_stake_per_bookmaker: float = field(
        default_factory=lambda: _float("DEFAULT_MAX_STAKE_PER_BOOKMAKER", 500.0)
    )

    # --- Umbrales de arbitraje / riesgo ---
    min_profit_pct_to_alert: float = field(
        default_factory=lambda: _float("MIN_PROFIT_PCT_TO_ALERT", 0.5)
    )
    suspicious_profit_pct: float = field(
        default_factory=lambda: _float("SUSPICIOUS_PROFIT_PCT", 12.0)
    )
    prematch_fresh_seconds: float = field(
        default_factory=lambda: _float("PREMATCH_FRESH_SECONDS", 180.0)
    )
    prematch_stale_seconds: float = field(
        default_factory=lambda: _float("PREMATCH_STALE_SECONDS", 900.0)
    )
    live_fresh_seconds: float = field(default_factory=lambda: _float("LIVE_FRESH_SECONDS", 5.0))
    live_stale_seconds: float = field(default_factory=lambda: _float("LIVE_STALE_SECONDS", 20.0))

    # --- Scanner loop ---
    poll_interval_seconds: int = field(
        default_factory=lambda: _int("POLL_INTERVAL_SECONDS", 1800)
    )

    # --- Telegram ---
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # --- Storage ---
    # Cuántos días de snapshots de cuotas crudas (tabla odds_snapshots) se
    # conservan antes de purgarse automáticamente. Las oportunidades
    # detectadas (tabla opportunities, mucho más pequeña) no se purgan nunca.
    snapshot_retention_days: int = field(
        default_factory=lambda: _int("SNAPSHOT_RETENTION_DAYS", 3)
    )
    # Se resuelve siempre respecto a PROJECT_ROOT (no al directorio de trabajo
    # actual) por el mismo motivo que `.env` arriba.
    sqlite_path: str = field(
        default_factory=lambda: str(PROJECT_ROOT / os.getenv("SQLITE_PATH", "data/surebet.db"))
    )

    # --- Dashboard ---
    dashboard_host: str = field(default_factory=lambda: os.getenv("DASHBOARD_HOST", "127.0.0.1"))
    dashboard_port: int = field(default_factory=lambda: _int("DASHBOARD_PORT", 8000))


settings = Settings()
