#!/usr/bin/env bash
# Build SpendSlicer.app and wrap it in a distributable .dmg.
#
#   ./packaging/build_macos.sh
#
# Output: dist/SpendSlicer-<version>-macos-<arch>.dmg
#
# The build is UNSIGNED. Gatekeeper will refuse to open it on first launch
# ("SpendSlicer is damaged and can't be opened"), because an unsigned, un-notarised
# app downloaded from the internet carries a quarantine attribute. Users clear it
# with the command printed at the end; see docs/DESKTOP.md. To sign instead, set
# CODESIGN_IDENTITY and the notarytool variables documented in that file.
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="SpendSlicer"
VERSION="$(python3 -c 'import re,pathlib; print(re.search(r"__version__ = \"([^\"]+)\"", pathlib.Path("spendslicer/__init__.py").read_text()).group(1))')"
ARCH="$(uname -m)"
DMG="dist/${APP_NAME}-${VERSION}-macos-${ARCH}.dmg"

echo "==> Building ${APP_NAME} ${VERSION} (${ARCH})"

echo "==> Frontend"
(cd frontend && npm ci && npm run build)

echo "==> Icons"
python3 packaging/make_icons.py

echo "==> PyInstaller"
rm -rf build dist
SPENDSLICER_VERSION="${VERSION}" pyinstaller packaging/spendslicer.spec --noconfirm

APP="dist/${APP_NAME}.app"
[ -d "$APP" ] || { echo "ERROR: $APP was not produced"; exit 1; }

# Optional signing. Without an identity the app ships ad-hoc signed, which is
# what PyInstaller already did — enough to run locally, not enough for Gatekeeper.
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    echo "==> Signing with ${CODESIGN_IDENTITY}"
    codesign --deep --force --options runtime --timestamp \
        --entitlements packaging/entitlements.plist \
        --sign "${CODESIGN_IDENTITY}" "$APP"
    codesign --verify --strict --verbose=2 "$APP"
else
    echo "==> No CODESIGN_IDENTITY set — shipping unsigned"
fi

echo "==> Staging .dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

rm -f "$DMG"
hdiutil create \
    -volname "${APP_NAME} ${VERSION}" \
    -srcfolder "$STAGE" \
    -ov -format UDZO \
    "$DMG"

# Notarisation, when credentials are present. Stapling lets the .dmg open
# cleanly even offline.
if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    echo "==> Notarising"
    xcrun notarytool submit "$DMG" \
        --apple-id "${APPLE_ID}" \
        --password "${APPLE_APP_PASSWORD}" \
        --team-id "${APPLE_TEAM_ID}" \
        --wait
    xcrun stapler staple "$DMG"
else
    echo "==> No Apple credentials set — skipping notarisation"
fi

echo
echo "Built: ${DMG}  ($(du -h "$DMG" | cut -f1))"
if [ -z "${CODESIGN_IDENTITY:-}" ]; then
    echo
    echo "This build is unsigned. After downloading, users must run:"
    echo "    xattr -dr com.apple.quarantine \"/Applications/${APP_NAME}.app\""
fi
