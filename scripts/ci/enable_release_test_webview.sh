#!/usr/bin/env bash
# Enable only the throw-away x86_64 RELEASE-test WebView CDP hook.
#
# The committed Android source contains no CiFlags/MainActivity debug marker.
# This script is used on a CI worktree immediately before the internal
# release-test APK build and its caller must restore the two files afterwards.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <source-root>" >&2
  exit 2
fi

ROOT="$(cd "$1" && pwd)"
PKG="${ROOT}/apps/desktop/src-tauri/gen/android/app/src/main/java/app/psychologygrowth/desktop"
FLAGS="${PKG}/CiFlags.kt"
MAIN="${PKG}/MainActivity.kt"
[ -f "${MAIN}" ] || { echo "FAIL: MainActivity.kt not found" >&2; exit 1; }

cat > "${FLAGS}" <<'EOF'
// CI-only capability. This file is generated in a throw-away RELEASE-test
// source tree and is never part of a production APK or source manifest.
object CiFlags {
  const val ENABLE_WEBVIEW_REMOTE_DEBUGGING: Boolean = true
}
EOF

python3 - "${MAIN}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING" in text:
    raise SystemExit("release-test WebView hook is already present")
anchor = "  override fun onCreate(savedInstanceState: Bundle?) {\n"
if anchor not in text:
    raise SystemExit("MainActivity onCreate anchor not found")
block = (
    "    // CI-only release-test CDP hook; never committed or shipped.\n"
    + "    // Runs before super.onCreate(): Tauri creates the WebView during super,\n"
    + "    // so the process-wide debugging flag must be set before that boundary.\n"
    + "    if (CiFlags.ENABLE_WEBVIEW_REMOTE_DEBUGGING) {\n"
    + "      android.webkit.WebView.setWebContentsDebuggingEnabled(true)\n"
    + "    }\n"
)
super_anchor = "    super.onCreate(savedInstanceState)\n"
if super_anchor in text:
    text = text.replace(super_anchor, block + super_anchor, 1)
else:
    text = text.replace(anchor, anchor + block, 1)
path.write_text(text, encoding="utf-8")
PY

echo "release-test WebView CDP hook enabled in throw-away source"
