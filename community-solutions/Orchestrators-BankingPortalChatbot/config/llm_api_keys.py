"""
Runtime and persisted LLM API key management for the Technical App.

Keys are loaded from environment variables on startup, then optionally
overridden from config/llm_api_keys.local.json (gitignored). Updates via
the Technical App dashboard persist to that file and sync to os.environ.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

CONFIG_DIR = Path(__file__).resolve().parent
KEYS_FILE = CONFIG_DIR / "llm_api_keys.local.json"

# Provider id -> environment variable name
PROVIDER_ENV_KEYS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "grok": "XAI_API_KEY",
}

CLOUD_PROVIDERS = tuple(PROVIDER_ENV_KEYS.keys())

_runtime_keys: Dict[str, str] = {}
_initialized = False


def _load_persisted() -> Dict[str, str]:
    if not KEYS_FILE.exists():
        return {}
    try:
        data = json.loads(KEYS_FILE.read_text())
        return {k: v for k, v in data.items() if k in PROVIDER_ENV_KEYS and isinstance(v, str)}
    except (json.JSONDecodeError, OSError):
        return {}


def init_api_keys() -> None:
    """Load keys from env + persisted file into runtime cache and os.environ."""
    global _initialized
    persisted = _load_persisted()
    for provider, env_var in PROVIDER_ENV_KEYS.items():
        key = os.getenv(env_var, "").strip() or persisted.get(provider, "").strip()
        if key:
            _runtime_keys[provider] = key
            os.environ[env_var] = key
    _initialized = True


def get_api_key(provider: str) -> str:
    if not _initialized:
        init_api_keys()
    provider = provider.lower()
    if provider in _runtime_keys:
        return _runtime_keys[provider]
    env_var = PROVIDER_ENV_KEYS.get(provider)
    if env_var:
        return os.getenv(env_var, "").strip()
    return ""


def set_api_key(provider: str, api_key: str) -> None:
    """Update a provider API key in memory, env, and persisted storage."""
    provider = provider.lower()
    if provider not in PROVIDER_ENV_KEYS:
        raise ValueError(f"Unknown provider: {provider}")

    key = api_key.strip()
    env_var = PROVIDER_ENV_KEYS[provider]

    if key:
        _runtime_keys[provider] = key
        os.environ[env_var] = key
    else:
        _runtime_keys.pop(provider, None)
        os.environ.pop(env_var, None)

    persisted = _load_persisted()
    if key:
        persisted[provider] = key
    else:
        persisted.pop(provider, None)

    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if persisted:
        KEYS_FILE.write_text(json.dumps(persisted, indent=2) + "\n")
    elif KEYS_FILE.exists():
        KEYS_FILE.unlink()


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}••••{key[-4:]}"


def get_keys_status() -> Dict[str, dict]:
    """Return masked key status for each cloud provider (safe for API responses)."""
    if not _initialized:
        init_api_keys()
    return {
        provider: {
            "configured": bool(get_api_key(provider)),
            "masked": mask_api_key(get_api_key(provider)),
        }
        for provider in CLOUD_PROVIDERS
    }


def sync_keys_to_env() -> None:
    """Push all runtime keys into os.environ (call before orchestrator LLM calls)."""
    if not _initialized:
        init_api_keys()
    for provider, env_var in PROVIDER_ENV_KEYS.items():
        key = _runtime_keys.get(provider) or os.getenv(env_var, "").strip()
        if key:
            os.environ[env_var] = key
