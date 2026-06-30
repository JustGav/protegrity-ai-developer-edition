"""
LangGraph orchestrator — StateGraph pipeline (protected-in, protected-out).

Pipeline: retrieve → llm

Gate 1 and Gate 2 are handled by the caller.
"""

from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from orchestrators.base import BaseOrchestrator, PipelineResult, build_turn_llm_trace
from common.protegrity_gates import register_context_tokens
from llm_providers.factory import get_llm_provider
from config.orchestration_config import KB_ENABLED

log = logging.getLogger(__name__)

KB_DIR = Path(__file__).resolve().parent.parent / "banking_data" / "knowledge_base"

SYSTEM_PROMPT = (
    "You are a helpful banking assistant for SecureBank. "
    "Be concise, professional, and accurate. "
    "IMPORTANT: Preserve all PII tags like [PERSON]value[/PERSON] exactly as they appear."
)


class PipelineState(TypedDict, total=False):
    user_message: str
    customer_id: str
    conversation_history: list
    protected_context: str
    # pipeline artefacts
    kb_context: str
    llm_messages: list
    llm_response: str
    answer: str
    retrieve_ms: int
    llm_ms: int


def _node_retrieve(state: PipelineState) -> dict:
    t0 = time.time()
    context = state.get("protected_context", "")
    if not context and KB_ENABLED:
        cid = state.get("customer_id", "")
        kb_file = KB_DIR / f"{cid}.txt"
        if kb_file.exists():
            context = kb_file.read_text().strip()
    if context:
        register_context_tokens(context)
    return {
        "kb_context": context,
        "retrieve_ms": round((time.time() - t0) * 1000),
    }


def _node_llm(state: PipelineState) -> dict:
    t0 = time.time()
    provider_fn = get_llm_provider()
    context = state.get("kb_context", "")
    system = SYSTEM_PROMPT
    if context:
        system += f"\n\nCustomer Data:\n{context}"

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for m in state.get("conversation_history") or []:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": state["user_message"]})

    raw = provider_fn(messages)
    return {
        "llm_response": raw,
        "answer": raw,
        "llm_messages": messages,
        "llm_ms": round((time.time() - t0) * 1000),
    }


class LangGraphOrchestrator(BaseOrchestrator):

    @property
    def name(self) -> str:
        return "LangGraph"

    def run(
        self,
        user_message: str,
        *,
        customer_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        protected_context: Optional[str] = None,
    ) -> PipelineResult:
        graph = StateGraph(PipelineState)
        graph.add_node("retrieve", _node_retrieve)
        graph.add_node("llm", _node_llm)

        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "llm")
        graph.add_edge("llm", END)

        compiled = graph.compile()

        initial: PipelineState = {
            "user_message": user_message,
            "customer_id": customer_id or "",
            "conversation_history": conversation_history or [],
            "protected_context": protected_context or "",
        }

        final_state = compiled.invoke(initial)

        kb_context = final_state.get("kb_context", "")
        orch_trace = [
            {
                "step": "LangGraph — Retrieve",
                "duration_ms": final_state.get("retrieve_ms", 0),
                "kb_chars": len(kb_context),
                "kb_preview": kb_context[:400],
            },
            build_turn_llm_trace(
                "LangGraph — LLM",
                user_message=initial["user_message"],
                response_preview=final_state.get("llm_response", "")[:500],
                conversation_history=initial.get("conversation_history"),
                duration_ms=final_state.get("llm_ms", 0),
            ),
        ]

        return PipelineResult(
            answer=final_state.get("answer", ""),
            raw_llm_response=final_state.get("llm_response", ""),
            metadata={"orchestrator": self.name},
            trace=orch_trace,
        )
