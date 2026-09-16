"""Conversión de formatos de cuota."""

from __future__ import annotations


def american_to_decimal(price: float) -> float:
    if price > 0:
        return price / 100.0 + 1.0
    return 100.0 / abs(price) + 1.0
