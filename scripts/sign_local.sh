#!/bin/bash
# Re-sign the local Hey Jev build with a stable identity, so macOS keeps its Screen Recording, Accessibility and
# Calendar permissions across rebuilds.
#
# Why: py2app signs the alias build ad hoc. An ad-hoc signature is identified by its code hash, which changes on
# every rebuild, so macOS treats each rebuild as a new app and asks again. Signing with your Apple Development
# certificate and a fixed designated requirement (bundle id + your team) gives the app one identity that survives.
#
# This script never touches Gatekeeper (no spctl, no quarantine changes) and never types a password. The first real
# signing can show a keychain dialog ("codesign wants to use your key"). Click it yourself.
#
# Usage:
#   scripts/sign_local.sh                 sign dist/"Hey Jev - Fish Audio.app" (run after py2app -A)
#   scripts/sign_local.sh --dry-run       print the identity, requirement and commands; sign nothing, no keychain use
#   scripts/sign_local.sh --verify        check the signature and print the designated requirement
#   scripts/sign_local.sh [--dry-run|--verify] "/path/to/Other.app"
# Overrides: JEV_SIGN_IDENTITY (name or hash), JEV_SIGN_TEAM (10-character team id).
set -euo pipefail

BUNDLE_ID="com.heyjev.app"
MODE="sign"
APP=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) MODE="dry-run" ;;
    --verify) MODE="verify" ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) APP="$arg" ;;
  esac
done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${APP:-$ROOT/dist/Hey Jev - Fish Audio.app}"
EXE_DIR="$APP/Contents/MacOS"

if [ ! -d "$APP" ]; then
  echo "No app at: $APP" >&2
  echo "Build it first: .venv/bin/python setup.py py2app -A" >&2
  exit 1
fi

if [ "$MODE" = "verify" ]; then
  codesign --verify --verbose=2 "$APP"
  echo "--- designated requirement"
  codesign -d -r- "$APP" 2>&1 | grep 'designated =>'
  exit 0
fi

# 1. The identity. Listing identities reads the keychain's certificate list, which does not prompt.
IDENTITY="${JEV_SIGN_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
  IDENTITY="$(security find-identity -v -p codesigning | sed -n 's/^ *[0-9]*) \([0-9A-F]\{40\}\) "Apple Development:.*/\1/p' | head -1)"
fi
if [ -z "$IDENTITY" ]; then
  echo "No 'Apple Development' code-signing identity found. Open Xcode > Settings > Accounts and add your Apple ID," >&2
  echo "or set JEV_SIGN_IDENTITY to a certificate name or hash." >&2
  exit 1
fi

# 2. The team id, from the certificate's OU field.
TEAM="${JEV_SIGN_TEAM:-}"
if [ -z "$TEAM" ]; then
  NAME="$(security find-identity -v -p codesigning | sed -n "s/^ *[0-9]*) $IDENTITY \"\(.*\)\"/\1/p" | head -1)"
  TEAM="$(security find-certificate -c "${NAME:-$IDENTITY}" -p 2>/dev/null | openssl x509 -noout -subject -nameopt RFC2253 2>/dev/null \
    | sed -n 's/.*OU=\([A-Z0-9]\{10\}\).*/\1/p' | head -1)"
fi
if ! printf '%s' "$TEAM" | grep -Eq '^[A-Z0-9]{10}$'; then
  echo "Could not read a 10-character team id from the certificate. Set JEV_SIGN_TEAM." >&2
  exit 1
fi

# 3. The fixed requirement: this bundle id, an Apple-issued certificate, this team. It does not change when the code
#    changes or when the certificate is renewed, so macOS permissions stay.
REQ="designated => identifier \"$BUNDLE_ID\" and anchor apple generic and certificate leaf[subject.OU] = \"$TEAM\""
csreq -r="$REQ" -t >/dev/null  # syntax check only; fails loudly on a typo

EXE="$(find "$EXE_DIR" -maxdepth 1 -type f -perm -u+x | head -1)"
SIGN=(codesign --force --sign "$IDENTITY" --identifier "$BUNDLE_ID" --timestamp=none --requirements "=$REQ")

HELPER="$APP/Contents/Library/LoginItems/Jev Hotkey.app"
HELPER_ID="com.heyjev.app.hotkey"
HELPER_REQ="designated => identifier \"$HELPER_ID\" and anchor apple generic and certificate leaf[subject.OU] = \"$TEAM\""
HELPER_SIGN=(codesign --force --sign "$IDENTITY" --identifier "$HELPER_ID" --timestamp=none --requirements "=$HELPER_REQ")
csreq -r="$HELPER_REQ" -t >/dev/null
echo "identity:    $IDENTITY"
echo "team:        $TEAM"
echo "requirement: $REQ"
echo "app:         $APP"
if [ "$MODE" = "dry-run" ]; then
  if [ -d "$HELPER" ]; then
    echo "would run:   ${HELPER_SIGN[*]} \"$HELPER\"   (the Ctrl-Option-J helper, signed first)"
  fi
  echo "would run:   ${SIGN[*]} \"$EXE\""
  echo "would run:   ${SIGN[*]} \"$APP\""
  echo "would run:   codesign --verify \"$APP\""
  echo "(dry run: nothing signed, no keychain use)"
  exit 0
fi

# 4. Sign the helper (if built), then the executable, then the bundle. (No --strict on verify: alias builds symlink their resources into this repo.)
#    Sign the executable, then the bundle. If macOS asks for keychain access here, click it yourself.
if [ -d "$HELPER" ]; then
  "${HELPER_SIGN[@]}" "$HELPER"
fi
"${SIGN[@]}" "$EXE"
"${SIGN[@]}" "$APP"
codesign --verify --verbose=2 "$APP"
echo "signed. Quit and reopen Hey Jev. Allow Screen Recording once more; it should stay allowed after future rebuilds."
