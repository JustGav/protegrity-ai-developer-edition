"""
Orchestration & LLM configuration.

Set ORCHESTRATOR and LLM_PROVIDER via environment variables or change defaults here.

Supported orchestrators: langgraph, crewai, llamaindex, direct
Supported LLM providers: ollama, openai (ChatGPT), anthropic (Claude), grok (xAI)
"""

import os
from dotenv import load_dotenv

from config.local_llm_config import (
    DEFAULT_CPU_MODEL,
    resolve_active_ollama_model,
)

load_dotenv()

LLM_PROVIDERS = ("ollama", "openai", "anthropic", "grok")

LLM_PROVIDER_LABELS = {
    "ollama": "Ollama (Local)",
    "openai": "ChatGPT (OpenAI)",
    "anthropic": "Claude (Anthropic)",
    "grok": "Grok (xAI)",
}

# ── Orchestrator selection ───────────────────────────────────────────
ORCHESTRATOR = os.getenv("ORCHESTRATOR", "langgraph").lower()
assert ORCHESTRATOR in ("langgraph", "crewai", "llamaindex", "direct"), \
    f"Unknown orchestrator: {ORCHESTRATOR}"

# ── LLM provider selection ──────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
assert LLM_PROVIDER in LLM_PROVIDERS, f"Unknown LLM provider: {LLM_PROVIDER}"

# ── LLM model defaults ───────────────────────────────────────────────
LLM_MODEL = os.getenv("LLM_MODEL", None)

DEFAULT_MODELS = {
    "ollama": DEFAULT_CPU_MODEL,
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "grok": "grok-3-mini",
}


def get_model_name(provider: str | None = None) -> str:
    if LLM_MODEL:
        return LLM_MODEL
    p = (provider or os.getenv("LLM_PROVIDER") or LLM_PROVIDER).lower()
    if p == "ollama":
        return resolve_active_ollama_model()
    return DEFAULT_MODELS.get(p, resolve_active_ollama_model())

# ── Ollama settings ──────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CPU_MODEL = os.getenv("OLLAMA_CPU_MODEL", DEFAULT_CPU_MODEL)
OLLAMA_GPU_MODEL = os.getenv("OLLAMA_GPU_MODEL", "qwen3.5:4b")
OLLAMA_GPU_ENABLED = os.getenv("OLLAMA_GPU_ENABLED", "")
OLLAMA_ACTIVE_MODEL = os.getenv("OLLAMA_ACTIVE_MODEL", "")

# ── RAG / Knowledge Graph settings ──────────────────────────────────
USE_KNOWLEDGE_GRAPH = os.getenv("USE_KNOWLEDGE_GRAPH", "true").lower() == "true"
USE_CHROMADB = os.getenv("USE_CHROMADB", "true").lower() == "true"
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))

# ── Protegrity gate settings ────────────────────────────────────────
SKIP_PROTEGRITY_GATES = os.getenv("SKIP_PROTEGRITY_GATES", "false").lower() == "true"
SKIP_SEMANTIC_GUARDRAIL = os.getenv("SKIP_SEMANTIC_GUARDRAIL", "true").lower() == "true"
PII_DISCOVERY_THRESHOLD = float(os.getenv("PII_DISCOVERY_THRESHOLD", "0.4"))
GUARDRAIL_RISK_THRESHOLD = float(os.getenv("GUARDRAIL_RISK_THRESHOLD", "0.7"))


# ── Aliases for backward compatibility ──────────────────────────────
get_model = get_model_name
RISK_THRESHOLD = GUARDRAIL_RISK_THRESHOLD
PROTEGRITY_USER = os.getenv("PROTEGRITY_USER", "default_user")
KB_ENABLED = USE_KNOWLEDGE_GRAPH
