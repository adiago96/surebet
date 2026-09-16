# Surebet — Detección de arbitraje deportivo (coste 0 €)

Sistema de detección de arbitraje deportivo (surebets) usando fuentes 100% gratuitas: [The Odds API](https://the-odds-api.com/) (free tier) y la API pública de Pinnacle. Distingue siempre entre **arbitraje matemático** (los números cuadran) y **arbitraje ejecutable** (candidato razonable para apostar de verdad), y nunca promete "ganancia garantizada".

La investigación completa (qué fuentes gratuitas existen realmente en sept. 2026, qué bookmakers cubren, por qué, y las decisiones de arquitectura) está en [`docs/INVESTIGACION_Y_DISENO.md`](docs/INVESTIGACION_Y_DISENO.md). Léelo antes de configurar el sistema: explica, con datos comprobados, por qué **bet365, Winamax España, Bwin, Codere, Luckia y Sportium no están disponibles** en ninguna fuente gratuita.

## Instalación rápida

```
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Consigue una API key gratuita en <https://the-odds-api.com/> y ponla en `.env` (`THE_ODDS_API_KEY`). Opcionalmente configura Telegram (ver `.env.example`).

## Uso

```
.venv\Scripts\python scripts\run_scanner.py --once     # una pasada
.venv\Scripts\python scripts\run_scanner.py              # bucle continuo
.venv\Scripts\python scripts\run_dashboard.py             # dashboard en http://127.0.0.1:8000
.venv\Scripts\python -m pytest                              # tests
```

## Estructura

Ver la sección 14 de [`docs/INVESTIGACION_Y_DISENO.md`](docs/INVESTIGACION_Y_DISENO.md) para el árbol completo y qué hace cada módulo.

## Advertencia

Ninguna alerta de este sistema es una garantía de beneficio. Las cuotas cambian, los mercados se suspenden, las casas pueden rechazar o limitar apuestas, y el redondeo de stakes puede destruir un margen pequeño. Verifica siempre la cuota vigente en cada casa antes de apostar.
