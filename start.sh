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
  echo "正在准备 Python 环境（首次约 1–2 分钟）…"
  UV=$(find_uv)
  if [ -n "$UV" ]; then
    [ -x venv/bin/python ] || "$UV" venv --python 3.13 venv
    "$UV" pip install --python venv/bin/python -r requirements.txt
  else
    PY=$(find_python)
    if [ -z "$PY" ]; then echo "找不到 Python 3.10+。请先安装 Python 3.13（python.org）后再双击。"; read -r; exit 1; fi
    [ -x venv/bin/python ] || "$PY" -m venv venv
    venv/bin/pip install -q -r requirements.txt
  fi
  echo "$REQ_HASH" > venv/.req_hash
fi

venv/bin/python scripts/import_keys.py

if curl -fs "$URL/api/health" >/dev/null 2>&1; then
  echo "程序已经在运行，直接打开浏览器：$URL"
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
echo "✅ 命名博弈模拟器已启动：$URL"
echo "   关闭这个窗口（或按 Ctrl+C）即可停止程序。"
wait $PID
