"""
qwen_client.py — DEPRECATED, superseded during Sprint 1 build-out.

This module originally held a standalone httpx-based Qwen client with its
own provider seam (ai_orchestrator.register_qwen_client) and its own pricing
table. While finishing Sprint 1, llm_core.py (the pre-existing "Parity
Mission" LLM layer — versioned prompt registry, provider adapters, cost
ledger) turned out to already be the platform's real integration point:
main.py wires it in at startup (`llm_core.enable_ai(...)` once any provider
key is present), and it already had adapters for Anthropic/OpenAI/Gemini.
Keeping this file's parallel client would have reproduced the exact
"two scorers not unified" duplicate-logic problem the independent audit
flagged elsewhere in the project.

What happened instead:
  - Qwen support was added directly to llm_core.py as `_call_qwen`, alongside
    its existing adapters, using the same plain-urllib style (no httpx
    dependency needed) — see llm_core._ADAPTERS["qwen"].
  - llm_core._PRICES now includes qwen-turbo/plus/max rates (replacing this
    file's _PRICE_PER_1K table).
  - llm_core.active_provider() checks QWEN_API_KEY first, so Qwen becomes
    the active provider automatically once that env var is set — no
    separate setup_from_env() call is needed; main.py's existing
    `llm_core.enable_ai(SessionLocal)` startup call covers it.
  - ai_orchestrator.py now calls llm_core.call_llm(..., model_override=...)
    directly rather than through a registered client function — see
    ai_orchestrator.MODEL_FOR_TIER (an alias onto
    llm_core.QWEN_MODEL_FOR_TIER) and ai_orchestrator.run_agent().

This file is kept only so any external references don't hard-fail on
import; it exposes no working client. New code should not import it.
"""
from __future__ import annotations


def build_client(*_args, **_kwargs):
    raise RuntimeError(
        "qwen_client.build_client() is deprecated. Qwen is now a provider "
        "inside llm_core.py (llm_core._call_qwen / llm_core.call_llm). "
        "Agents should call abm_platform.services.ai_orchestrator.run_agent() "
        "instead of building a client directly."
    )


def setup_from_env() -> bool:
    """No-op — kept for backward compatibility with any old call sites.
    Qwen activation now happens automatically via llm_core.active_provider()
    (checked at startup by main.py's existing llm_core.enable_ai() call)
    whenever QWEN_API_KEY is set. Returns False always, since this function
    no longer registers anything itself."""
    return False
