#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# setup_protegrity.sh — Install Protegrity Developer Edition containers
#                       and the Python SDK if they are missing.
#
# Usage:
#   bash scripts/setup_protegrity.sh          # install everything
#   bash scripts/setup_protegrity.sh --check  # check status only
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLONE_BASE="${REPO_DIR}/.protegrity-install"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib_python.sh"

# Auto-create and activate venv if not already in one
VENV_DIR="${REPO_DIR}/.venv"
if [ -z "${VIRTUAL_ENV:-}" ]; then
    ensure_python_venv "$REPO_DIR" || exit 1
else
    if ! python_version_ok python3; then
        echo -e "\033[0;31m✖\033[0m Active venv uses unsupported Python: $(python3 --version 2>&1)"
        suggest_python_install
        exit 1
    fi
fi

# Resolve pip command
if command -v pip &>/dev/null; then
    PIP=pip
elif command -v pip3 &>/dev/null; then
    PIP=pip3
elif python3 -m pip --version &>/dev/null; then
    PIP="python3 -m pip"
else
    echo -e "\033[0;31m✖\033[0m pip is not available even inside the venv."
    exit 1
fi

# Install project requirements if not yet done
install_project_requirements "$REPO_DIR" || exit 1

EDITION_REPO="https://github.com/Protegrity-Developer-Edition/protegrity-developer-edition.git"
PYTHON_REPO="https://github.com/Protegrity-Developer-Edition/protegrity-developer-python.git"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()  { echo -e "${GREEN}✔${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✖${NC} $*"; }

# ── Checks ────────────────────────────────────────────────────────────

check_docker() {
    if ! command -v docker &>/dev/null; then
        error "Docker is not installed. Please install Docker first."
        echo "  → https://docs.docker.com/get-docker/"
        return 1
    fi
    if ! docker info &>/dev/null; then
        error "Docker daemon is not running. Please start Docker."
        return 1
    fi
    info "Docker is available"
}

resolve_compose() {
    if docker compose version &>/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        COMPOSE=(docker-compose)
    else
        error "Docker Compose is not installed."
        echo "  → https://docs.docker.com/compose/install/"
        return 1
    fi
}

check_docker_compose() {
    if ! resolve_compose && command -v apt-get &>/dev/null; then
        warn "Docker Compose v2 plugin not found — attempting install…"
        sudo apt-get update -qq 2>/dev/null || true
        sudo apt-get install -y docker-compose-plugin 2>/dev/null || true
        resolve_compose || true
    fi
    resolve_compose || return 1
    info "Docker Compose is available (${COMPOSE[*]})"
    if [[ "${COMPOSE[0]}" == "docker-compose" ]]; then
        warn "Using legacy docker-compose v1 — will apply a resolved compose override"
    fi
}

_nonempty_or() {
    local value="$1"
    local fallback="$2"
    if [[ -n "${value// /}" ]]; then
        printf '%s' "$value"
    else
        printf '%s' "$fallback"
    fi
}

prepare_protegrity_compose_env() {
    # Treat empty strings as unset — bash ${VAR:-default} keeps empty values.
    local registry pattern_tag context_tag classification_tag sgr_tag

    registry="$(_nonempty_or "${REGISTRY:-}" "ghcr.io/protegrity-ai-developer-edition")"
    pattern_tag="$(_nonempty_or "${PATTERN_TAG:-}" "2.0.0.320.59776828")"
    context_tag="$(_nonempty_or "${CONTEXT_TAG:-}" "2.0.0.242.5041932c")"
    classification_tag="$(_nonempty_or "${CLASSIFICATION_TAG:-}" "2.0.0.374.8047721c")"
    sgr_tag="$(_nonempty_or "${SEMANTIC_GUARDRAIL_TAG:-}" "1.1.1-36-1b3de114")"

    PROTEGRITY_REGISTRY="$registry"
    PROTEGRITY_PATTERN_IMAGE="$(_nonempty_or "${DOCKER_PATTERN_IMAGE:-}" "${registry}/pattern-provider:${pattern_tag}")"
    PROTEGRITY_CONTEXT_IMAGE="$(_nonempty_or "${DOCKER_CONTEXT_IMAGE:-}" "${registry}/context-provider:${context_tag}")"
    PROTEGRITY_CLASSIFICATION_IMAGE="$(_nonempty_or "${DOCKER_CLASSIFICATION_IMAGE:-}" "${registry}/classification-service:${classification_tag}")"
    PROTEGRITY_SEMANTIC_GUARDRAIL_IMAGE="$(_nonempty_or "${DOCKER_SEMANTIC_GUARDRAIL_IMAGE:-}" "${registry}/semantic-guardrail:${sgr_tag}")"
    PROTEGRITY_NETWORK_NAME="$(_nonempty_or "${DOCKER_NETWORK_NAME:-}" "protegrity-network")"
    PROTEGRITY_CLASSIFICATION_PORT="$(_nonempty_or "${CLASSIFICATION_PORT:-}" "8580")"
    PROTEGRITY_SGR_PORT="$(_nonempty_or "${SGR_PORT:-}" "8581")"

    export DOCKER_NETWORK_NAME="$PROTEGRITY_NETWORK_NAME"
    export REGISTRY="$registry"
    export CLASSIFICATION_PORT="$PROTEGRITY_CLASSIFICATION_PORT"
    export SGR_PORT="$PROTEGRITY_SGR_PORT"
    export DOCKER_PATTERN_IMAGE="$PROTEGRITY_PATTERN_IMAGE"
    export DOCKER_CONTEXT_IMAGE="$PROTEGRITY_CONTEXT_IMAGE"
    export DOCKER_CLASSIFICATION_IMAGE="$PROTEGRITY_CLASSIFICATION_IMAGE"
    export DOCKER_SEMANTIC_GUARDRAIL_IMAGE="$PROTEGRITY_SEMANTIC_GUARDRAIL_IMAGE"
}

write_standalone_compose_v1() {
    local dir=$1
    local standalone_file=$2
    local stack
    stack="$(basename "$dir")"

    case "$stack" in
        data-discovery)
            cat >"$standalone_file" <<EOF
version: '3.8'
networks:
  protegrity-network:
    name: ${PROTEGRITY_NETWORK_NAME}
services:
  pattern-provider-service:
    image: ${PROTEGRITY_PATTERN_IMAGE}
    container_name: pattern_provider
    networks:
      - protegrity-network
  context-provider-service:
    image: ${PROTEGRITY_CONTEXT_IMAGE}
    container_name: context_provider
    networks:
      - protegrity-network
  classification-service:
    image: ${PROTEGRITY_CLASSIFICATION_IMAGE}
    container_name: classification_service
    ports:
      - "${PROTEGRITY_CLASSIFICATION_PORT}:8050"
    depends_on:
      - pattern-provider-service
      - context-provider-service
    networks:
      - protegrity-network
    environment:
      - 'PROVIDERS=[{"name":"Pattern", "address":"http://pattern-provider-service:8051"}, {"name":"Context", "address":"http://context-provider-service:8052"}]'
EOF
            ;;
        semantic-guardrail)
            cat >"$standalone_file" <<EOF
version: '3.8'
networks:
  protegrity-network:
    name: ${PROTEGRITY_NETWORK_NAME}
services:
  semantic-guardrail-service:
    image: ${PROTEGRITY_SEMANTIC_GUARDRAIL_IMAGE}
    container_name: semantic_guardrail
    ports:
      - "${PROTEGRITY_SGR_PORT}:8001"
    networks:
      - protegrity-network
    environment:
      - LOG_LEVEL=WARNING
      - HF_HUB_OFFLINE=1
      - TRANSFORMERS_OFFLINE=1
EOF
            ;;
        *)
            return 1
            ;;
    esac
}

compose_up() {
    local dir=$1
    if [[ ! -f "${dir}/docker-compose.yml" && ! -f "${dir}/docker-compose.yaml" ]]; then
        error "No docker-compose file in ${dir}"
        return 1
    fi

    prepare_protegrity_compose_env

    if [[ "${COMPOSE[0]}" == "docker-compose" ]]; then
        local standalone_file
        standalone_file="$(mktemp "${TMPDIR:-/tmp}/protegrity-compose-standalone.XXXXXX.yml")"
        if ! write_standalone_compose_v1 "$dir" "$standalone_file"; then
            rm -f "$standalone_file"
            local compose_file="docker-compose.yml"
            [[ -f "${dir}/docker-compose.yml" ]] || compose_file="docker-compose.yaml"
            warn "Falling back to upstream compose file for ${dir}"
            if ! (cd "$dir" && "${COMPOSE[@]}" -f "$compose_file" up -d); then
                return 1
            fi
            return 0
        fi

        if ! (cd "$dir" && "${COMPOSE[@]}" -f "$standalone_file" up -d); then
            warn "Compose up failed — resolved images:"
            echo "       pattern:        ${PROTEGRITY_PATTERN_IMAGE}"
            echo "       context:        ${PROTEGRITY_CONTEXT_IMAGE}"
            echo "       classification: ${PROTEGRITY_CLASSIFICATION_IMAGE}"
            echo "       guardrail:      ${PROTEGRITY_SEMANTIC_GUARDRAIL_IMAGE}"
            (cd "$dir" && "${COMPOSE[@]}" -f "$standalone_file" config) || true
            rm -f "$standalone_file"
            return 1
        fi
        rm -f "$standalone_file"
        return 0
    fi

    (cd "$dir" && "${COMPOSE[@]}" up -d)
}

compose_up_edition_stack() {
    local edition_dir=$1

    if [[ -f "${edition_dir}/docker-compose.yml" || -f "${edition_dir}/docker-compose.yaml" ]]; then
        info "Starting Protegrity stack (legacy root compose)…"
        compose_up "$edition_dir"
        return
    fi

    local data_discovery="${edition_dir}/data-discovery"
    local semantic_guardrail="${edition_dir}/semantic-guardrail"

    if [[ ! -d "$data_discovery" || ! -d "$semantic_guardrail" ]]; then
        error "Unexpected protegrity-developer-edition layout under ${edition_dir}"
        echo "  Expected data-discovery/ and semantic-guardrail/ compose directories."
        return 1
    fi

    info "Starting classification stack (data-discovery)…"
    compose_up "$data_discovery"
    info "Starting semantic guardrail stack…"
    compose_up "$semantic_guardrail"
}

check_containers() {
    local running
    running=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -c 'classification_service\|semantic_guardrail\|pattern_provider\|context_provider' || true)
    if [ "$running" -ge 4 ]; then
        info "Protegrity containers are running ($running/4 services)"
        return 0
    else
        warn "Protegrity containers are NOT running ($running/4 services detected)"
        return 1
    fi
}

check_python_sdk() {
    if python3 -c "import protegrity_developer_python" &>/dev/null; then
        local ver
        ver=$($PIP show protegrity-developer-python 2>/dev/null | grep '^Version:' | awk '{print $2}')
        # Verify the SDK has find_and_unprotect (missing in v0.9.0rc6 from PyPI)
        if python3 -c "import protegrity_developer_python; assert hasattr(protegrity_developer_python, 'find_and_unprotect')" 2>/dev/null; then
            info "protegrity-developer-python SDK is installed (v${ver:-unknown})"
            return 0
        else
            warn "protegrity-developer-python v${ver:-unknown} is incomplete (missing find_and_unprotect) — needs upgrade from source"
            return 1
        fi
    else
        warn "protegrity-developer-python SDK is NOT installed"
        return 1
    fi
}

# ── Install functions ─────────────────────────────────────────────────

install_docker() {
    echo ""
    echo "━━━ Installing Docker & Docker Compose ━━━"

    if ! command -v curl &>/dev/null; then
        sudo apt-get update -qq 2>/dev/null
        sudo apt-get install -y curl 2>/dev/null
    fi

    echo "Installing Docker via get.docker.com …"
    curl -fsSL https://get.docker.com | sudo sh

    # Add current user to docker group so sudo is not needed
    sudo usermod -aG docker "$USER"

    # Activate the new group in current shell (avoids logout/login)
    if command -v newgrp &>/dev/null; then
        echo "Activating docker group …"
        sg docker -c "docker info" &>/dev/null || true
    fi

    # Verify installation
    if docker --version &>/dev/null; then
        info "Docker installed: $(docker --version)"
    else
        error "Docker installation failed"
        return 1
    fi

    if ! resolve_compose && command -v apt-get &>/dev/null; then
        echo "Installing Docker Compose plugin (v2)…"
        sudo apt-get update -qq 2>/dev/null || true
        sudo apt-get install -y docker-compose-plugin 2>/dev/null || true
    fi
    if resolve_compose; then
        info "Docker Compose installed: $(docker compose version 2>/dev/null || docker-compose --version)"
    else
        error "Docker Compose not available after Docker install"
        return 1
    fi
}

install_containers() {
    echo ""
    echo "━━━ Installing Protegrity Developer Edition containers ━━━"
    mkdir -p "$CLONE_BASE"
    local edition_dir="$CLONE_BASE/protegrity-developer-edition"

    if [ -d "$edition_dir/.git" ]; then
        info "Repository already cloned — pulling latest…"
        git -C "$edition_dir" pull --quiet
    else
        echo "Cloning $EDITION_REPO …"
        git clone --quiet "$EDITION_REPO" "$edition_dir"
    fi

    echo "Starting containers with docker compose (this may take a while on first run)…"
    compose_up_edition_stack "$edition_dir"

    echo ""
    # Wait briefly for containers to start
    echo "Waiting for containers to start…"
    sleep 10
    if check_containers; then
        info "Protegrity containers started successfully"
    else
        warn "Containers may still be starting — check with: docker ps"
    fi
}

install_python_sdk() {
    echo ""
    echo "━━━ Installing Protegrity Python SDK ━━━"
    echo "Installing from PyPI: $PIP install protegrity-developer-python …"

    if $PIP install protegrity-developer-python 2>/dev/null; then
        # Check if we got the full SDK (v1.1.0+) or a limited fallback version
        if python3 -c "import protegrity_developer_python; assert hasattr(protegrity_developer_python, 'find_and_unprotect')" 2>/dev/null; then
            info "protegrity-developer-python installed from PyPI (full SDK)"
            return 0
        else
            warn "PyPI installed a limited SDK version — upgrading from source…"
        fi
    else
        warn "PyPI install failed — building from source…"
    fi

    # Build from source with relaxed Python version requirement
    mkdir -p "$CLONE_BASE"
    local python_dir="$CLONE_BASE/protegrity-developer-python"

    if [ -d "$python_dir/.git" ]; then
        info "Repository already cloned — pulling latest…"
        git -C "$python_dir" pull --quiet
    else
        echo "Cloning $PYTHON_REPO …"
        git clone --quiet "$PYTHON_REPO" "$python_dir"
    fi

    cd "$python_dir"

    $PIP install -r requirements.txt 2>/dev/null || true
    $PIP install . --no-deps --force-reinstall
    cd "$REPO_DIR"

    if python3 -c "import protegrity_developer_python; assert hasattr(protegrity_developer_python, 'find_and_unprotect')" 2>/dev/null; then
        info "Python SDK installed successfully from source (full SDK)"
    elif check_python_sdk; then
        warn "Python SDK installed but find_and_unprotect not available"
    else
        error "Python SDK installation failed"
        return 1
    fi
}

# ── Main ──────────────────────────────────────────────────────────────

main() {
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║   Protegrity Developer Edition — Setup                  ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""

    local check_only=false
    if [[ "${1:-}" == "--check" ]]; then
        check_only=true
    fi

    # Status checks
    local containers_ok=true sdk_ok=true docker_ok=true

    check_docker      || docker_ok=false
    check_docker_compose || docker_ok=false
    check_containers  || containers_ok=false
    check_python_sdk  || sdk_ok=false

    echo ""

    if $containers_ok && $sdk_ok; then
        info "Everything is installed and running ✓"
        return 0
    fi

    if $check_only; then
        echo ""
        echo "Run without --check to install missing components."
        return 1
    fi

    # Install missing components
    if ! $containers_ok; then
        if ! $docker_ok; then
            install_docker
            docker_ok=true
        fi
        install_containers
    fi

    if ! $sdk_ok; then
        install_python_sdk
    fi

    echo ""
    echo "━━━ Summary ━━━"
    check_containers || true
    check_python_sdk || true
    echo ""
    info "Setup complete. You can verify with: bash scripts/setup_protegrity.sh --check"
}

main "$@"
