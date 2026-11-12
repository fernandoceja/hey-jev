#!/bin/bash
# Build the Jev Hotkey login-item helper and put it inside the Jev app bundle, where SMAppService looks for it:
#   <Jev>.app/Contents/Library/LoginItems/Jev Hotkey.app
# Run it after `py2app -A` (a rebuild replaces the bundle), then run scripts/sign_local.sh. It compiles one Swift file
# with swiftc, adds an ad-hoc signature so it can run, and changes nothing outside the bundle and build/hotkey.
#
# Usage: scripts/build_hotkey_helper.sh [--dry-run] ["/path/to/Hey Jev.app"]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/helper/JevHotkey"
OUT="$ROOT/build/hotkey"
DRY=0
APP=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    *) APP="$arg" ;;
  esac
done
APP="${APP:-$ROOT/dist/Hey Jev - Fish Audio.app}"
DEST="$APP/Contents/Library/LoginItems/Jev Hotkey.app"

if [ ! -d "$APP" ]; then
  echo "No app at: $APP" >&2
  echo "Build it first: .venv/bin/python setup.py py2app -A" >&2
  exit 1
fi
echo "source: $SRC/main.swift"
echo "into:   $DEST"
if [ "$DRY" = "1" ]; then
  echo "(dry run: nothing built or copied)"
  exit 0
fi

rm -rf "$OUT"
mkdir -p "$OUT/Jev Hotkey.app/Contents/MacOS"
swiftc -O "$SRC/main.swift" -o "$OUT/Jev Hotkey.app/Contents/MacOS/JevHotkey" -framework AppKit -framework Carbon
cp "$SRC/Info.plist" "$OUT/Jev Hotkey.app/Contents/Info.plist"
codesign --force --sign - --identifier com.heyjev.app.hotkey --timestamp=none "$OUT/Jev Hotkey.app"

mkdir -p "$APP/Contents/Library/LoginItems"
rm -rf "$DEST"
cp -R "$OUT/Jev Hotkey.app" "$DEST"
echo "helper installed. Now run scripts/sign_local.sh, then quit and reopen Jev."
