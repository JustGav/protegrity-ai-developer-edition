"""
Direct orchestrator — simplest pipeline (protected-in, protected-out).

Pipeline: context → LLM (no framework overhead).

Gate 1 and Gate 2 are handled by the caller.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional

from orchestrators.base import BaseOrchestrator, PipelineResult, build_turn_llm_trace
from llm_providers.factory import get_llm_provider

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful banking assistant for SecureBank. "
    "Be concise, professional, and accurate. "
    "IMPORTANT: Preserve all PII tags like [PERSON]value[/PERSON] exactly as they appear."
)


class DirectOrchestrator(BaseOrchestrator):

    @property
    def name(self) -> str:
        return "Direct"

    def run(
        self,
        user_message: str,
        *,
        customer_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        protected_context: Optional[str] = None,
    ) -> PipelineResult:
        system = SYSTEM_PROMPT
        if protected_context:
            system += f"\n\nCustomer Data:\n{protected_context}"

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in conversation_history or []:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": user_message})

        provider_fn = get_llm_provider()
        raw = provider_fn(messages)

        return PipelineResult(
            answer=raw,
            raw_llm_response=raw,
            metadata={"orchestrator": self.name},
            trace=[
                build_turn_llm_trace(
                    "Direct — LLM",
                    user_message=user_message,
                    response_preview=raw[:500],
                    conversation_history=conversation_history,
                )
            ],
        )
