#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# start_system.sh — Bootstrap and start the full Banking Portal stack.
#
# Checks/installs: Python venv, dependencies, Protegrity containers + SDK,
# Ollama (Docker), then starts all three Flask apps.
#
# Usage:
#   bash scripts/start_system.sh              # full bootstrap + start
#   bash scripts/start_system.sh --gpu        # Ollama with GPU overlay
#   bash scripts/start_system.sh --check      # status only (no changes)
#   bash scripts/start_system.sh --apps-only    # start Flask apps only
#   bash scripts/start_system.sh --no-pull      # skip Ollama model pull
#   PYTHON=python3.12 bash scripts/start_system.sh  # force Python version
#
# Stop everything:
#   bash scripts/stop_system.sh
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="${REPO_DIR}/scripts"
LOG_DIR="${REPO_DIR}/logs"
VENV_DIR="${REPO_DIR}/.venv"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}✔${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✖${NC} $*"; }
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

CHECK_ONLY=false
APPS_ONLY=false
GPU=false
NO_PULL=false

for arg in "$@"; do
  case "$arg" in
    --check)    CHECK_ONLY=true ;;
    --apps-only) APPS_ONLY=true ;;
    --gpu)      GPU=true ;;
    --no-pull)  NO_PULL=true ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      error "Unknown option: $arg (try --help)"
      exit 1
      ;;
  esac
done

cd "$REPO_DIR"

load_env() {
  if [[ -f "${REPO_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_DIR}/.env"
    set +a
  fi
  TECH_PORT="${TECH_PORT:-5002}"
  BUSINESS_PORT="${BUSINESS_PORT:-5003}"
  OBSERVER_PORT="${OBSERVER_PORT:-5004}"
  OLLAMA_HOST_PORT="${OLLAMA_HOST_PORT:-11435}"
  OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:${OLLAMA_HOST_PORT}}"
}

activate_venv() {
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/lib_python.sh"
  if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    ensure_python_venv "$REPO_DIR" || exit 1
  elif ! python_version_ok python3; then
    error "Active venv uses unsupported Python: $(python3 --version 2>&1)"
    suggest_python_install
    exit 1
  fi
}

ensure_env_file() {
  if [[ ! -f "${REPO_DIR}/.env" ]]; then
    if [[ -f "${REPO_DIR}/.env.example" ]]; then
      cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
      warn "Created .env from .env.example — edit Protegrity credentials before chat will work"
    else
      error "Missing .env and .env.example"
      exit 1
    fi
  fi
  load_env
  if grep -qE 'your-email@company.com|your-password|your-api-key' "${REPO_DIR}/.env" 2>/dev/null; then
    warn "Protegrity credentials in .env look like placeholders — sign up at:"
    echo "       https://www.protegrity.com/developers/dev-edition-api"
  fi
}

check_docker() {
  command -v docker &>/dev/null && docker info &>/dev/null
}

check_protegrity_containers() {
  local running
  running=$(docker ps --format '{{.Names}}' 2>/dev/null \
    | grep -cE 'classification_service|semantic_guardrail|pattern_provider|context_provider' || true)
  [[ "$running" -ge 4 ]]
}

check_python_sdk() {
  activate_venv
  python3 -c "import protegrity_developer_python; assert hasattr(protegrity_developer_python, 'find_and_unprotect')" &>/dev/null
}

check_ollama() {
  curl -sf "${OLLAMA_BASE_URL}/api/tags" &>/dev/null
}

check_flask_deps() {
  activate_venv
  python3 -c "import flask" &>/dev/null
}

check_app_port() {
  local port=$1
  curl -sf -o /dev/null "http://localhost:${port}/" 2>/dev/null \
    || curl -sf -o /dev/null "http://localhost:${port}/tech/login" 2>/dev/null \
    || curl -sf -o /dev/null "http://localhost:${port}/bank/login" 2>/dev/null \
    || curl -sf -o /dev/null "http://localhost:${port}/observe/login" 2>/dev/null
}

status_report() {
  step "System status"
  local ok=true

  if check_flask_deps; then info "Python dependencies installed"; else warn "Python dependencies missing"; ok=false; fi
  if check_docker; then info "Docker is running"; else warn "Docker not available"; ok=false; fi
  if check_protegrity_containers; then info "Protegrity containers running"; else warn "Protegrity containers not running"; ok=false; fi
  if check_python_sdk; then info "Protegrity Python SDK ready"; else warn "Protegrity Python SDK missing/incomplete"; ok=false; fi
  if check_ollama; then info "Ollama reachable at ${OLLAMA_BASE_URL}"; else warn "Ollama not reachable at ${OLLAMA_BASE_URL}"; ok=false; fi

  for label_port in "Technical:${TECH_PORT}" "Business:${BUSINESS_PORT}" "Observer:${OBSERVER_PORT}"; do
    local label="${label_port%%:*}" port="${label_port##*:}"
    if check_app_port "$port"; then
      info "${label} app responding on :${port}"
    else
      warn "${label} app not responding on :${port}"
      ok=false
    fi
  done

  $ok || return 1
  return 0
}

install_protegrity() {
  step "Protegrity Developer Edition"
  bash "${SCRIPT_DIR}/setup_protegrity.sh"
  activate_venv
}

install_ollama() {
  step "Ollama LLM stack"
  local llm_args=()
  $GPU && llm_args+=(--gpu)
  $NO_PULL && llm_args+=(--no-pull)
  bash "${SCRIPT_DIR}/start_llm_docker.sh" "${llm_args[@]}"
}

stop_app_ports() {
  step "Stopping existing app processes"
  for port in "$TECH_PORT" "$BUSINESS_PORT" "$OBSERVER_PORT"; do
    if fuser "${port}/tcp" &>/dev/null 2>&1; then
      fuser -k "${port}/tcp" &>/dev/null 2>&1 || true
      info "Freed port ${port}"
    fi
  done
  sleep 1
}

start_flask_apps() {
  step "Starting Flask applications"
  mkdir -p "$LOG_DIR"
  activate_venv

  export TECH_PORT BUSINESS_PORT OBSERVER_PORT
  export OLLAMA_BASE_URL LLM_PROVIDER="${LLM_PROVIDER:-ollama}" ORCHESTRATOR="${ORCHESTRATOR:-langgraph}"

  nohup python3 "${REPO_DIR}/TechnicalApp/run.py" \
    > "${LOG_DIR}/technical.log" 2>&1 &
  echo $! > "${LOG_DIR}/technical.pid"
  info "TechnicalApp  PID $(cat "${LOG_DIR}/technical.pid")  → http://localhost:${TECH_PORT}/tech/login"

  nohup python3 "${REPO_DIR}/BusinessCustomerApp/run.py" \
    > "${LOG_DIR}/business.log" 2>&1 &
  echo $! > "${LOG_DIR}/business.pid"
  info "BusinessApp   PID $(cat "${LOG_DIR}/business.pid")  → http://localhost:${BUSINESS_PORT}/bank/login"

  nohup python3 "${REPO_DIR}/FlowObserverApp/run.py" \
    > "${LOG_DIR}/observer.log" 2>&1 &
  echo $! > "${LOG_DIR}/observer.pid"
  info "ObserverApp   PID $(cat "${LOG_DIR}/observer.pid")  → http://localhost:${OBSERVER_PORT}/observe/login"

  echo ""
  echo "Waiting for apps to accept connections..."
  local ready=0
  for _ in $(seq 1 30); do
    ready=0
    if check_app_port "$TECH_PORT"; then ready=$((ready + 1)); fi
    if check_app_port "$BUSINESS_PORT"; then ready=$((ready + 1)); fi
    if check_app_port "$OBSERVER_PORT"; then ready=$((ready + 1)); fi
    if [[ "$ready" -eq 3 ]]; then
      break
    fi
    sleep 1
  done

  if [[ "$ready" -lt 3 ]]; then
    warn "Some apps may still be starting — check logs in ${LOG_DIR}/"
  else
    info "All three apps are responding"
  fi
}

print_summary() {
  step "Ready"
  cat <<EOF
  Technical Portal   http://localhost:${TECH_PORT}/tech/login
                     admin / Adm!n@S3cure2026

  Banking Portal     http://localhost:${BUSINESS_PORT}/bank/login
                     allison100 / pass100  (see login page for more)

  Pipeline Observer  http://localhost:${OBSERVER_PORT}/observe/login
                     admin / Adm!n@S3cure2026

  Logs:    ${LOG_DIR}/
  Stop:    bash scripts/stop_system.sh
EOF
}

main() {
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║   Banking Portal Chatbot — Full System Start             ║"
  echo "╚══════════════════════════════════════════════════════════╝"

  ensure_env_file

  if $CHECK_ONLY; then
    status_report || exit 1
    exit 0
  fi

  if ! $APPS_ONLY; then
    install_protegrity
    install_ollama
  else
    activate_venv
    if ! check_flask_deps; then
      warn "Installing Python dependencies..."
      install_project_requirements "$REPO_DIR" || exit 1
    fi
  fi

  stop_app_ports
  start_flask_apps
  print_summary
}

main "$@"
