"""
scoring.py — Bible scoring spine (Build Artifact 1), implemented as code.

    Effective Opportunity = Dynamic_Score x (ICS/100) x Stage_Bonus x
                             Budget_Modifier x Entrenchment_Modifier x
                             Risk_Modifier x Window_Multiplier

    Decision Score = Effective Opportunity x (Strategic_Readiness/100) / Capital_Cost

All modifier values are loaded from modifiers.json (the Rule_Registry seed),
not hardcoded, per RULEREG-RECORD-001 — override the JSON to retune without
touching this module.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass

_MODIFIERS = json.loads((Path(__file__).parent / "modifiers.json").read_text())


def entrenchment_modifier(entrenchment_score: float) -> float:
    """General formula: (100 - score) / 100. FORTRESS (80) -> 0.20 per the lookup table."""
    return round(max(0.0, (100 - entrenchment_score) / 100), 4)


def risk_modifier(risk_exposure: float) -> float:
    """max(0.2, 1 - Risk_Exposure/500)"""
    floor = _MODIFIERS["risk_modifier_floor"]
    divisor = _MODIFIERS["risk_exposure_divisor"]
    return max(floor, round(1 - risk_exposure / divisor, 4))


def dynamic_score(signal_strength: float, regulatory_pressure: float,
                   persona_reachability: float, relationship_warmth: float,
                   regulatory_mandatory: bool = False) -> float:
    w = _MODIFIERS["dynamic_score_weights"]
    reg_weight = w["regulatory_pressure_if_mandatory"] if regulatory_mandatory else w["regulatory_pressure"]
    score = (signal_strength * w["signal_strength"] + regulatory_pressure * reg_weight +
             persona_reachability * w["persona_reachability"] + relationship_warmth * w["relationship_warmth"])
    return round(min(100.0, max(0.0, score)), 4)


@dataclass
class EffectiveOpportunityInputs:
    dynamic_score: float
    ics: float               # Intelligence Confidence Score, 0-100
    stage: str                # key into stage_bonus
    budget_status: str        # key into budget_modifier
    entrenchment_score: float = 0.0   # 0 = no incumbent -> modifier 1.0
    risk_exposure: float = 0.0        # 0 = no risk -> modifier 1.0
    window_state: str | None = None   # None = multiplier not engaged (treated as 1.0)


def effective_opportunity(inp: EffectiveOpportunityInputs) -> float:
    stage_bonus = _MODIFIERS["stage_bonus"][inp.stage]
    budget_mod = _MODIFIERS["budget_modifier"][inp.budget_status]
    entrench_mod = entrenchment_modifier(inp.entrenchment_score) if inp.entrenchment_score else 1.0
    risk_mod = risk_modifier(inp.risk_exposure) if inp.risk_exposure else 1.0
    window_mod = _MODIFIERS["window_multiplier"][inp.window_state] if inp.window_state else 1.0

    result = (inp.dynamic_score * (inp.ics / 100) * stage_bonus * budget_mod *
              entrench_mod * risk_mod * window_mod)
    return round(result, 4)


def decision_score(eff_opportunity: float, strategic_readiness: float, capital_cost: float) -> float:
    if capital_cost <= 0:
        raise ValueError("capital_cost must be > 0")
    return round(eff_opportunity * (strategic_readiness / 100) / capital_cost, 4)


def can_promote_to_hot(ics: float) -> bool:
    """GOV-ICS-001: ICS >= 40 required to promote to HOT/TIER_1, regardless of Dynamic Score."""
    return ics >= _MODIFIERS["ics_action_floor"]


def needs_reasoning_expansion(ics: float) -> bool:
    """HUMANREVIEW-003: ICS < 60 triggers mandatory reasoning-chain expansion."""
    return ics < _MODIFIERS["ics_review_scrutiny_gate"]


def tier_for_score(total_score: float, ics: float) -> str:
    t = _MODIFIERS["tier_thresholds"]
    if total_score >= t["HOT"] and can_promote_to_hot(ics):
        return "HOT"
    if total_score >= t["HOT"] and not can_promote_to_hot(ics):
        return "WARM"   # ICS gate blocks HOT even though raw score qualifies
    if total_score >= t["WARM"]:
        return "WARM"
    return "COLD"
