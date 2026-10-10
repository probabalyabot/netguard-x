"""Risk scoring.  Transparent weighted sum; the weights are inputs, not constants."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RiskWeights(BaseModel):
    """Defaults are heuristic starting points, not calibrated values.  Tune them per environment."""

    broken_flows: float = Field(20, ge=0)
    security_violations: float = Field(30, ge=0)
    new_exposures: float = Field(6, ge=0)
    routing_failures: float = Field(10, ge=0)
    criticality: float = Field(5, ge=0)


class Risk(BaseModel):
    score: float
    level: str
    breakdown: dict[str, float]
    inputs: dict[str, float]
    weights: RiskWeights


def level_for(score: float) -> str:
    if score <= 0:
        return "NONE"
    if score < 25:
        return "LOW"
    if score < 50:
        return "MEDIUM"
    if score < 75:
        return "HIGH"
    return "CRITICAL"


def calculate_risk(
    broken_flows: int,
    security_violations: int,
    new_exposures: int,
    routing_failures: int,
    criticality_excess: int,
    weights: RiskWeights,
) -> Risk:
    """score = min(100, w1*broken + w2*violations + w3*exposures + w4*routing + w5*criticality_excess)

    ``criticality_excess`` is the sum of (criticality - 1) over negatively affected flows, so an
    outage on a criticality-5 asset weighs more than one on a criticality-1 asset.
    """
    inputs = {
        "broken_flows": broken_flows,
        "security_violations": security_violations,
        "new_exposures": new_exposures,
        "routing_failures": routing_failures,
        "criticality_excess": criticality_excess,
    }
    breakdown = {
        "broken_flows": weights.broken_flows * broken_flows,
        "security_violations": weights.security_violations * security_violations,
        "new_exposures": weights.new_exposures * new_exposures,
        "routing_failures": weights.routing_failures * routing_failures,
        "criticality": weights.criticality * criticality_excess,
    }
    raw = sum(breakdown.values())
    score = round(min(100.0, raw), 1)
    return Risk(score=score, level=level_for(score), breakdown=breakdown, inputs=inputs, weights=weights)
