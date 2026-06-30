#!/usr/bin/env bash
# Start Ollama Docker stack for Banking Portal Chatbot.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_DIR="${REPO_DIR}/infra/llm"
COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"

GPU=false
NO_PULL=false
for arg in "$@"; do
  if [[ "$arg" == "--gpu" ]]; then
    GPU=true
  elif [[ "$arg" == "--no-pull" ]]; then
    NO_PULL=true
  fi
done

if docker compose version &>/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose &>/dev/null; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required." >&2
  exit 1
fi

cd "$COMPOSE_DIR"

echo "=== Starting Banking Portal LLM stack (Ollama) ==="
if $GPU; then
  echo "GPU overlay enabled"
  "${COMPOSE[@]}" -f docker-compose.yml -f docker-compose.gpu.yml up -d
else
  "${COMPOSE[@]}" -f docker-compose.yml up -d
fi

echo ""
echo "Waiting for Ollama..."
for i in $(seq 1 60); do
  if curl -sf "http://localhost:${OLLAMA_HOST_PORT:-11435}/api/tags" >/dev/null 2>&1; then
    echo "✔ Ollama is ready"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "⚠ Timeout — check: docker compose -f infra/llm/docker-compose.yml ps"
    docker compose -f docker-compose.yml ps
    exit 1
  fi
  sleep 5
done

MODEL="${OLLAMA_ACTIVE_MODEL:-${OLLAMA_CPU_MODEL:-qwen3.5:0.8b}}"
if $NO_PULL; then
  echo ""
  echo "Skipping model pull (--no-pull)"
else
  echo ""
  echo "Pulling model: ${MODEL}"
  docker exec banking_ollama ollama pull "${MODEL}" || echo "⚠ Could not pull ${MODEL}"
fi

echo ""
echo "=== LLM Docker stack ==="
docker compose -f docker-compose.yml ps
echo ""
echo "Ollama: http://localhost:${OLLAMA_HOST_PORT:-11435}"
echo ""
echo "Set in .env:"
echo "  OLLAMA_BASE_URL=http://localhost:${OLLAMA_HOST_PORT:-11435}"
echo "  LLM_PROVIDER=ollama"
