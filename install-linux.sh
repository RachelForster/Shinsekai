#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/.uv-cache}"
  uv venv --python 3.10 .venv
  uv pip install -r requirements.txt
else
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

mkdir -p data/config data/sprite data/speech data/models data/chat_history data/character_templates

echo "Install complete. Run ./start-linux.sh"
