"""
Orchestrator package — supports Direct, LangGraph, CrewAI, LlamaIndex.

Usage (library):
    from orchestrators import ask
    result = ask("What is my balance?", customer_id="CUST-100000")

Usage (CLI):
    ORCHESTRATOR=langgraph LLM_PROVIDER=ollama python -m orchestrators
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrators.base import PipelineResult

__all__ = ["get_orchestrator", "ask"]

log = logging.getLogger(__name__)


def get_orchestrator():
    """Lazy wrapper — avoids import errors when submodules aren't on path."""
    from orchestrators.factory import get_orchestrator as _get
    return _get()


def ask(
    user_message: str,
    *,
    customer_id: str | None = None,
    conversation_history: list | None = None,
    protected_context: str | None = None,
) -> "PipelineResult":
    """
    Run user_message through the configured orchestrator pipeline.

    The caller is responsible for Gate 1 (protection) and Gate 2 (unprotection).
    user_message should already be protected (tokenized PII).

    Returns PipelineResult with raw (still-tokenized) answer.
    """
    orch = get_orchestrator()
    log.info("Orchestrator: %s | message: %s", orch.name, user_message[:80])
    return orch.run(
        user_message,
        customer_id=customer_id,
        conversation_history=conversation_history,
        protected_context=protected_context,
    )
