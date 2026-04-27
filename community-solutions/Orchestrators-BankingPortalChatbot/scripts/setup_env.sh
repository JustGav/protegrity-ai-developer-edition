#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# scripts/setup_env.sh — Build the Python environment for Banking Portal
#
# Creates a reproducible Python environment from config/requirements.txt
# and bootstraps a .env file if one does not yet exist.
#
# Supports two environment managers:
#   venv  (default) — creates .venv/ inside the project root
#   conda           — creates or reuses a named conda environment
#
# Usage:
#   bash scripts/setup_env.sh                        # venv at .venv/
#   bash scripts/setup_env.sh --venv                 # same as above
#   bash scripts/setup_env.sh --venv /path/to/env    # venv at custom path
#   bash scripts/setup_env.sh --conda banking-portal # conda env by name
#   bash scripts/setup_env.sh --python /usr/bin/python3.12  # custom interpreter
#   bash scripts/setup_env.sh --check                # validate existing env only
#
# Requirements:
#   Python >= 3.12.11 (required by protegrity-developer-python >= 1.1.0)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIREMENTS="${REPO_DIR}/config/requirements.txt"
ENV_EXAMPLE="${REPO_DIR}/.env.example"
ENV_FILE="${REPO_DIR}/.env"

# ── Defaults ──────────────────────────────────────────────────────────
MODE="venv"
VENV_DIR="${REPO_DIR}/.venv"
CONDA_ENV="banking-portal"
PYTHON_BIN=""
CHECK_ONLY=false

# ── Colours ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✔${NC}  $*"; }
info() { echo -e "${BLUE}→${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "${RED}✖${NC}  $*" >&2; exit 1; }
hr()   { echo -e "${BOLD}──────────────────────────────────────────────────────${NC}"; }

# ── Argument parsing ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --venv)
            MODE="venv"
            if [[ "${2:-}" && "${2:-}" != --* ]]; then
                VENV_DIR="$2"; shift
            fi
            shift ;;
        --conda)
            MODE="conda"
            if [[ "${2:-}" && "${2:-}" != --* ]]; then
                CONDA_ENV="$2"; shift
            fi
            shift ;;
        --python)
            PYTHON_BIN="${2:?--python requires a path argument}"
            shift 2 ;;
        --check)
            CHECK_ONLY=true
            shift ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *)
            fail "Unknown argument: $1  (run with --help for usage)" ;;
    esac
done

# ── Locate a suitable Python interpreter ─────────────────────────────
find_python() {
    if [[ -n "$PYTHON_BIN" ]]; then
        command -v "$PYTHON_BIN" 2>/dev/null || fail "Python binary not found: $PYTHON_BIN"
        echo "$PYTHON_BIN"; return
    fi
    # Prefer explicit version binaries first
    for candidate in python3.13 python3.12 python3 python; do
        if command -v "$candidate" &>/dev/null; then
            echo "$candidate"; return
        fi
    done
    fail "No Python interpreter found. Install Python 3.12+ and retry."
}

# ── Version guard (requires >= 3.12.11 for Protegrity SDK v1.1) ──────
check_python_version() {
    local py="$1"
    local ver
    ver=$("$py" -c "import sys; print('{}.{}.{}'.format(*sys.version_info[:3]))")
    local major minor patch
    IFS='.' read -r major minor patch <<< "$ver"
    patch="${patch:-0}"
    if (( major < 3 || (major == 3 && minor < 12) || (major == 3 && minor == 12 && patch < 11) )); then
        warn "Python $ver detected. protegrity-developer-python >= 1.1.0 requires Python >= 3.12.11."

        local os_type
        os_type=$(uname -s)

        if [[ "$os_type" == "Darwin" ]]; then
            # ── macOS: use Homebrew ──────────────────────────────────
            if command -v brew &>/dev/null; then
                info "Attempting to install Python 3.13 via Homebrew …"
                if brew install python@3.13 2>/dev/null; then
                    local brew_py=""
                    if command -v python3.13 &>/dev/null; then
                        brew_py="python3.13"
                    else
                        brew_py="$(brew --prefix python@3.13)/bin/python3.13"
                    fi
                    if [[ -x "$(command -v $brew_py)" ]]; then
                        local new_ver_mac
                        new_ver_mac=$($brew_py -c "import sys; print('{}.{}.{}'.format(*sys.version_info[:3]))" 2>/dev/null || echo "0.0.0")
                        ok "Python $new_ver_mac installed successfully."
                        PYTHON_BIN="$brew_py"
                        return 0
                    fi
                fi
            fi
            echo ""
            echo "  Could not auto-install a compatible Python."
            echo "  Install Python 3.13 via Homebrew:"
            echo "    brew install python@3.13"
            echo "  Or download from https://www.python.org/downloads/"
            echo ""
            echo "    # Then re-run:"
            echo "    bash scripts/setup_env.sh --python python3.13"
            echo ""
            fail "Python >= 3.12.11 is required."
        fi

        # ── Linux: try deadsnakes PPA (Ubuntu/Debian) ───────────────
        if command -v apt-get &>/dev/null; then
            sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
            sudo apt-get update -qq 2>/dev/null || true

            # Try Python 3.13 first (deadsnakes doesn't ship newer 3.12.x on noble)
            info "Attempting to install Python 3.13 via deadsnakes PPA …"
            if sudo apt-get install -y python3.13 python3.13-venv python3.13-dev 2>/dev/null; then
                local new_ver13
                new_ver13=$(python3.13 -c "import sys; print('{}.{}.{}'.format(*sys.version_info[:3]))" 2>/dev/null || echo "0.0.0")
                ok "Python $new_ver13 installed successfully."
                PYTHON_BIN="python3.13"
                return 0
            fi

            # Fall back to Python 3.12 (may work on older Ubuntu releases)
            info "Attempting to install Python 3.12 via deadsnakes PPA …"
            if sudo apt-get install -y python3.12 python3.12-venv python3.12-dev 2>/dev/null; then
                local new_ver
                new_ver=$(python3.12 -c "import sys; print('{}.{}.{}'.format(*sys.version_info[:3]))" 2>/dev/null || echo "0.0.0")
                local nma nmi npa
                IFS='.' read -r nma nmi npa <<< "$new_ver"
                npa="${npa:-0}"
                if (( nma >= 3 && nmi >= 12 && npa >= 11 )); then
                    ok "Python $new_ver installed successfully."
                    PYTHON_BIN="python3.12"
                    return 0
                fi
            fi
        fi

        echo ""
        echo "  Could not auto-install a compatible Python."
        echo "  Install Python 3.13 (recommended) or Python 3.12.11+ manually:"
        echo ""
        echo "    # Ubuntu / Debian (deadsnakes PPA)"
        echo "    sudo add-apt-repository ppa:deadsnakes/ppa"
        echo "    sudo apt-get update && sudo apt-get install -y python3.13 python3.13-venv"
        echo ""
        echo "    # Then re-run:"
        echo "    bash scripts/setup_env.sh --python python3.13"
        echo ""
        fail "Python >= 3.12.11 is required."
    fi
    ok "Python $ver — version requirement satisfied."
}

# ── Validate that all requirements are importable ────────────────────
validate_imports() {
    local py="$1"
    info "Validating package imports …"
    local failed=()
    # Validate core importable modules (bash 3.2-compatible — no associative arrays)
    local dist_mod_pairs=(
        "flask:flask" "jinja2:jinja2" "python-dotenv:dotenv"
        "requests:requests" "openai:openai" "kuzu:kuzu" "chromadb:chromadb"
        "psycopg2-binary:psycopg2" "langgraph:langgraph" "langchain-core:langchain_core"
        "crewai:crewai" "llama-index-core:llama_index.core"
        "llama-index-llms-openai:llama_index.llms.openai"
        "llama-index-llms-anthropic:llama_index.llms.anthropic"
        "anthropic:anthropic" "groq:groq" "pytest:pytest" "faker:faker"
        "streamlit:streamlit" "protegrity-developer-python:protegrity_developer_python"
    )
    for pair in "${dist_mod_pairs[@]}"; do
        local dist="${pair%%:*}"
        local mod="${pair#*:}"
        if ! "$py" -c "import ${mod}" &>/dev/null 2>&1; then
            failed+=("$dist (import: ${mod})")
        fi
    done
    if [[ ${#failed[@]} -gt 0 ]]; then
        warn "The following packages failed to import:"
        for f in "${failed[@]}"; do echo "    - $f"; done
        return 1
    fi
    ok "All packages import successfully."
}

# ══════════════════════════════════════════════════════════════════════
# CHECK-ONLY mode
# ══════════════════════════════════════════════════════════════════════
if $CHECK_ONLY; then
    hr
    echo -e "${BOLD}  Environment Check${NC}"
    hr
    PY=$(find_python)
    check_python_version "$PY"
    validate_imports "$PY" && exit 0 || exit 1
fi

# ══════════════════════════════════════════════════════════════════════
# VENV mode
# ══════════════════════════════════════════════════════════════════════
setup_venv() {
    hr
    echo -e "${BOLD}  Banking Portal — Python venv Setup${NC}"
    hr

    local py
    py=$(find_python)
    check_python_version "$py"

    # ── Create venv ───────────────────────────────────────────────────
    if [[ -d "$VENV_DIR" && -f "$VENV_DIR/bin/activate" ]]; then
        warn "venv already exists at ${VENV_DIR} — reusing it."
        warn "Delete and rerun to start fresh:  rm -rf ${VENV_DIR}"
    else
        info "Creating venv at ${VENV_DIR} …"
        "$py" -m venv "$VENV_DIR" || {
            local pyver
            pyver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            warn "venv creation failed. Attempting to install python${pyver}-venv …"
            if [[ "$(uname -s)" == "Darwin" ]]; then
                fail "venv module missing. Reinstall Python via Homebrew: brew install python@${pyver}"
            fi
            # On Debian/Ubuntu, python3-venv may need to be installed separately
            sudo apt-get install -y "python${pyver}-venv" 2>/dev/null \
                || sudo apt-get install -y python3-venv 2>/dev/null \
                || fail "Could not install python3-venv. Please install it manually."
            "$py" -m venv "$VENV_DIR"
        }
        ok "venv created."
    fi

    # ── Activate ──────────────────────────────────────────────────────
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    local venv_py="$VENV_DIR/bin/python"

    # ── Upgrade pip ───────────────────────────────────────────────────
    info "Upgrading pip …"
    "$venv_py" -m pip install --upgrade pip --quiet
    ok "pip upgraded."

    # ── Install requirements ──────────────────────────────────────────
    [[ -f "$REQUIREMENTS" ]] || fail "Requirements file not found: $REQUIREMENTS"
    info "Installing packages from config/requirements.txt …"
    "$venv_py" -m pip install -r "$REQUIREMENTS"
    ok "All packages installed."

    # ── Bootstrap .env ────────────────────────────────────────────────
    setup_env_file

    # ── Validate ──────────────────────────────────────────────────────
    validate_imports "$venv_py"

    hr
    ok "Environment ready.  Activate with:"
    echo ""
    echo "    source ${VENV_DIR}/bin/activate"
    echo ""
    echo "  Then start the apps:"
    echo "    bash scripts/start_apps.sh"
    hr
}

# ══════════════════════════════════════════════════════════════════════
# CONDA mode
# ══════════════════════════════════════════════════════════════════════
setup_conda() {
    hr
    echo -e "${BOLD}  Banking Portal — Conda Environment Setup${NC}"
    hr

    # ── Verify conda is available ─────────────────────────────────────
    if ! command -v conda &>/dev/null; then
        fail "conda not found. Install Miniconda or Anaconda, or use --venv instead."
    fi

    # ── Determine Python binary to use for version check ─────────────
    local py
    if [[ -n "$PYTHON_BIN" ]]; then
        py="$PYTHON_BIN"
    else
        # Try to find a 3.12+ system Python for the version check
        for candidate in python3.13 python3.12 python3 python; do
            if command -v "$candidate" &>/dev/null; then py="$candidate"; break; fi
        done
        py="${py:-python3}"
    fi

    # ── Resolve requested Python version ─────────────────────────────
    local req_py_ver
    if [[ -n "$PYTHON_BIN" ]]; then
        req_py_ver=$("$PYTHON_BIN" -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))")
    else
        req_py_ver="3.13"  # default for new envs
    fi

    # ── Create or reuse conda env ─────────────────────────────────────
    if conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV"; then
        warn "Conda environment '${CONDA_ENV}' already exists — reusing it."
        warn "Remove and rerun to start fresh:  conda env remove -n ${CONDA_ENV}"
    else
        info "Creating conda environment '${CONDA_ENV}' with Python ${req_py_ver} …"
        conda create -y -n "$CONDA_ENV" "python=${req_py_ver}"
        ok "Conda environment created."
    fi

    # ── Resolve env's Python binary ───────────────────────────────────
    local conda_prefix
    conda_prefix=$(conda env list | awk -v env="$CONDA_ENV" '$1==env{print $NF}')
    local conda_py="${conda_prefix}/bin/python"
    [[ -x "$conda_py" ]] || fail "Could not locate Python in conda env: ${conda_prefix}"

    check_python_version "$conda_py"

    # ── Upgrade pip ───────────────────────────────────────────────────
    info "Upgrading pip …"
    "$conda_py" -m pip install --upgrade pip --quiet
    ok "pip upgraded."

    # ── Install requirements ──────────────────────────────────────────
    [[ -f "$REQUIREMENTS" ]] || fail "Requirements file not found: $REQUIREMENTS"
    info "Installing packages from config/requirements.txt …"
    "$conda_py" -m pip install -r "$REQUIREMENTS"
    ok "All packages installed."

    # ── Bootstrap .env ────────────────────────────────────────────────
    setup_env_file

    # ── Validate ──────────────────────────────────────────────────────
    validate_imports "$conda_py"

    hr
    ok "Environment ready.  Activate with:"
    echo ""
    echo "    conda activate ${CONDA_ENV}"
    echo ""
    echo "  Then start the apps:"
    echo "    bash scripts/start_apps.sh"
    hr
}

# ══════════════════════════════════════════════════════════════════════
# .env bootstrap helper
# ══════════════════════════════════════════════════════════════════════
setup_env_file() {
    if [[ -f "$ENV_FILE" ]]; then
        ok ".env already exists — leaving it unchanged."
    elif [[ -f "$ENV_EXAMPLE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        warn ".env created from .env.example — remember to fill in your API keys:"
        echo "    ${ENV_FILE}"
    else
        warn ".env.example not found — skipping .env creation."
    fi
}

# ══════════════════════════════════════════════════════════════════════
# Dispatch
# ══════════════════════════════════════════════════════════════════════
case "$MODE" in
    venv)  setup_venv ;;
    conda) setup_conda ;;
esac
