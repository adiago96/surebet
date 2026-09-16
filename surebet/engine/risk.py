"""Validación de riesgo (Fases 6 y 8) y la distinción fundamental del sistema:

    MATHEMATICAL ARBITRAGE   -> 1/odd_1 + ... + 1/odd_n < 1 con los datos recibidos.
    EXECUTABLE ARBITRAGE     -> además: cuotas frescas, mercados/reglas equivalentes
                                 (garantizado por la capa de normalización antes de
                                 llegar aquí), sin señales de datos sospechosos, y
                                 dentro de límites de stake razonables.

Ninguna oportunidad se marca nunca como "ganancia garantizada". Ver
`docs/INVESTIGACION_Y_DISENO.md` Fase 6/8/16 para la justificación.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from surebet.config import settings
from surebet.engine.arbitrage import ArbitrageOpportunity
from surebet.engine.stakes import StakePlan


class DataFreshness(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"


class Verdict(str, Enum):
    NOT_ARBITRAGE = "NOT_ARBITRAGE"
    STALE_DO_NOT_BET = "STALE_DO_NOT_BET"
    SUSPICIOUS_ARB = "SUSPICIOUS_ARB"
    # Matemáticamente sum(1/odd_i) < 1 con las cuotas crudas, PERO al redondear
    # los stakes a los incrementos mínimos reales el beneficio se vuelve <= 0.
    # Nunca debe alertarse ni mostrarse como una oportunidad válida.
    ROUNDING_UNPROFITABLE = "ROUNDING_UNPROFITABLE"
    VALID_ARB = "VALID_ARB"  # matemático + fresco + no sospechoso + sobrevive al redondeo real.


@dataclass
class RiskAssessment:
    verdict: Verdict
    freshness: DataFreshness
    max_age_seconds: float
    execution_risk_score: int  # 0 (bajo riesgo) - 100 (altísimo riesgo)
    reasons: list[str]
    is_mathematical_arbitrage: bool
    is_executable_candidate: bool  # nunca "garantizado": solo "candidato razonable"


def classify_freshness(max_age_seconds: float, is_live: bool) -> DataFreshness:
    fresh_th = settings.live_fresh_seconds if is_live else settings.prematch_fresh_seconds
    stale_th = settings.live_stale_seconds if is_live else settings.prematch_stale_seconds
    if max_age_seconds <= fresh_th:
        return DataFreshness.FRESH
    if max_age_seconds <= stale_th:
        return DataFreshness.AGING
    return DataFreshness.STALE


def execution_risk_score(
    opportunity: ArbitrageOpportunity,
    freshness: DataFreshness,
    stake_plan: StakePlan | None,
    is_live: bool,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if freshness == DataFreshness.AGING:
        score += 25
        reasons.append("Cuotas envejeciendo (AGING): pueden haber cambiado ya en origen")
    elif freshness == DataFreshness.STALE:
        score += 60
        reasons.append("Cuotas obsoletas (STALE)")

    if is_live:
        score += 20
        reasons.append("Mercado en vivo: mucha mayor probabilidad de suspensión/cambio de cuota")

    if opportunity.num_bookmakers_involved < 2:
        score += 40
        reasons.append("Todas las patas en la misma casa: no es un arbitraje real")

    line = opportunity.market.line
    if line is not None and (line * 4) % 1 != 0:
        # línea "rara" no múltiplo de 0.25: fuente de datos poco fiable
        score += 15
        reasons.append("Línea de hándicap/total no estándar")
    elif line is not None and (line * 2) % 1 != 0:
        # cuarto de línea (.25 / .75): liquidación por split, menor liquidez típica
        score += 8
        reasons.append("Línea de cuarto (.25/.75): confirmar liquidez y límites antes de apostar")

    if opportunity.profit_pct > settings.suspicious_profit_pct:
        score += 35
        reasons.append(
            f"Margen de beneficio ({opportunity.profit_pct:.1f}%) anormalmente alto para "
            "ser un simple desfase de mercado"
        )

    if stake_plan is not None:
        if not stake_plan.arbitrage_survives_rounding:
            score += 50
            reasons.append("El redondeo a incrementos mínimos destruye el margen de beneficio")
        if stake_plan.limited_by_max_stake:
            score += 20
            reasons.append("El stake óptimo supera el límite máximo conocido de alguna casa")

    return min(score, 100), reasons


def assess(
    opportunity: ArbitrageOpportunity,
    is_live: bool,
    stake_plan: StakePlan | None = None,
) -> RiskAssessment:
    is_math_arb = opportunity.is_mathematical_arbitrage
    freshness = classify_freshness(opportunity.max_leg_age_seconds, is_live)
    score, reasons = execution_risk_score(opportunity, freshness, stake_plan, is_live)

    if not is_math_arb:
        verdict = Verdict.NOT_ARBITRAGE
    elif freshness == DataFreshness.STALE:
        verdict = Verdict.STALE_DO_NOT_BET
    elif opportunity.profit_pct > settings.suspicious_profit_pct:
        verdict = Verdict.SUSPICIOUS_ARB
    elif stake_plan is not None and not stake_plan.arbitrage_survives_rounding:
        verdict = Verdict.ROUNDING_UNPROFITABLE
    else:
        verdict = Verdict.VALID_ARB

    is_executable_candidate = (
        verdict == Verdict.VALID_ARB
        and score < 50
        and (stake_plan is None or stake_plan.arbitrage_survives_rounding)
    )

    return RiskAssessment(
        verdict=verdict,
        freshness=freshness,
        max_age_seconds=opportunity.max_leg_age_seconds,
        execution_risk_score=score,
        reasons=reasons,
        is_mathematical_arbitrage=is_math_arb,
        is_executable_candidate=is_executable_candidate,
    )
