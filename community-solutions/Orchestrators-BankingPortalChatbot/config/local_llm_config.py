"""
Local LLM configuration — Ollama.

Resolves active model from OLLAMA_ACTIVE_MODEL, GPU/CPU env vars, or auto-detected GPU.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

import requests

DEFAULT_CPU_MODEL = "qwen3.5:0.8b"
DEFAULT_GPU_MODEL = "qwen3.5:4b"

_resolved_ollama_base_url: Optional[str] = None


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def detect_nvidia_gpu() -> bool:
    """Return True when nvidia-smi is available and reports a GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def is_ollama_gpu_enabled() -> bool:
    """GPU mode from OLLAMA_GPU_ENABLED, or auto-detect when unset."""
    configured = _env_bool("OLLAMA_GPU_ENABLED")
    if configured is not None:
        return configured
    return detect_nvidia_gpu()


def resolve_active_ollama_model() -> str:
    """
    Pick the active Ollama model.

    Priority: OLLAMA_ACTIVE_MODEL -> GPU model (when enabled) -> CPU model.
    """
    active = os.getenv("OLLAMA_ACTIVE_MODEL", "").strip()
    if active:
        return active
    if is_ollama_gpu_enabled():
        gpu_model = os.getenv("OLLAMA_GPU_MODEL", DEFAULT_GPU_MODEL).strip()
        if gpu_model:
            return gpu_model
    return os.getenv("OLLAMA_CPU_MODEL", DEFAULT_CPU_MODEL).strip() or DEFAULT_CPU_MODEL


def get_ollama_base_url_candidates() -> List[str]:
    """Ordered Ollama base URLs — Docker maps host 11435 -> container 11434."""
    candidates: List[str] = []
    configured = os.getenv("OLLAMA_BASE_URL", "").strip()
    if configured:
        candidates.append(_normalize_base_url(configured))

    candidates.extend(
        [
            "http://localhost:11435",
            "http://localhost:11434",
            "http://ollama:11434",
            "http://host.docker.internal:11435",
        ]
    )

    deduped: List[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def probe_ollama_health(base_url: str, timeout: float = 4.0) -> bool:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


def resolve_ollama_base_url(force_refresh: bool = False) -> str:
    """Return the first healthy Ollama base URL (cached)."""
    global _resolved_ollama_base_url
    if _resolved_ollama_base_url and not force_refresh:
        return _resolved_ollama_base_url

    for candidate in get_ollama_base_url_candidates():
        if probe_ollama_health(candidate):
            _resolved_ollama_base_url = candidate.rstrip("/")
            return _resolved_ollama_base_url

    fallback = get_ollama_base_url_candidates()[0]
    _resolved_ollama_base_url = fallback.rstrip("/")
    return _resolved_ollama_base_url


def get_ollama_base_url() -> str:
    return resolve_ollama_base_url()


def reset_ollama_url_cache() -> None:
    global _resolved_ollama_base_url
    _resolved_ollama_base_url = None
