"""
Critical-path acceptance tests, ported from Build Artifact 3.
Run: pytest tests/test_scoring.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scoring import (
    effective_opportunity, EffectiveOpportunityInputs, can_promote_to_hot, tier_for_score
)


def test_t_score_1_worked_example():
    """T-SCORE-1: Dynamic 90, ICS 80, EVALUATING, UNFUNDED = 46.8 (+/- 0.1)"""
    inp = EffectiveOpportunityInputs(
        dynamic_score=90, ics=80, stage="EVALUATING", budget_status="UNFUNDED",
    )
    result = effective_opportunity(inp)
    assert abs(result - 46.8) < 0.1, f"expected 46.8, got {result}"


def test_t_score_2_ics_gating():
    """T-SCORE-2: Account with ICS 35 cannot reach TIER_1/HOT even with Dynamic 95 (GOV-ICS-001)."""
    assert can_promote_to_hot(35) is False
    assert can_promote_to_hot(40) is True
    tier = tier_for_score(total_score=95, ics=35)
    assert tier != "HOT", f"ICS 35 should block HOT promotion, got tier={tier}"


def test_stage_closed_zeroes_opportunity():
    inp = EffectiveOpportunityInputs(dynamic_score=90, ics=90, stage="CLOSED", budget_status="ALLOCATED")
    assert effective_opportunity(inp) == 0.0


def test_allocated_budget_beats_unfunded():
    base = dict(dynamic_score=80, ics=80, stage="EXPLORING")
    unfunded = effective_opportunity(EffectiveOpportunityInputs(**base, budget_status="UNFUNDED"))
    allocated = effective_opportunity(EffectiveOpportunityInputs(**base, budget_status="ALLOCATED"))
    assert allocated > unfunded


if __name__ == "__main__":
    test_t_score_1_worked_example()
    test_t_score_2_ics_gating()
    test_stage_closed_zeroes_opportunity()
    test_allocated_budget_beats_unfunded()
    print("All scoring tests passed.")
