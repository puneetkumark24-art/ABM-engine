"""
abm_platform.services.agents — Tier A/B/C/D agent implementations
(transformation/AI_Intelligence_Layer_Architecture.md section 5).

Every agent in this package is a thin wrapper around
abm_platform.services.ai_orchestrator.run_agent() — no agent module calls a
model provider directly. Agents that had a pre-existing deterministic
implementation (e.g. signal_intel.classify_partnership,
signal_decay.compute_decay) keep that implementation as the default/fallback
and treat the AI agent as an ADDITIVE enrichment layer, per the
transformation program's KEEP·IMPROVE·EXTEND·HARDEN philosophy
(transformation/CONSTITUTION.md) — the deterministic path never disappears,
so the platform keeps working with zero API cost when no provider key is
configured (ai_orchestrator/llm_core's honest dry-run) or when the AI call
fails validation.
"""
