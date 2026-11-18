#!/bin/bash
# Used by the Portfolio Tracker Mac app (scripts/mac/PortfolioTracker.applescript) to run the app without a Terminal window.
#   app.sh start    start everything in the background (does nothing if it already runs)
#   app.sh status   prints one word: ready | starting | stopped | failed
#   app.sh tick     what the app should do now: open-now (ready, window not opened yet) | ready | starting | slow | failed | stopped
#                   (the app keeps no state of its own: it lives in .run/, so the app bundle is never modified)
#   app.sh open     open the app's window (Google Chrome app window if installed, else the default browser)
#   app.sh stop     stop everything
#   app.sh log      show the log in Console
# Works with macOS's bash 3.2. Linux works too (for testing), without the window and log commands.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
URL="http://localhost:3001"
LOGDIR="${PT_LOG_DIR:-$HOME/Library/Logs/Portfolio Tracker}"
LOG="$LOGDIR/app.log"
RUN="$ROOT/.run"
mkdir -p "$LOGDIR" "$RUN"

# Apps don't get your Terminal's PATH (Homebrew's python3 and node live in /opt/homebrew/bin or /usr/local/bin): borrow it.
LOGIN_PATH=$( (/bin/zsh -lic 'printf %s "$PATH"' 2>/dev/null || /bin/bash -lc 'printf %s "$PATH"' 2>/dev/null) | tail -n 1)
export PATH="${LOGIN_PATH:+$LOGIN_PATH:}/opt/homebrew/bin:/usr/local/bin:$PATH"

dev_pid() { cat "$RUN/dev.pid" 2>/dev/null; }
alive() { local p; p=$(dev_pid); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
up() { curl -fs -o /dev/null --max-time 2 "$URL/" && curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:8001/api/health"; }

case "${1:-}" in
  start)
    if alive; then exit 0; fi
    rm -f "$RUN/stopped-by-app" "$RUN/window-opened" "$RUN/warned-slow"
    date +%s > "$RUN/app-started"
    { echo ""; echo "=== $(date '+%Y-%m-%d %H:%M:%S') starting Portfolio Tracker ==="; } >> "$LOG"
    # detached: the app gets control back at once, and closing it never kills the servers half-way
    nohup bash "$ROOT/scripts/dev.sh" --prod >> "$LOG" 2>&1 < /dev/null &
    echo $! > "$RUN/dev.pid"
    ;;
  status)
    if up; then echo ready
    elif alive; then echo starting
    elif [ -f "$RUN/stopped-by-app" ]; then echo stopped
    else echo failed; fi
    ;;
  tick)
    if up; then
      if [ -f "$RUN/window-opened" ]; then echo ready; else touch "$RUN/window-opened"; echo open-now; fi
    elif alive; then
      started=$(cat "$RUN/app-started" 2>/dev/null || date +%s)
      if [ ! -f "$RUN/window-opened" ] && [ ! -f "$RUN/warned-slow" ] && [ $(( $(date +%s) - started )) -gt 1200 ]; then
        touch "$RUN/warned-slow"; echo slow
      else echo starting; fi
    elif [ -f "$RUN/stopped-by-app" ]; then echo stopped
    else echo failed; fi
    ;;
  open)
    if [ -d "/Applications/Google Chrome.app" ] || [ -d "$HOME/Applications/Google Chrome.app" ]; then
      open -na "Google Chrome" --args --app="$URL" --new-window
    elif command -v open >/dev/null 2>&1; then open "$URL"
    else echo "$URL"; fi
    ;;
  stop)
    touch "$RUN/stopped-by-app"
    p=$(dev_pid)
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
      kill -TERM "$p" 2>/dev/null
      for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$p" 2>/dev/null || break; sleep 1; done
    fi
    # anything still holding the app's ports (e.g. after a crash) goes too
    if command -v lsof >/dev/null 2>&1; then
      for port in 3001 8001; do lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null; done
    fi
    rm -f "$RUN/dev.pid"
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') stopped by the app ===" >> "$LOG"
    ;;
  log)
    if command -v open >/dev/null 2>&1; then open -a Console "$LOG"; else tail -n 40 "$LOG"; fi
    ;;
  tail)
    tail -n "${2:-15}" "$LOG"
    ;;
  *)
    echo "usage: app.sh start|status|open|stop|log|tail"; exit 2 ;;
esac
