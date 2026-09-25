#!/bin/bash
# One-click launcher: sets up the Python environment on first run, imports
# API keys from the old Concordia builder, starts the server (backend + web
# UI in one process) and opens the browser. Close this window to stop.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
URL="http://127.0.0.1:$PORT"

find_uv() { command -v uv 2>/dev/null || { [ -x "$HOME/.local/bin/uv" ] && echo "$HOME/.local/bin/uv"; } || true; }
find_python() {
  for p in python3.13 python3.12 python3.11 python3.10 "$HOME/.local/bin/python3.13"; do
    if command -v "$p" >/dev/null 2>&1; then echo "$p"; return; fi
  done
}

REQ_HASH=$(shasum requirements.txt | cut -d' ' -f1)
if [ ! -x venv/bin/python ] || [ "$(cat venv/.req_hash 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "Preparing the Python environment (first run takes 1-2 minutes)..."
  UV=$(find_uv)
  if [ -n "$UV" ]; then
    [ -x venv/bin/python ] || "$UV" venv --python 3.13 venv
    "$UV" pip install --python venv/bin/python -r requirements.txt
  else
    PY=$(find_python)
    if [ -z "$PY" ]; then echo "Python 3.10+ not found. Install Python 3.13 from python.org, then double-click again."; read -r; exit 1; fi
    [ -x venv/bin/python ] || "$PY" -m venv venv
    venv/bin/pip install -q -r requirements.txt
  fi
  echo "$REQ_HASH" > venv/.req_hash
fi

venv/bin/python scripts/import_keys.py

if curl -fs "$URL/api/health" >/dev/null 2>&1; then
  echo "Already running. Opening the browser: $URL"
  [ -n "$NO_BROWSER" ] || open "$URL" 2>/dev/null || true
  exit 0
fi

venv/bin/python -m uvicorn naming_game.api:app --host 127.0.0.1 --port "$PORT" --log-level warning &
PID=$!
trap 'kill $PID 2>/dev/null; exit 0' EXIT INT TERM
for _ in $(seq 1 80); do
  curl -fs "$URL/api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
[ -n "$NO_BROWSER" ] || open "$URL" 2>/dev/null || xdg-open "$URL" 2>/dev/null || true
echo ""
echo "Naming Game Simulator is running at $URL"
echo "   Close this window (or press Ctrl+C) to stop it."
wait $PID
