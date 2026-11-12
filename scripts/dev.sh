#!/usr/bin/env bash
# Portfolio Tracker — one-command setup and start (macOS / Linux).
#   ./scripts/dev.sh          install (if needed) and start: http://localhost:3001
#   ./scripts/dev.sh --test   run the tests, lint and build, then exit
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
API_PORT=8001
WEB_PORT=3001

TEST=0
for a in "$@"; do
  case "$a" in
    --test) TEST=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3.11+ is required. On macOS: brew install python@3.12"; exit 1; }
if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  echo "Node.js 20+ is required. On macOS: brew install node@22"; exit 1
fi
echo "Using $($PY --version) and Node $(node --version)"

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements-dev.txt
(cd frontend && { [ -d node_modules ] || npm ci; })
# Research (the former Fibonacci AI app): bring its database up to date and add the demo data on first run.
(cd backend && alembic -c research/alembic.ini upgrade head >/dev/null && python -m research.data.seed)

if [ "$TEST" = 1 ]; then
  (cd backend && python -m pytest -q)
  (cd frontend && npm run lint && npm test && npm run build)
  exit 0
fi

# Refuse to start on busy ports, and say what is using them.
busy=0
for p in $API_PORT $WEB_PORT; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null || { command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; }; then
    echo ""
    echo "Port $p is already in use:"
    command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | sed 's/^/   /'
    echo "   Stop it (Ctrl-C in its window, or: lsof -ti :$p | xargs kill) and run this again."
    busy=1
  fi
done
[ "$busy" = 0 ] || exit 1

cleanup() { kill "${API_PID:-0}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd backend && uvicorn app.main:app --host 127.0.0.1 --port $API_PORT) &
API_PID=$!
sleep 2
if ! kill -0 "$API_PID" 2>/dev/null; then echo "The backend didn't start (see the error above)."; exit 1; fi

echo ""
echo "  Portfolio Tracker : http://localhost:$WEB_PORT"
echo "  (Ctrl-C stops it; your data stays in backend/portfolio.db)"
echo ""
cd frontend && npx next dev -p $WEB_PORT
