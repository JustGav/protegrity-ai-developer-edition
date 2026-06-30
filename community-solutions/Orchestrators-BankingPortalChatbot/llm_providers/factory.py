"""
LLM provider factory.

Returns a unified callable: llm(messages) -> str
Also provides LangChain-compatible ChatModel objects.

Providers:
  - ollama: Local Ollama (/api/chat with think disabled for qwen3.5)
  - openai: ChatGPT (OpenAI API)
  - anthropic: Claude (Anthropic API)
  - grok: Grok (xAI OpenAI-compatible API)
"""

from __future__ import annotations

import os
from typing import Dict, List

import requests

from config.llm_api_keys import get_api_key, sync_keys_to_env
from config.local_llm_config import (
    get_ollama_base_url,
    resolve_active_ollama_model,
)
from config.orchestration_config import LLM_PROVIDER, get_model_name

try:
    import openai
except ImportError:
    openai = None  # type: ignore

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore


def _active_provider() -> str:
    return os.environ.get("LLM_PROVIDER", LLM_PROVIDER).lower()


def get_llm():
    """
    Return a callable: fn(messages: List[Dict]) -> str

    messages format: [{"role": "system"|"user"|"assistant", "content": "..."}]
    """
    sync_keys_to_env()
    provider = _active_provider()
    model = get_model_name(provider)

    if provider == "ollama":
        return _ollama_llm(model)
    if provider == "openai":
        return _openai_llm(model)
    if provider == "anthropic":
        return _anthropic_llm(model)
    if provider == "grok":
        return _grok_llm(model)
    raise ValueError(f"Unknown LLM provider: {provider}")


def get_llm_for_langchain():
    """Return a LangChain ChatModel instance for the configured provider."""
    sync_keys_to_env()
    provider = _active_provider()
    model = get_model_name(provider)

    if provider == "ollama":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key="ollama",
            base_url=f"{get_ollama_base_url()}/v1",
            temperature=0,
            max_tokens=4096,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=get_api_key("openai"), temperature=0)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, api_key=get_api_key("anthropic"), temperature=0)

    if provider == "grok":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=get_api_key("grok"),
            base_url="https://api.x.ai/v1",
            temperature=0,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")


def _ollama_native_chat(model: str, messages: List[Dict]) -> str:
    """Use Ollama native chat API so qwen3.5 thinking can be disabled."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 4096},
    }
    response = requests.post(
        f"{get_ollama_base_url()}/api/chat",
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    text = (response.json().get("message") or {}).get("content", "").strip()
    if not text:
        raise ValueError(f"Ollama returned empty response for model {model}")
    return text


def _ollama_llm(model: str):
    resolved_model = model or resolve_active_ollama_model()

    def call(messages: List[Dict]) -> str:
        return _ollama_native_chat(resolved_model, messages)

    return call


def _openai_llm(model: str):
    if openai is None:
        raise ImportError("pip install openai")
    api_key = get_api_key("openai")
    if not api_key:
        raise ValueError("OpenAI API key not configured. Set it in the Technical App dashboard.")
    client = openai.OpenAI(api_key=api_key)

    def call(messages: List[Dict]) -> str:
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        if not resp.choices or not resp.choices[0].message.content:
            raise ValueError(f"OpenAI returned empty response for model {model}")
        return resp.choices[0].message.content.strip()

    return call


def _anthropic_llm(model: str):
    if anthropic is None:
        raise ImportError("pip install anthropic")
    api_key = get_api_key("anthropic")
    if not api_key:
        raise ValueError("Anthropic API key not configured. Set it in the Technical App dashboard.")
    client = anthropic.Anthropic(api_key=api_key)

    def call(messages: List[Dict]) -> str:
        system = ""
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                chat_msgs.append(m)

        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system.strip() or "You are a helpful assistant.",
            messages=chat_msgs,
            temperature=0,
        )
        if not resp.content or not resp.content[0].text:
            raise ValueError(f"Anthropic returned empty response for model {model}")
        return resp.content[0].text.strip()

    return call


def _grok_llm(model: str):
    if openai is None:
        raise ImportError("pip install openai")
    api_key = get_api_key("grok")
    if not api_key:
        raise ValueError("Grok (xAI) API key not configured. Set it in the Technical App dashboard.")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    def call(messages: List[Dict]) -> str:
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0)
        if not resp.choices or not resp.choices[0].message.content:
            raise ValueError(f"Grok returned empty response for model {model}")
        return resp.choices[0].message.content.strip()

    return call


# ── Aliases for backward compatibility ──────────────────────────────
get_llm_provider = get_llm
