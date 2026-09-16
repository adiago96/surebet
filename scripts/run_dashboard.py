"""Lanza el dashboard web local. Uso: python scripts/run_dashboard.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from surebet.config import settings  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("surebet.api.main:app", host=settings.dashboard_host, port=settings.dashboard_port, reload=False)
