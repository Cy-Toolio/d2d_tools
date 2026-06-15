#!/usr/bin/env bash
# install_csv_mac.sh — Creates CSV Analyzer.app and registers it with macOS Launch Services.
# Run once from Terminal:  bash install_csv_mac.sh
# Uninstall:               bash install_csv_mac.sh --uninstall

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$INSTALL_DIR/csv_tui.py"
APP_NAME="CSV Analyzer"
APP_BUNDLE="$INSTALL_DIR/$APP_NAME.app"
BUNDLE_ID="com.local.csvanalyzer"

LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

# ── uninstall ──────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ]; then
    echo "Removing '$APP_NAME.app'..."
    [ -f "$LSREGISTER" ] && "$LSREGISTER" -u "$APP_BUNDLE" 2>/dev/null || true
    rm -rf "$APP_BUNDLE"
    echo "Done."
    exit 0
fi

# ── prerequisites ──────────────────────────────────────────────────
if [ ! -f "$PY_SCRIPT" ]; then
    echo "Error: csv_tui.py not found at $PY_SCRIPT" >&2; exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install from https://python.org" >&2; exit 1
fi
if ! command -v osacompile &>/dev/null; then
    echo "Error: osacompile not found. Install Xcode Command Line Tools:" >&2
    echo "  xcode-select --install" >&2; exit 1
fi

echo "Python  : $(command -v python3)"
echo "Install : $INSTALL_DIR"
echo ""

# ── write AppleScript source ───────────────────────────────────────
# Uses 'path to me' so the app works regardless of where the folder is placed.
# 'on open' handles the Apple Event Finder sends when double-clicking a file.
TMP_SCRIPT="$(mktemp /tmp/csv_analyzer_XXXXXX.applescript)"
trap 'rm -f "$TMP_SCRIPT"' EXIT

cat > "$TMP_SCRIPT" << 'APPLESCRIPT'
on getPyScript()
    set appPath to POSIX path of (path to me)
    set installDir to do shell script "dirname " & quoted form of appPath
    return installDir & "/csv_tui.py"
end getPyScript

on run
    launchCsv("")
end run

on open theFiles
    set filePath to POSIX path of (item 1 of theFiles)
    launchCsv(filePath)
end open

on launchCsv(filePath)
    set pyScript to getPyScript()
    if filePath is "" then
        set cmd to "/usr/bin/env python3 " & quoted form of pyScript
    else
        set cmd to "/usr/bin/env python3 " & quoted form of pyScript & " " & quoted form of filePath
    end if
    tell application "Terminal"
        activate
        do script cmd
    end tell
end launchCsv
APPLESCRIPT

# ── compile to .app ────────────────────────────────────────────────
echo "Building $APP_NAME.app..."
rm -rf "$APP_BUNDLE"
osacompile -o "$APP_BUNDLE" "$TMP_SCRIPT"

# ── patch Info.plist with CSV document type ────────────────────────
PLIST="$APP_BUNDLE/Contents/Info.plist"
PB="/usr/libexec/PlistBuddy"

"$PB" -c "Set :CFBundleIdentifier $BUNDLE_ID"   "$PLIST" 2>/dev/null \
  || "$PB" -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$PLIST"

"$PB" -c "Add :CFBundleDocumentTypes array"               "$PLIST" 2>/dev/null || true
"$PB" -c "Add :CFBundleDocumentTypes:0 dict"              "$PLIST"
"$PB" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions array"  "$PLIST"
"$PB" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 string csv" "$PLIST"
"$PB" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string CSV File"     "$PLIST"
"$PB" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer"       "$PLIST"
"$PB" -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Default"         "$PLIST"

# ── make launcher executable ───────────────────────────────────────
chmod +x "$INSTALL_DIR/csv_tui_launcher.sh" 2>/dev/null || true

# ── register with Launch Services ─────────────────────────────────
if [ -f "$LSREGISTER" ]; then
    "$LSREGISTER" -f "$APP_BUNDLE"
    echo "Registered with Launch Services."
fi

echo ""
echo "✓ '$APP_NAME.app' created at:"
echo "  $APP_BUNDLE"
echo ""
echo "FIRST-RUN (Gatekeeper):"
echo "  Right-click '$APP_NAME.app' → Open → Open  (one time only)"
echo ""
echo "SET AS DEFAULT:"
echo "  Right-click any .csv file → Get Info  (⌘I)"
echo "  'Open with' → choose 'CSV Analyzer'"
echo "  Click 'Change All...'"
