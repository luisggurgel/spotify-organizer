#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

DEV_MODE=false
if [[ "${1:-}" == "--dev" ]]; then
  DEV_MODE=true
fi

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Error: Python 3.11 or newer was not found on PATH." >&2
  exit 1
fi

echo "Using $("$PYTHON_BIN" --version)"

if [[ ! -d ".venv" ]]; then
  echo "Creating virtual environment in .venv..."
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"
if [[ ! -x "$VENV_PYTHON" && -x ".venv/Scripts/python.exe" ]]; then
  VENV_PYTHON=".venv/Scripts/python.exe"
fi

echo "Installing dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet
if [[ "$DEV_MODE" == true ]]; then
  "$VENV_PYTHON" -m pip install -r requirements-dev.txt
else
  "$VENV_PYTHON" -m pip install -r requirements.txt
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
fi

ENV_CHECK=$("$VENV_PYTHON" - <<'PY'
from pathlib import Path

env_path = Path(".env")
values = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    values[k.strip()] = v.strip()

missing = [k for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET") if not values.get(k)]
print(",".join(missing))
PY
)

if [[ -n "$ENV_CHECK" ]]; then
  if [[ -t 0 ]]; then
    echo ""
    echo "Initial Spotify configuration (.env)"
    echo "Make sure http://127.0.0.1:8000/auth/callback is registered as a Redirect URI in the Spotify Developer Dashboard."
    echo ""
    read -r -p "SPOTIFY_CLIENT_ID: " INPUT_CLIENT_ID
    read -r -s -p "SPOTIFY_CLIENT_SECRET: " INPUT_CLIENT_SECRET
    echo ""

    INPUT_CLIENT_ID="$INPUT_CLIENT_ID" INPUT_CLIENT_SECRET="$INPUT_CLIENT_SECRET" "$VENV_PYTHON" - <<'PY'
import os
from pathlib import Path

env_path = Path(".env")
cid = os.environ["INPUT_CLIENT_ID"].strip()
csec = os.environ["INPUT_CLIENT_SECRET"].strip()

lines = env_path.read_text(encoding="utf-8").splitlines()
updated = []
seen = set()

for line in lines:
    if line.startswith("SPOTIFY_CLIENT_ID="):
        updated.append(f"SPOTIFY_CLIENT_ID={cid}")
        seen.add("SPOTIFY_CLIENT_ID")
    elif line.startswith("SPOTIFY_CLIENT_SECRET="):
        updated.append(f"SPOTIFY_CLIENT_SECRET={csec}")
        seen.add("SPOTIFY_CLIENT_SECRET")
    else:
        updated.append(line)

if "SPOTIFY_CLIENT_ID" not in seen:
    updated.append(f"SPOTIFY_CLIENT_ID={cid}")
if "SPOTIFY_CLIENT_SECRET" not in seen:
    updated.append(f"SPOTIFY_CLIENT_SECRET={csec}")

env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
    echo "Credentials saved to .env."
  else
    echo "Warning: fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env before starting."
  fi
fi

echo "Setup complete."
