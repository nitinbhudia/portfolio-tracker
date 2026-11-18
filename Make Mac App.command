#!/bin/bash
# Double-click this file in Finder to build "Portfolio Tracker.app" in your Applications folder.
# After that, open Portfolio Tracker like any other app: no Terminal window needed.
# First time only: if macOS says it can't be opened, right-click this file, choose Open, then Open again.
cd "$(dirname "$0")" || exit 1
if bash scripts/mac/build-app.sh; then
  echo ""
  echo "Done. You can close this window."
else
  echo ""
  echo "The app couldn't be built (see the messages above)."
fi
read -r -p "Press Return to close… " _
