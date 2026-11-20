#!/usr/bin/env bash
# Portfolio Tracker — one-command setup and start (macOS / Linux).
#   ./scripts/dev.sh          install (if needed) and start: http://localhost:3001
#   ./scripts/dev.sh --test   run the tests, lint and build, then exit
#   ./scripts/dev.sh --prod   start the built app (built when needed; faster pages): used by the Mac app
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
API_PORT=8001
WEB_PORT=3001
DEMO_PORT=8002   # demo mode: a second backend with made-up data only (the Live/Demo switch in the app)

TEST=0
PROD=0
for a in "$@"; do
  case "$a" in
    --test) TEST=1 ;;
    --prod) PROD=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done
MODE_ARG=""
[ "$PROD" = 1 ] && MODE_ARG="--prod"

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
# Frontend packages: install on first run, and again whenever an update changed package-lock.json.
sha() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1; else sha256sum "$1" | cut -d' ' -f1; fi; }
mkdir -p .run
LOCK_SHA=$(sha frontend/package-lock.json)
if [ ! -d frontend/node_modules ] || [ "$(cat .run/npm-lock.sha 2>/dev/null)" != "$LOCK_SHA" ]; then
  (cd frontend && npm ci) && echo "$LOCK_SHA" > .run/npm-lock.sha
fi
# Research (the former Fibonacci AI app): bring its database up to date and add the demo data on first run.
(cd backend && alembic -c research/alembic.ini upgrade head >/dev/null && python -m research.data.seed)
# Demo mode's made-up data (its own folder, backend/demo-data/): built once, about half a minute. Never touches your data.
if (cd backend && PT_DEMO=1 python -m app.demo.build --if-missing >"$ROOT/.run/demo-build.log" 2>&1); then
  grep -v '^INFO' .run/demo-build.log | tail -n 2
else
  echo "(The demo data couldn't be built, see .run/demo-build.log; the app works without it.)"
fi

if [ "$TEST" = 1 ]; then
  (cd backend && python -m pytest -q)
  (cd frontend && npm run lint && npm test && npm run build)
  exit 0
fi

# --prod: build the pages once (and again whenever an update changed them), in their own folder (.next-prod), so the
# development server of the Terminal starter (.next) never mixes with the built app.
export NEXT_DIST_DIR=".next"
if [ "$PROD" = 1 ]; then
  export NEXT_DIST_DIR=".next-prod"
  SRC_SHA=$(cd frontend && for f in app components lib public package-lock.json next.config.ts tsconfig.json postcss.config.mjs; do
      if [ -e "$f" ]; then find "$f" -type f; fi; done | LC_ALL=C sort | while read -r f; do sha "$f"; done \
    | { if command -v shasum >/dev/null 2>&1; then shasum -a 256; else sha256sum; fi; } | cut -d' ' -f1)
  if [ ! -f "frontend/.next-prod/BUILD_ID" ] || [ "$(cat .run/build.sha 2>/dev/null)" != "$SRC_SHA" ]; then
    echo "Building the app's pages (a minute or two; only after an update)…"
    (cd frontend && npx next build) && echo "$SRC_SHA" > .run/build.sha
  fi
fi

# Refuse to start on busy ports, and say what is using them. After an in-app restart, wait for the old copy to let go.
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null || { command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }; }
if [ "${PT_RESTARTING:-0}" = 1 ]; then
  for _ in $(seq 1 30); do port_busy $API_PORT || port_busy $WEB_PORT || port_busy $DEMO_PORT || break; sleep 1; done
fi
busy=0
for p in $API_PORT $WEB_PORT $DEMO_PORT; do
  if port_busy "$p"; then
    echo ""
    echo "Port $p is already in use:"
    command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | sed 's/^/   /'
    echo "   Stop it (Ctrl-C in its window, or: lsof -ti :$p | xargs kill) and run this again."
    busy=1
  fi
done
[ "$busy" = 0 ] || exit 1

# Stop a process and everything it started (npx -> node -> next-server).
kill_tree() {
  local pid=$1 child
  [ -n "$pid" ] || return 0
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}
stop_all() { kill_tree "${WEB_PID:-}"; kill_tree "${API_PID:-}"; kill_tree "${DEMO_PID:-}"; }
echo $$ > .run/dev.pid   # the Mac app uses this to stop everything (an in-app restart keeps the same process)
trap 'stop_all; rm -f .run/dev.pid; exit 0' INT TERM
trap 'stop_all; rm -f .run/dev.pid' EXIT

# PT_SUPERVISED tells the app it may restart itself (after an update or a restore): it writes .restart-requested
# and ends its backend; this script then stops the frontend and starts everything again from the new files.
rm -f .restart-requested
(cd backend && PT_SUPERVISED=1 exec uvicorn app.main:app --host 127.0.0.1 --port $API_PORT) &
API_PID=$!
# The demo copy: PT_DEMO=1 gives it its own databases and no keys, and routes all its network requests to made-up data.
(cd backend && PT_DEMO=1 exec uvicorn app.main:app --host 127.0.0.1 --port $DEMO_PORT --log-level warning) &
DEMO_PID=$!
sleep 2
if ! kill -0 "$API_PID" 2>/dev/null; then echo "The backend didn't start (see the error above)."; exit 1; fi
if [ "$PROD" = 1 ]; then
  (cd frontend && exec npx next start -p $WEB_PORT) &
else
  (cd frontend && exec npx next dev -p $WEB_PORT) &
fi
WEB_PID=$!

echo ""
echo "  Portfolio Tracker : http://localhost:$WEB_PORT"
echo "  (Ctrl-C stops it; your data stays in backend/portfolio.db)"
echo ""
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 1; done
stop_all
trap - EXIT
if [ -f .restart-requested ]; then
  echo ""
  echo "Restarting Portfolio Tracker (after an update or a restore)…"
  rm -f .restart-requested
  PT_RESTARTING=1 exec bash "$ROOT/scripts/dev.sh" $MODE_ARG
fi
rm -f .run/dev.pid
echo "Portfolio Tracker stopped."
