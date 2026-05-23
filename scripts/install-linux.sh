#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

die() {
  echo "Error: $*" >&2
  exit 1
}

require_python310() {
  local python_bin="$1"
  local version
  version="$("$python_bin" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  [[ "$version" == "3.10" ]] || die "Python 3.10 is required, but $python_bin is $version"
}

has_project_conda_env() {
  [[ -n "${CONDA_PREFIX:-}" && -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV:-}" != "base" ]]
}

VENV_DIR="$PWD/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if has_project_conda_env; then
  CONDA_PYTHON="$CONDA_PREFIX/bin/python"
  [[ -x "$CONDA_PYTHON" ]] || die "active conda environment does not have an executable Python at $CONDA_PYTHON"
  require_python310 "$CONDA_PYTHON"
  "$CONDA_PYTHON" -m pip --version >/dev/null 2>&1 || die "active conda environment does not have pip; install pip in that environment and rerun"
  echo "Using active conda environment: $CONDA_PREFIX"
  "$CONDA_PYTHON" -m pip install -r requirements.txt
elif command -v uv >/dev/null 2>&1; then
  echo "Creating .venv with uv and Python 3.10"
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"
  uv venv --python 3.10 "$VENV_DIR"
  uv pip install --python "$VENV_PYTHON" -r requirements.txt
else
  PYTHON310="$(command -v python3.10 2>/dev/null)" || die "uv is not installed and python3.10 was not found; install uv, install python3.10, or activate a non-base Python 3.10 conda environment"
  require_python310 "$PYTHON310"
  echo "Creating .venv with $PYTHON310"
  "$PYTHON310" -m venv "$VENV_DIR"
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install -r requirements.txt
fi

mkdir -p data/config data/sprite data/speech data/models data/chat_history data/character_templates

echo "Install complete. Run ./scripts/start-linux.sh"
