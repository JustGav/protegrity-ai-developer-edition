"""
LlamaIndex orchestrator — query pipeline (protected-in, protected-out).

Pipeline: Retrieve → LlamaIndex LLM

Gate 1 and Gate 2 are handled by the caller.
"""

from __future__ import annotations
import logging, os
from pathlib import Path
from typing import Dict, List, Optional

from orchestrators.base import BaseOrchestrator, PipelineResult
from common.protegrity_gates import register_context_tokens
from config.local_llm_config import get_ollama_base_url
from config.orchestration_config import (
    get_model_name,
    KB_ENABLED,
    LLM_PROVIDER,
)

log = logging.getLogger(__name__)

KB_DIR = Path(__file__).resolve().parent.parent / "banking_data" / "knowledge_base"

SYSTEM_PROMPT = (
    "You are a helpful banking assistant for SecureBank. "
    "Be concise, professional, and accurate. "
    "IMPORTANT: Preserve all PII tags like [PERSON]value[/PERSON] exactly as they appear."
)


def _get_llama_llm():
    """Return a LlamaIndex LLM instance based on the configured provider."""
    from config.llm_api_keys import get_api_key, sync_keys_to_env

    sync_keys_to_env()
    provider = os.environ.get("LLM_PROVIDER", LLM_PROVIDER)
    model = os.environ.get("LLM_MODEL") or get_model_name(provider)

    if provider == "ollama":
        from llama_index.llms.openai_like import OpenAILike

        return OpenAILike(
            model=model,
            api_key="ollama",
            api_base=f"{get_ollama_base_url()}/v1",
            temperature=0.3,
            max_tokens=4096,
            is_chat_model=True,
            additional_kwargs={"think": False},
        )
    if provider == "openai":
        from llama_index.llms.openai import OpenAI as LlamaOpenAI

        return LlamaOpenAI(
            model=model,
            api_key=get_api_key("openai"),
            temperature=0.3,
            max_tokens=4096,
        )
    if provider == "anthropic":
        from llama_index.llms.anthropic import Anthropic as LlamaAnthropic

        return LlamaAnthropic(
            model=model,
            api_key=get_api_key("anthropic"),
            max_tokens=4096,
        )
    if provider == "grok":
        from llama_index.llms.openai_like import OpenAILike

        return OpenAILike(
            model=model,
            api_key=get_api_key("grok"),
            api_base="https://api.x.ai/v1",
            temperature=0.3,
            max_tokens=4096,
            is_chat_model=True,
        )
    raise ValueError(f"Unsupported LLM provider for LlamaIndex: {provider}")


class LlamaIndexOrchestrator(BaseOrchestrator):

    @property
    def name(self) -> str:
        return "LlamaIndex"

    def run(
        self,
        user_message: str,
        *,
        customer_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        protected_context: Optional[str] = None,
    ) -> PipelineResult:
        from llama_index.core.llms import ChatMessage, MessageRole

        # ── Retrieve ──
        kb_context = protected_context or ""
        if not kb_context and KB_ENABLED and customer_id:
            kb_file = KB_DIR / f"{customer_id}.txt"
            if kb_file.exists():
                kb_context = kb_file.read_text().strip()
        if kb_context:
            register_context_tokens(kb_context)

        # ── Build messages ──
        system_content = SYSTEM_PROMPT
        if kb_context:
            system_content += f"\n\nCustomer Data:\n{kb_context}"

        messages = [ChatMessage(role=MessageRole.SYSTEM, content=system_content)]
        for m in conversation_history or []:
            role = MessageRole.USER if m["role"] == "user" else MessageRole.ASSISTANT
            if m["role"] == "system":
                continue
            messages.append(ChatMessage(role=role, content=m["content"]))
        messages.append(ChatMessage(role=MessageRole.USER, content=user_message))

        # ── LLM call ──
        try:
            llm = _get_llama_llm()
            response = llm.chat(messages)
            raw_response = response.message.content
        except Exception as e:
            log.error("LlamaIndex LLM call failed: %s", e)
            raw_response = f"LlamaIndex LLM error: {e}"

        return PipelineResult(
            answer=raw_response,
            raw_llm_response=raw_response,
            metadata={"orchestrator": self.name},
        )
