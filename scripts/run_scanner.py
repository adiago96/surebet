"""Lanza el bucle continuo de escaneo de arbitrajes.

Uso:
    python scripts/run_scanner.py           # bucle infinito (respeta POLL_INTERVAL_SECONDS)
    python scripts/run_scanner.py --once     # una sola pasada (útil para probar)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surebet.scanner import run_forever, run_scan_once  # noqa: E402


async def _main() -> None:
    if "--once" in sys.argv:
        import logging

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        summary = await run_scan_once()
        print(f"\n{len(summary)} oportunidades matemáticas encontradas:\n")
        for s in summary:
            print(s)
    else:
        await run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
