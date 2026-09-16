from __future__ import annotations

from abc import ABC, abstractmethod

from surebet.models import Event, OddQuote


class Collector(ABC):
    """Interfaz común para cualquier fuente de cuotas."""

    name: str

    @abstractmethod
    async def fetch(self) -> tuple[list[Event], list[OddQuote]]:
        """Devuelve (eventos, cuotas) obtenidos en esta pasada."""
        raise NotImplementedError
