"""Normalización de eventos entre distintas fuentes.

Cada fuente (The Odds API, Pinnacle...) tiene sus propios IDs internos para
"Real Madrid vs Elche". Para poder cruzar cuotas de dos fuentes distintas
sobre el MISMO partido necesitamos una clave canónica basada en:

    (deporte, nombres de equipo normalizados, hora de inicio redondeada)

Esto es una heurística, no una garantía. Documentado en
docs/INVESTIGACION_Y_DISENO.md (Fase 5): un falso emparejamiento de eventos
es una fuente de falsos arbitrajes tan grave como un falso emparejamiento de
mercados, así que el margen de tolerancia se mantiene deliberadamente
estrecho (10 minutos, similitud de nombre >= 0.82).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

_SUFFIXES = (
    " cf",
    " fc",
    " cd",
    " ud",
    " sd",
    " afc",
    " sc",
    " ac",
    " bc",
    " athletic club",
)

KICKOFF_TOLERANCE = timedelta(minutes=10)
NAME_SIMILARITY_THRESHOLD = 0.82


def normalize_team_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.lower().strip()
    name = re.sub(r"[.\-']", " ", name)
    name = re.sub(r"\s+", " ", name)
    for suf in _SUFFIXES:
        if name.endswith(suf):
            name = name[: -len(suf)].strip()
    return name


def name_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, normalize_team_name(a), normalize_team_name(b)).ratio()


def same_fixture(
    home_a: str,
    away_a: str,
    start_a: datetime,
    home_b: str,
    away_b: str,
    start_b: datetime,
) -> bool:
    """Heurística conservadora: incluso invirtiendo local/visitante (deportes con
    sede neutral, o discrepancias de convención entre fuentes)."""
    if abs((start_a - start_b)) > KICKOFF_TOLERANCE:
        return False

    direct = (
        name_similarity(home_a, home_b) >= NAME_SIMILARITY_THRESHOLD
        and name_similarity(away_a, away_b) >= NAME_SIMILARITY_THRESHOLD
    )
    swapped = (
        name_similarity(home_a, away_b) >= NAME_SIMILARITY_THRESHOLD
        and name_similarity(away_a, home_b) >= NAME_SIMILARITY_THRESHOLD
    )
    return direct or swapped
