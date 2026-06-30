"""
Abstract base class for orchestrators.

Every orchestrator is a pure "protected-in, protected-out" pipeline:
  Retrieve (KB / RAG / KG) → LLM

Gate 1 (protect) and Gate 2 (unprotect) are the caller's responsibility.
Orchestrators receive already-protected input and return tokenized output.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class PipelineResult:
    """Unified result from any orchestrator."""
    answer: str
    gate1: Optional[Any] = None
    gate2: Optional[Any] = None
    rag_context: List[Dict] = field(default_factory=list)
    kg_context: Dict = field(default_factory=dict)
    raw_llm_response: str = ""
    blocked: bool = False
    block_reason: str = ""
    metadata: Dict = field(default_factory=dict)
    trace: List[Dict] = field(default_factory=list)


def build_turn_llm_trace(
    step: str,
    *,
    user_message: str,
    response_preview: str,
    conversation_history: Optional[List[Dict]] = None,
    duration_ms: int = 0,
    **extra: Any,
) -> Dict[str, Any]:
    """Trace payload scoped to the current user message (not full chat history)."""
    prior = conversation_history or []
    return {
        "step": step,
        "duration_ms": duration_ms,
        "turn_messages": [{"role": "user", "content": user_message}],
        "prior_turns": len(prior),
        "response_preview": response_preview,
        **extra,
    }


class BaseOrchestrator(ABC):
    """All orchestrators implement this interface."""

    @abstractmethod
    def run(
        self,
        user_message: str,
        *,
        customer_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        protected_context: Optional[str] = None,
    ) -> PipelineResult:
        """
        Execute the retrieve + LLM pipeline.

        The caller is responsible for Gate 1 (input protection) and
        Gate 2 (output unprotection). The orchestrator only handles
        retrieval and LLM invocation on already-protected data.

        Args:
            user_message: Already-protected user query (tokenized PII)
            customer_id: Optional customer context for KB retrieval
            conversation_history: Previous messages
            protected_context: Optional pre-loaded protected KB/RAG/KG context

        Returns:
            PipelineResult with raw (still-tokenized) answer
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable orchestrator name."""
        ...
