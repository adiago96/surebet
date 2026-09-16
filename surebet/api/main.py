"""Dashboard web (Fase 10). FastAPI + una única página HTML con JS vanilla
que consulta `/api/opportunities`. Sin frameworks de frontend: mantenerlo
simple es parte del requisito de coste 0 y de no sobre-ingenierizar.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from surebet.storage.db import backtest_summary, get_connection, init_db, recent_opportunities

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
