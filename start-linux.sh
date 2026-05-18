#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

load_dotenv() {
  local env_file="$1"
  local line key value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue

    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi

    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    export "$key=$value"
  done < "$env_file"
}

if [[ -f .env.local ]]; then
  load_dotenv .env.local
fi

export QT_API="${QT_API:-pyside6}"
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}"

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

VENV_PYTHON="$PWD/.venv/bin/python"

if has_project_conda_env; then
  PYTHON="$CONDA_PREFIX/bin/python"
  [[ -x "$PYTHON" ]] || die "active conda environment does not have an executable Python at $PYTHON"
elif [[ -x "$VENV_PYTHON" ]]; then
  PYTHON="$VENV_PYTHON"
elif PYTHON310="$(command -v python3.10 2>/dev/null)"; then
  PYTHON="$PYTHON310"
else
  die "no supported Python found; activate a non-base Python 3.10 conda environment, run ./install-linux.sh to create .venv, or install python3.10"
fi

require_python310 "$PYTHON"

mkdir -p data/config data/sprite data/speech data/models data/chat_history data/character_templates

exec "$PYTHON" webui_qt.py
