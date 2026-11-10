#!/bin/bash
# Double-click this file in Finder to start Portfolio Tracker.
# It opens a Terminal window, starts the app, and opens http://localhost:3001 in your browser when it's ready.
# Keep the window open while you use the app; press Ctrl-C (or close the window) to stop it.
# First time only: if macOS says it can't be opened, right-click this file, choose Open, then Open again.

cd "$(dirname "$0")" || exit 1
URL="http://localhost:3001"

open_browser() {
  if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
}

# Already running (e.g. in another Terminal window)? Just open it.
if curl -s -o /dev/null --max-time 2 "$URL" && curl -s -o /dev/null --max-time 2 http://127.0.0.1:8001/api/health; then
  echo "Portfolio Tracker is already running; opening it in your browser."
  echo "To stop it, press Ctrl-C in the window where it is running."
  open_browser
  read -r -t 10 -p "This window closes in 10 seconds… " _
  exit 0
fi

# Wait (up to 15 minutes: the first run installs what the app needs) until the page answers, then open it.
(
  for _ in $(seq 1 900); do
    if curl -s -o /dev/null --max-time 2 "$URL"; then open_browser; exit 0; fi
    sleep 1
  done
) &
WAITER=$!
trap 'kill "$WAITER" 2>/dev/null' EXIT

echo "Starting Portfolio Tracker… (the first run takes a few minutes)"
bash scripts/dev.sh
status=$?
kill "$WAITER" 2>/dev/null
echo ""
if [ "$status" -ne 0 ]; then
  echo "Portfolio Tracker didn't start or stopped with an error (see the messages above)."
else
  echo "Portfolio Tracker has stopped."
fi
echo "You can close this window."
read -r -p "Press Return to close… " _
