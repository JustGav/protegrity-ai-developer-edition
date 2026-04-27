#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# scripts/start_apps.sh — Local (non-Docker) launcher for both apps
#
# Runs TechnicalApp (port 5002) and BusinessCustomerApp (port 5003)
# directly with Python in the background.
#
# For Docker-based startup (recommended), use: ./start.sh
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✖${NC}  $*" >&2; exit 1; }

# Cross-platform port killer (macOS + Linux)
kill_port() {
    local port="$1"
    if command -v lsof &>/dev/null; then
        local pids
        pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill -9 2>/dev/null || true
            warn "Killed existing process on port $port"
        fi
    elif command -v fuser &>/dev/null; then
        fuser -k "${port}/tcp" 2>/dev/null || true
    fi
}

# ── Stop existing instances ────────────────────────────────────────────
echo "=== Stopping any existing app processes ==="
kill_port 5002
kill_port 5003
kill_port 8501
sleep 1

# ── Start TechnicalApp ─────────────────────────────────────────────────
echo ""
echo "=== Starting TechnicalApp on port 5002 ==="
python TechnicalApp/run.py &
TECH_PID=$!
ok "TechnicalApp PID: $TECH_PID"

# ── Start BusinessCustomerApp ──────────────────────────────────────────
echo ""
echo "=== Starting BusinessCustomerApp on port 5003 ==="
python BusinessCustomerApp/run.py &
BIZ_PID=$!
ok "BusinessCustomerApp PID: $BIZ_PID"

# ── Ensure streamlit is available (auto-install into .chromadb-venv) ────
ensure_streamlit() {
    command -v streamlit &>/dev/null && return 0
    local venv="${REPO_DIR}/.chromadb-venv"
    if [ -x "${venv}/bin/streamlit" ]; then
        export PATH="${venv}/bin:${PATH}"
        return 0
    fi
    warn "streamlit not found — installing into ${venv} ..."
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

# ── Start ChromaDB Viewer ──────────────────────────────────────────────
echo ""
echo "=== Starting ChromaDB Viewer on port 8501 ==="

# Ensure streamlit + chromadb are available BEFORE trying to rebuild
if ensure_streamlit; then
    # Auto-build the ChromaDB index if it doesn't exist yet (fresh clone)
    if [ ! -d "${REPO_DIR}/chroma_db" ]; then
        warn "chroma_db/ not found — building index from knowledge base ..."
        python3 scripts/browse_chromadb.py rebuild 2>&1 || warn "ChromaDB rebuild failed."
    fi

    streamlit run scripts/chromadb_viewer.py \
        --server.headless true \
        --server.port 8501 \
        2>"${REPO_DIR}/chromadb_viewer.log" &
    CHROMA_PID=$!
    ok "ChromaDB Viewer PID: $CHROMA_PID"
else
    warn "ChromaDB Viewer not started (streamlit unavailable)."
    CHROMA_PID=""
fi

# Brief startup wait
sleep 4

# ── Health checks ─────────────────────────────────────────────────────
echo ""
echo "=== Status ==="
curl -s -o /dev/null -w "TechnicalApp     :5002 → HTTP %{http_code}\n" \
    http://localhost:5002/tech/login 2>/dev/null \
    || warn "TechnicalApp not yet responding on :5002"

curl -s -o /dev/null -w "BusinessApp      :5003 → HTTP %{http_code}\n" \
    http://localhost:5003/bank/login 2>/dev/null \
    || warn "BusinessApp not yet responding on :5003"

if [ -n "${CHROMA_PID:-}" ]; then
    sleep 2
    if lsof -i tcp:8501 -sTCP:LISTEN &>/dev/null 2>&1; then
        ok "ChromaDB Viewer  :8501 → http://localhost:8501"
    else
        warn "ChromaDB Viewer not yet responding on :8501 — check chromadb_viewer.log"
    fi
fi

echo ""
echo "PIDs: TechnicalApp=$TECH_PID  BusinessApp=$BIZ_PID${CHROMA_PID:+  ChromaDB=$CHROMA_PID}"
echo "To stop: kill $TECH_PID $BIZ_PID${CHROMA_PID:+ $CHROMA_PID}"
echo "         (or run this script again to replace all)"

