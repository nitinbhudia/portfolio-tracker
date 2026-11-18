#!/bin/bash
# Builds "Portfolio Tracker.app" in your Applications folder (~/Applications) from this copy of the app.
# Run it again if you move this folder. Nothing to download or install: it uses tools every Mac has.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[ "$(uname)" = Darwin ] || { echo "This builds a Mac app: run it on your Mac."; exit 1; }
DEST_DIR="$HOME/Applications"
APP="$DEST_DIR/Portfolio Tracker.app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST_DIR"

# A running copy of the app is quit first (that also stops the app's servers).
if pgrep -f "Portfolio Tracker.app/Contents/MacOS" >/dev/null 2>&1; then
  osascript -e 'tell application "Portfolio Tracker" to quit' >/dev/null 2>&1 || true
  sleep 3
fi

# The applet, with this folder filled in (AppleScript string: backslashes and quotes escaped).
export APP_HOME_ESC
APP_HOME_ESC=$(printf '%s' "$ROOT" | sed 's/\\/\\\\/g; s/"/\\"/g')
perl -pe 's/__APP_HOME__/$ENV{APP_HOME_ESC}/g' "$ROOT/scripts/mac/PortfolioTracker.applescript" > "$TMP/app.applescript"
rm -rf "$APP"
osacompile -s -o "$APP" "$TMP/app.applescript"

# Icon
mkdir "$TMP/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$ROOT/scripts/mac/icon.png" --out "$TMP/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$ROOT/scripts/mac/icon.png" --out "$TMP/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
rm -f "$APP/Contents/Resources/Assets.car"   # newer macOS: a compiled default icon would win over ours

PLIST="$APP/Contents/Info.plist"
pb() { /usr/libexec/PlistBuddy -c "$1" "$PLIST" >/dev/null 2>&1 || true; }
pb "Delete :CFBundleIconName"
pb "Set :CFBundleIconFile applet"
pb "Set :CFBundleName Portfolio Tracker"
pb "Add :CFBundleDisplayName string Portfolio Tracker"
pb "Set :CFBundleIdentifier com.portfoliotracker.app" ; pb "Add :CFBundleIdentifier string com.portfoliotracker.app"
pb "Add :LSApplicationCategoryType string public.app-category.finance"
pb "Add :NSHumanReadableCopyright string Runs on your computer; your data stays in $ROOT"

# The changes above invalidate the applet's signature: sign it again for this Mac (ad hoc; nothing is uploaded).
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
touch "$APP"

echo ""
echo "Built: $APP"
echo "Open it from Launchpad, Spotlight (type \"Portfolio Tracker\") or Finder → Applications."
echo "To keep it in the Dock: while it's running, right-click its Dock icon → Options → Keep in Dock."
open -R "$APP"
