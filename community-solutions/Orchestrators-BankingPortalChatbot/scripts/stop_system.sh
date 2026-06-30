#!/usr/bin/env bash
# Stop Banking Portal Flask apps (and optionally Ollama / Protegrity stacks).
#
# Usage:
#   bash scripts/stop_system.sh              # stop Flask apps only
#   bash scripts/stop_system.sh --all        # also stop Ollama docker stack
#   bash scripts/stop_system.sh --protegrity # also stop Protegrity containers
#   bash scripts/stop_system.sh --all --protegrity
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
EDITION_DIR="${REPO_DIR}/.protegrity-install/protegrity-developer-edition"

STOP_LLM=false
STOP_PROTEGRITY=false
for arg in "$@"; do
  case "$arg" in
    --all) STOP_LLM=true ;;
    --protegrity) STOP_PROTEGRITY=true ;;
  esac
done

resolve_compose() {
  if docker compose version &>/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose &>/dev/null; then
    COMPOSE=(docker-compose)
  else
    return 1
  fi
}

compose_down() {
  local dir=$1
  if [[ -f "${dir}/docker-compose.yml" || -f "${dir}/docker-compose.yaml" ]]; then
    (cd "$dir" && "${COMPOSE[@]}" down) || true
  fi
}

stop_protegrity_stack() {
  echo ""
  echo "=== Stopping Protegrity containers ==="

  if resolve_compose; then
    if [[ -f "${EDITION_DIR}/docker-compose.yml" || -f "${EDITION_DIR}/docker-compose.yaml" ]]; then
      compose_down "$EDITION_DIR"
    else
      compose_down "${EDITION_DIR}/semantic-guardrail"
      compose_down "${EDITION_DIR}/data-discovery"
    fi
  fi

  # Fallback: remove by container_name (works even when compose v1 cannot parse upstream files)
  for name in semantic_guardrail classification_service pattern_provider context_provider; do
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
      docker rm -f "$name" >/dev/null 2>&1 || true
    fi
  done

  echo "Protegrity stack stopped"
}

if [[ -f "${REPO_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_DIR}/.env"
  set +a
fi

TECH_PORT="${TECH_PORT:-5002}"
BUSINESS_PORT="${BUSINESS_PORT:-5003}"
OBSERVER_PORT="${OBSERVER_PORT:-5004}"

echo "=== Stopping Banking Portal apps ==="

for name in technical business observer; do
  pid_file="${LOG_DIR}/${name}.pid"
  if [[ -f "$pid_file" ]]; then
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped ${name} (PID ${pid})"
    fi
    rm -f "$pid_file"
  fi
done

for port in "$TECH_PORT" "$BUSINESS_PORT" "$OBSERVER_PORT"; do
  if fuser "${port}/tcp" &>/dev/null 2>&1; then
    fuser -k "${port}/tcp" &>/dev/null 2>&1 || true
    echo "Freed port ${port}"
  fi
done

if $STOP_LLM; then
  echo ""
  echo "=== Stopping Ollama stack ==="
  if docker compose version &>/dev/null 2>&1; then
    (cd "${REPO_DIR}/infra/llm" && docker compose -f docker-compose.yml down) || true
  fi
  echo "Ollama stack stopped"
fi

if $STOP_PROTEGRITY; then
  stop_protegrity_stack
fi

echo ""
if $STOP_PROTEGRITY; then
  echo "Done."
else
  echo "Done. Protegrity containers are still running."
  echo "To stop Protegrity: bash scripts/stop_system.sh --protegrity"
fi
