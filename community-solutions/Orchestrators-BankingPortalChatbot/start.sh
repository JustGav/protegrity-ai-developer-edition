#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# start.sh — Master launcher for the Banking Portal Chatbot
#
# What this script does:
#   1. Verifies Docker is installed and running.
#   2. Checks whether Protegrity Developer Edition containers are active.
#      - If YES  → does nothing (leaves them untouched).
#      - If NO   → starts them from .protegrity-install/ and waits until
#                  they are healthy.
#   3. Builds (if needed) and starts TechnicalApp (port 5002) and
#      BusinessCustomerApp (port 5003) via docker compose.
#
# Usage:
#   ./start.sh            # start everything
#   ./start.sh --stop     # stop app containers (leaves Protegrity running)
#   ./start.sh --restart  # stop then start app containers
#   ./start.sh --logs     # stream logs from both apps
#   ./start.sh --status   # show running containers and health
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PTY_EDITION_DIR="${SCRIPT_DIR}/.protegrity-install/protegrity-developer-edition"
PTY_WAIT_TIMEOUT=300   # seconds to wait for Protegrity to become healthy (longer on ARM/M-series)

# ── Colours ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✔${NC}  $*"; }
info() { echo -e "${BLUE}→${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✖${NC}  $*" >&2; exit 1; }
hr()   { echo -e "${BOLD}──────────────────────────────────────────────────────${NC}"; }

# ── Detect docker compose command ─────────────────────────────────────
detect_compose() {
    if docker compose version &>/dev/null 2>&1; then
        COMPOSE="docker compose"
    elif command -v docker-compose &>/dev/null; then
        COMPOSE="docker-compose"
    else
        fail "Docker Compose not found. Install Docker Desktop: https://docs.docker.com/get-docker/"
    fi
}

# ── Check Docker daemon ───────────────────────────────────────────────
check_docker() {
    if ! command -v docker &>/dev/null; then
        fail "Docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/"
    fi
    if ! docker info &>/dev/null 2>&1; then
        fail "Docker daemon is not running. Please start Docker Desktop and try again."
    fi
    ok "Docker is running."
}

# ── Check if Protegrity containers are up (≥3 of 4 expected services) ─
protegrity_is_running() {
    local count
    count=$(docker ps --format '{{.Names}}' 2>/dev/null \
        | grep -cE '^(classification_service|semantic_guardrail|pattern_provider|context_provider)$' \
        || true)
    [ "${count}" -ge 3 ]
}

# ── Wait until Protegrity HTTP endpoints accept connections ───────────
wait_for_protegrity() {
    local elapsed=0
    info "Waiting for Protegrity services to be ready (timeout ${PTY_WAIT_TIMEOUT}s) ..."
    # Use TCP check (nc) rather than curl -f: a 4xx HTTP response means the
    # service is alive, but curl -f treats 4xx as failure (non-zero exit code).
    # BSD netcat (macOS) uses -G for connect timeout; GNU uses -w
    local nc_cmd="nc -z -w 3"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        nc_cmd="nc -z -G 3"
    fi
    until $nc_cmd localhost 8580 2>/dev/null; do
        if [ "${elapsed}" -ge "${PTY_WAIT_TIMEOUT}" ]; then
            warn "Protegrity services did not respond within ${PTY_WAIT_TIMEOUT}s."
            warn "The apps will start in degraded mode (PII protection unavailable)."
            return 0
        fi
        printf "  still waiting ... %ss elapsed\r" "${elapsed}"
        sleep 5
        elapsed=$((elapsed + 5))
    done
    echo ""
    ok "Protegrity services are ready."
}

# ── Pre-create protegrity-network to avoid macOS Docker race condition ─
# Docker Desktop on macOS can fail with "network <id> not found" when a
# network is created inline during `compose up` (the network is assigned an
# ID but the VM networking layer loses the reference before containers start).
# Pre-creating the network makes it stable before compose ever runs.
prune_and_create_network() {
    # Remove any existing stale entry (ignores error if it doesn't exist)
    if docker network inspect protegrity-network &>/dev/null 2>&1; then
        info "Removing existing protegrity-network for clean recreation ..."
        # Disconnect any lingering containers first
        local cids
        cids=$(docker network inspect protegrity-network \
               -f '{{range $k,$v := .Containers}}{{$k}} {{end}}' 2>/dev/null || true)
        for cid in ${cids}; do
            docker network disconnect -f protegrity-network "${cid}" &>/dev/null 2>&1 || true
        done
        docker network rm protegrity-network &>/dev/null 2>&1 || true
        sleep 1
    fi

    # Prune any other unused networks that might hold stale references
    docker network prune -f &>/dev/null 2>&1 || true

    # Create the network explicitly — compose will detect it exists and skip
    # its own inline creation, avoiding the race condition entirely
    docker network create --driver bridge protegrity-network \
        --label "com.docker.compose.network=protegrity-network" \
        --label "com.docker.compose.project=protegrity-developer-edition" \
        &>/dev/null 2>&1 \
        && ok "protegrity-network created." \
        || { warn "protegrity-network may already exist — continuing."; }
}

# ── Ensure Protegrity Developer Edition is running ────────────────────
ensure_protegrity() {
    hr
    echo -e "${BOLD}Protegrity Developer Edition${NC}"

    if protegrity_is_running; then
        ok "Protegrity Developer Edition containers are already running — no action needed."
        return 0
    fi

    warn "Protegrity containers are not running."

    # Attempt to start from the cloned repository
    if [ ! -f "${PTY_EDITION_DIR}/docker-compose.yml" ]; then
        echo ""
        fail "Protegrity Developer Edition not found at:
  ${PTY_EDITION_DIR}

Please run the setup script first:
  bash scripts/setup_protegrity.sh
"
    fi

    # macOS Docker Desktop has a race condition where a network created inline
    # during `compose up` disappears before containers can attach to it, producing
    # "failed to set up container networking: network <id> not found".
    #
    # Fix: pre-create protegrity-network manually so compose skips its own
    # network creation step and attaches directly to the already-stable network.
    info "Ensuring protegrity-network exists before starting containers ..."
    prune_and_create_network

    info "Starting Protegrity Developer Edition containers ..."
    # `compose down` removes exited containers that carry stale network IDs,
    # then `compose up -d` recreates them against the freshly created network.
    (cd "${PTY_EDITION_DIR}" && ${COMPOSE} down --remove-orphans 2>/dev/null || true)
    (cd "${PTY_EDITION_DIR}" && ${COMPOSE} up -d)

    wait_for_protegrity
}

# ── Ensure streamlit is available (auto-install into .chromadb-venv) ────
ensure_streamlit() {
    # Already on PATH (system, active venv, etc.)
    command -v streamlit &>/dev/null && return 0

    # Check the dedicated venv
    local venv="${SCRIPT_DIR}/.chromadb-venv"
    if [ -x "${venv}/bin/streamlit" ]; then
        export PATH="${venv}/bin:${PATH}"
        return 0
    fi

    # Create the venv and install streamlit + chromadb
    info "Installing streamlit into ${venv} ..."
    local py=""
    for candidate in python3.12 python3.13 python3; do
        if command -v "${candidate}" &>/dev/null; then py="${candidate}"; break; fi
    done
    if [ -z "${py}" ]; then
        warn "No python3 found — cannot auto-install streamlit."
        return 1
    fi
    "${py}" -m venv "${venv}" \
        && "${venv}/bin/pip" install --quiet --upgrade pip \
        && "${venv}/bin/pip" install --quiet streamlit chromadb \
        && export PATH="${venv}/bin:${PATH}" \
        && ok "streamlit installed in ${venv}" \
        || { warn "Failed to install streamlit — ChromaDB Viewer skipped."; return 1; }
}

start_chromadb_viewer() {
    # ChromaDB uses a file lock — cannot run inside Docker. Launch locally.
    hr
    echo -e "${BOLD}ChromaDB Viewer (local Streamlit)${NC}"
    chroma_pids=$(lsof -ti tcp:8501 2>/dev/null || true)
    if [ -n "${chroma_pids}" ]; then
        echo "${chroma_pids}" | xargs kill 2>/dev/null || true
        sleep 1
    fi

    # Ensure streamlit + chromadb are available BEFORE trying to rebuild
    if ! ensure_streamlit; then
        warn "ChromaDB Viewer not started (streamlit unavailable)."
        return 0
    fi

    # Auto-build the ChromaDB index if it doesn't exist yet (fresh clone)
    if [ ! -d "${SCRIPT_DIR}/chroma_db" ]; then
        info "chroma_db/ not found — building index from knowledge base ..."
        python3 scripts/browse_chromadb.py rebuild 2>&1 || warn "ChromaDB rebuild failed — viewer may show empty data."
    fi

    streamlit run scripts/chromadb_viewer.py \
        --server.headless true \
        --server.port 8501 \
        2>"${SCRIPT_DIR}/chromadb_viewer.log" &
    sleep 3
    if lsof -i tcp:8501 -sTCP:LISTEN &>/dev/null 2>&1; then
        ok "ChromaDB Viewer is healthy   → http://localhost:8501"
    else
        warn "ChromaDB Viewer may still be starting → http://localhost:8501"
        warn "Logs: ${SCRIPT_DIR}/chromadb_viewer.log"
    fi
}

# ── Command handling ──────────────────────────────────────────────────
CMD="${1:-}"

check_docker
detect_compose
cd "${SCRIPT_DIR}"

case "${CMD}" in
    --stop)
        hr
        info "Stopping Banking Portal apps ..."
        ${COMPOSE} down
        # Also stop local ChromaDB viewer if running
        chroma_pids=$(lsof -ti tcp:8501 2>/dev/null || true)
        if [ -n "${chroma_pids}" ]; then
            echo "${chroma_pids}" | xargs kill 2>/dev/null || true
            ok "ChromaDB Viewer stopped."
        fi
        ok "Apps stopped."
        exit 0
        ;;

    --restart)
        hr
        info "Restarting Banking Portal apps ..."
        ${COMPOSE} down
        # Also stop local ChromaDB viewer if running
        chroma_pids=$(lsof -ti tcp:8501 2>/dev/null || true)
        if [ -n "${chroma_pids}" ]; then
            echo "${chroma_pids}" | xargs kill 2>/dev/null || true
        fi
        ensure_protegrity
        # Pre-create bind-mount directories and fix ownership if needed
        for _bm_dir in "${SCRIPT_DIR}/TechnicalApp/chat_history_tech" \
                       "${SCRIPT_DIR}/BusinessCustomerApp/chat_history"; do
            mkdir -p "${_bm_dir}" 2>/dev/null || true
            if [ ! -w "${_bm_dir}" ]; then
                info "Fixing permissions on ${_bm_dir} ..."
                sudo chown -R "$(id -u):$(id -g)" "${_bm_dir}" 2>/dev/null \
                    || sudo chmod -R 777 "${_bm_dir}" 2>/dev/null \
                    || warn "Could not fix permissions on ${_bm_dir} — chat history may fail."
            fi
        done
        ${COMPOSE} up --build -d
        start_chromadb_viewer
        ok "Apps restarted."
        exit 0
        ;;

    --logs)
        ${COMPOSE} logs -f
        exit 0
        ;;

    --status)
        hr
        echo -e "${BOLD}Protegrity containers${NC}"
        docker ps --format "  {{.Names}}\t{{.Status}}" \
            --filter "name=classification_service" \
            --filter "name=semantic_guardrail" \
            --filter "name=pattern_provider" \
            --filter "name=context_provider" \
            2>/dev/null || true
        echo ""
        echo -e "${BOLD}Banking Portal apps${NC}"
        docker ps --format "  {{.Names}}\t{{.Status}}\t{{.Ports}}" \
            --filter "name=technical_app" \
            --filter "name=business_app" \
            --filter "name=banking_pgweb" \
            --filter "name=kuzu_explorer" \
            2>/dev/null || true
        echo ""
        echo -e "${BOLD}ChromaDB Viewer (local)${NC}"
        if lsof -i tcp:8501 -sTCP:LISTEN &>/dev/null 2>&1; then
            ok "Running → http://localhost:8501"
        else
            warn "Not running. Start with: streamlit run scripts/chromadb_viewer.py"
        fi
        exit 0
        ;;

    "")
        # Default: start everything
        ;;

    *)
        echo "Usage: $0 [--stop | --restart | --logs | --status]"
        exit 1
        ;;
esac

# ── Main startup flow ─────────────────────────────────────────────────
hr
echo -e "${BOLD}Banking Portal Chatbot — Docker Startup${NC}"
hr

ensure_protegrity

hr
echo -e "${BOLD}Banking Portal Apps${NC}"

# Pre-create bind-mount directories and fix ownership if needed.
# On a fresh clone these don't exist; Docker would create them as root,
# but the container runs as uid 1000 (appuser) and needs write access.
for _bm_dir in "${SCRIPT_DIR}/TechnicalApp/chat_history_tech" \
               "${SCRIPT_DIR}/BusinessCustomerApp/chat_history"; do
    mkdir -p "${_bm_dir}" 2>/dev/null || true
    if [ ! -w "${_bm_dir}" ]; then
        info "Fixing permissions on ${_bm_dir} ..."
        sudo chown -R "$(id -u):$(id -g)" "${_bm_dir}" 2>/dev/null \
            || sudo chmod -R 777 "${_bm_dir}" 2>/dev/null \
            || warn "Could not fix permissions on ${_bm_dir} — chat history may fail."
    fi
done

info "Building images and starting containers ..."
${COMPOSE} up --build -d

# Brief wait then health check
echo ""
info "Waiting for apps to become healthy ..."
sleep 10

# Check TechnicalApp
if curl --connect-timeout 5 -sf -o /dev/null "http://localhost:5002/tech/login" 2>/dev/null; then
    ok "TechnicalApp is healthy     → http://localhost:5002/tech/login"
else
    warn "TechnicalApp is still starting → http://localhost:5002/tech/login"
fi

# Check BusinessApp
if curl --connect-timeout 5 -sf -o /dev/null "http://localhost:5003/bank/login" 2>/dev/null; then
    ok "BusinessCustomerApp is healthy → http://localhost:5003/bank/login"
else
    warn "BusinessCustomerApp is still starting → http://localhost:5003/bank/login"
fi

# ── Start ChromaDB Viewer (Streamlit) ─────────────────────────────────
start_chromadb_viewer

hr
echo ""
echo -e "  ${BOLD}TechnicalApp     ${NC} →  http://localhost:5002/tech/login"
echo -e "  ${BOLD}BusinessApp      ${NC} →  http://localhost:5003/bank/login"
echo -e "  ${BOLD}Kuzu Explorer    ${NC} →  http://localhost:8000"
echo -e "  ${BOLD}pgweb            ${NC} →  http://localhost:8081"
echo -e "  ${BOLD}ChromaDB Viewer  ${NC} →  http://localhost:8501"
echo ""
echo "  Logs:   ./start.sh --logs         (or: ${COMPOSE} logs -f)"
echo "  Status: ./start.sh --status"
echo "  Stop:   ./start.sh --stop"
echo ""
