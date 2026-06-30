#!/usr/bin/env bash
# Shared Python/venv helpers — orchestration deps require Python 3.10–3.13.
# (CrewAI, LangGraph, etc. do not support 3.14+ yet.)

# shellcheck disable=SC2034
PYTHON_MIN=10
PYTHON_MAX_EXCLUSIVE=14

python_version_ok() {
  local py="$1"
  "$py" -c "
import sys
v = sys.version_info
ok = (3, ${PYTHON_MIN}) <= (v.major, v.minor) < (3, ${PYTHON_MAX_EXCLUSIVE})
sys.exit(0 if ok else 1)
" 2>/dev/null
}

python_version_string() {
  local py="$1"
  "$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null \
    || echo "unknown"
}

find_compatible_python() {
  local candidates=()
  if [[ -n "${PYTHON:-}" ]] && python_version_ok "$PYTHON"; then
    candidates+=("$PYTHON")
  fi
  local minor
  for minor in 12 11 10 13; do
    candidates+=("python3.${minor}")
  done
  candidates+=("python3")

  local seen="" py
  for py in "${candidates[@]}"; do
  [[ " $seen " == *" $py "* ]] && continue
    seen="$seen $py"
    if command -v "$py" &>/dev/null && python_version_ok "$py"; then
      echo "$py"
      return 0
    fi
  done
  return 1
}

suggest_python_install() {
  cat <<'EOF'
This project requires Python 3.10, 3.11, 3.12, or 3.13 (not 3.14+).

On Ubuntu/Debian:
  sudo apt-get update
  sudo apt-get install -y python3.12 python3.12-venv

Then re-run:
  bash scripts/start_system.sh

Or point at a specific interpreter:
  PYTHON=python3.12 bash scripts/start_system.sh
EOF
}

venv_python_ok() {
  local venv_dir="$1"
  [[ -x "${venv_dir}/bin/python" ]] || return 1
  python_version_ok "${venv_dir}/bin/python"
}

ensure_python_venv() {
  local repo_dir="$1"
  local venv_dir="${repo_dir}/.venv"
  local py

  if ! py=$(find_compatible_python); then
    echo -e "\033[0;31m✖\033[0m No compatible Python (3.10–3.13) found on PATH."
    suggest_python_install
    return 1
  fi

  local py_ver
  py_ver=$(python_version_string "$py")
  echo "Using Python ${py_ver} (${py})"

  if [[ -d "$venv_dir" ]] && ! venv_python_ok "$venv_dir"; then
    local bad_ver
    bad_ver=$(python_version_string "${venv_dir}/bin/python" 2>/dev/null || echo "invalid")
    echo -e "\033[1;33m⚠\033[0m Removing incompatible .venv (Python ${bad_ver}; need 3.10–3.13)"
    rm -rf "$venv_dir"
  fi

  if [[ ! -f "${venv_dir}/bin/activate" ]]; then
    echo "Creating virtual environment at ${venv_dir} …"
    if ! "$py" -m venv "$venv_dir" 2>/dev/null; then
      local minor="${py#python3.}"
      minor="${minor#python}"
      echo "python3-venv not found for ${py} — trying to install …"
      if command -v sudo &>/dev/null; then
        sudo apt-get update -qq 2>/dev/null || true
        sudo apt-get install -y "python${minor}-venv" 2>/dev/null \
          || sudo apt-get install -y python3-venv 2>/dev/null \
          || true
      fi
      rm -rf "$venv_dir"
      if ! "$py" -m venv "$venv_dir"; then
        echo -e "\033[0;31m✖\033[0m Failed to create venv with ${py}"
        suggest_python_install
        return 1
      fi
    fi
  fi

  if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "Activating virtual environment …"
    # shellcheck disable=SC1091
    source "${venv_dir}/bin/activate"
  fi

  return 0
}

resolve_pip() {
  if command -v pip &>/dev/null; then
    echo pip
  elif command -v pip3 &>/dev/null; then
    echo pip3
  else
    echo "python3 -m pip"
  fi
}

install_project_requirements() {
  local repo_dir="$1"
  local req="${repo_dir}/config/requirements.txt"
  [[ -f "$req" ]] || return 0

  if python3 -c "import flask" &>/dev/null; then
    return 0
  fi

  local pip
  pip=$(resolve_pip)
  echo "Installing project requirements …"
  if ! $pip install -r "$req"; then
    echo -e "\033[0;31m✖\033[0m pip install failed."
    echo "Current interpreter: $(python3 --version 2>&1)"
    suggest_python_install
    return 1
  fi
}
