"""Emit realtime pipeline events from chat handlers."""
from __future__ import annotations

import logging
import time

from services.pipeline_events import new_run_id, publish_event

log = logging.getLogger(__name__)

SOURCE_BUSINESS = "business"
SOURCE_TECHNICAL = "technical"


class PipelineRunEmitter:
    def __init__(self, source_app: str, customer_id: str, user_message: str):
        self.source_app = source_app
        self.customer_id = customer_id
        self.user_message = user_message
        self.run_id = new_run_id(source_app)
        self.start()
        self._active_node = "customer"

    def start(self) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "run_start",
            {
                "customer_id": self.customer_id,
                "user_message": self.user_message,
                "node": "customer",
            },
        )

    def gate1(
        self,
        *,
        original: str,
        protected: str,
        duration_ms: int,
        accepted: bool,
        risk_score: float = 0.0,
        pii_elements: int = 0,
        elements_found: list | None = None,
        explanation: str = "",
    ) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "gate1",
            {
                "node": "gate1",
                "duration_ms": duration_ms,
                "accepted": accepted,
                "risk_score": risk_score,
                "pii_elements": pii_elements,
                "elements_found": elements_found or [],
                "explanation": explanation,
                "original": original,
                "protected": protected,
            },
        )
        self._active_node = "gate1"

    def kb_retrieval(self, payload: dict) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "kb_retrieval",
            {"node": "kb", **payload},
        )
        self._active_node = "kb"

    def rag(self, payload: dict) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "rag",
            {"node": "kb", **payload},
        )
        self._active_node = "kb"

    def knowledge_graph(self, payload: dict) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "knowledge_graph",
            {"node": "kb", **payload},
        )
        self._active_node = "kb"

    def orchestrator(self, payload: dict) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "orchestrator",
            {"node": "orchestrator", **payload},
        )
        self._active_node = "orchestrator"
        for sub in payload.get("sub_trace") or []:
            self.orchestrator_step(sub)

    def orchestrator_step(self, sub: dict) -> None:
        step_name = sub.get("step", "Orchestrator step")
        node = "llm" if "LLM" in step_name or sub.get("turn_messages") or sub.get("messages") else "orchestrator"
        turn_messages = sub.get("turn_messages")
        prior_turns = sub.get("prior_turns", 0)
        if turn_messages is None and sub.get("messages"):
            users = [m for m in sub["messages"] if m.get("role") == "user"]
            turn_messages = [users[-1]] if users else sub["messages"][-1:]
            prior_turns = max(prior_turns, max(len(sub["messages"]) - len(turn_messages) - 1, 0))

        if turn_messages or sub.get("response_preview"):
            publish_event(
                self.run_id,
                self.source_app,
                "llm_request",
                {
                    "node": "llm",
                    "turn_messages": turn_messages or [],
                    "prior_turns": prior_turns,
                    "response_preview": sub.get("response_preview", ""),
                    "duration_ms": sub.get("duration_ms", 0),
                    "step": step_name,
                },
            )
            self._active_node = "llm"
            if "LLM" in step_name:
                return

        publish_event(
            self.run_id,
            self.source_app,
            "orchestrator_step",
            {"node": node, **sub},
        )
        self._active_node = node

    def gate2(
        self,
        *,
        raw_response: str,
        final_response: str,
        duration_ms: int,
        protegrity_user: str = "superuser",
    ) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "gate2",
            {
                "node": "gate2",
                "duration_ms": duration_ms,
                "protegrity_user": protegrity_user,
                "raw_response": raw_response,
                "final_response": final_response,
            },
        )
        self._active_node = "gate2"

    def complete(
        self,
        *,
        blocked: bool = False,
        total_ms: int = 0,
        response: str = "",
    ) -> None:
        publish_event(
            self.run_id,
            self.source_app,
            "run_complete",
            {
                "node": "response",
                "blocked": blocked,
                "total_ms": total_ms,
                "response": response,
            },
        )
        self._active_node = "response"
