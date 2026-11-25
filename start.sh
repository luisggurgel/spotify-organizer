#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="127.0.0.1"
PORT="${PORT:-8000}"
URL="http://${HOST}:${PORT}"
RELOAD_FLAG=()

if [[ "${1:-}" == "--dev" ]]; then
  RELOAD_FLAG=("--reload")
fi

if [[ ! -d ".venv" || ! -f ".env" ]]; then
  ./install.sh "${1:-}"
fi

VENV_PYTHON=".venv/bin/python"
if [[ ! -x "$VENV_PYTHON" && -x ".venv/Scripts/python.exe" ]]; then
  VENV_PYTHON=".venv/Scripts/python.exe"
fi

MISSING=$("$VENV_PYTHON" - <<'PY'
from pathlib import Path

values = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    values[k.strip()] = v.strip()

print(",".join(k for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET") if not values.get(k)))
PY
)

if [[ -n "$MISSING" ]]; then
  ./install.sh
fi

open_browser() {
  sleep 1.5
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  elif command -v wslview >/dev/null 2>&1; then
    wslview "$URL" >/dev/null 2>&1 || true
  fi
}

echo "Starting Spotify Language Organizer at ${URL}"
echo "Press Ctrl+C to stop."

open_browser &
exec "$VENV_PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" "${RELOAD_FLAG[@]}"
