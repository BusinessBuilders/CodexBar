#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/dist"
APPDIR="$OUTPUT_DIR/CodexBar.AppDir"
BUILD_CACHE_DIR="$OUTPUT_DIR/build-cache"
METADATA_DIR="$BUILD_CACHE_DIR/linuxdeploy-metadata"
APPDIR_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --appdir-only)
      APPDIR_ONLY=1
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      APPDIR="$OUTPUT_DIR/CodexBar.AppDir"
      BUILD_CACHE_DIR="$OUTPUT_DIR/build-cache"
      METADATA_DIR="$BUILD_CACHE_DIR/linuxdeploy-metadata"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$OUTPUT_DIR" "$BUILD_CACHE_DIR"
rm -rf "$APPDIR"
rm -rf "$METADATA_DIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/codexbar-linux" "$METADATA_DIR"

echo "==> Resolving bundled codexbar CLI"
CLI_PATH="$(
/usr/bin/python3 - <<'PY' "$BUILD_CACHE_DIR" "$SCRIPT_DIR"
from pathlib import Path
import sys

build_cache = Path(sys.argv[1])
linux_dir = Path(sys.argv[2])
sys.path.insert(0, str(linux_dir))

from codexbar_linux.cli import download_cli, find_cli

try:
    cli_path = find_cli()
except FileNotFoundError:
    cli_cache_dir = build_cache / "bundled-cli"
    cli_cache_dir.mkdir(parents=True, exist_ok=True)
    cli_path = download_cli(cli_cache_dir)

print(cli_path)
PY
)"

if [[ ! -x "$CLI_PATH" ]]; then
  echo "ERROR: bundled codexbar CLI not found: $CLI_PATH" >&2
  exit 1
fi

echo "==> Copying app sources"
cp -r "$SCRIPT_DIR/codexbar_linux" "$APPDIR/usr/lib/codexbar-linux/"
find "$APPDIR/usr/lib/codexbar-linux" -type d -name '__pycache__' -prune -exec rm -rf {} +
cp "$CLI_PATH" "$APPDIR/usr/bin/codexbar"
chmod +x "$APPDIR/usr/bin/codexbar"

ICON_SOURCE="$REPO_ROOT/docs/icon.png"
if [[ ! -f "$ICON_SOURCE" ]]; then
  echo "ERROR: icon not found at $ICON_SOURCE" >&2
  exit 1
fi
cp "$ICON_SOURCE" "$METADATA_DIR/codexbar-linux.png"

echo "==> Writing launcher metadata"
/usr/bin/python3 - <<'PY' "$APPDIR" "$METADATA_DIR" "$SCRIPT_DIR"
from pathlib import Path
import sys

appdir = Path(sys.argv[1])
metadata_dir = Path(sys.argv[2])
linux_dir = Path(sys.argv[3])
sys.path.insert(0, str(linux_dir))

from codexbar_linux.packaging import PackagingPaths, render_apprun, render_desktop_entry, render_launcher

paths = PackagingPaths.from_root(appdir)
paths.launcher.write_text(render_launcher(paths))
(metadata_dir / "AppRun").write_text(render_apprun(paths))
(metadata_dir / "codexbar-linux.desktop").write_text(
    render_desktop_entry(exec_name="codexbar-linux", icon_name="codexbar-linux")
)
PY

chmod +x "$METADATA_DIR/AppRun" "$APPDIR/usr/bin/codexbar-linux"

if ! command -v linuxdeploy >/dev/null 2>&1; then
  echo "ERROR: linuxdeploy is required to package the AppDir" >&2
  exit 1
fi

echo "==> Deploying bundled CLI dependencies into AppDir"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH="x86_64" ;;
  aarch64|arm64) ARCH="aarch64" ;;
esac

ARCH="$ARCH" linuxdeploy \
  --appdir "$APPDIR" \
  --custom-apprun "$METADATA_DIR/AppRun" \
  --desktop-file "$METADATA_DIR/codexbar-linux.desktop" \
  --icon-file "$METADATA_DIR/codexbar-linux.png" \
  --executable "$APPDIR/usr/bin/codexbar"

echo "==> Bundling Python runtime dependencies"
/usr/bin/python3 -m pip install --quiet --target "$APPDIR/usr/lib/codexbar-linux/site-packages" "pillow>=10.0.0"
find "$APPDIR/usr/lib/codexbar-linux/site-packages" -type d -name '__pycache__' -prune -exec rm -rf {} +

if [[ "$APPDIR_ONLY" == "1" ]]; then
  echo "✓ AppDir ready at $APPDIR"
  exit 0
fi

resolve_appimagetool() {
  if command -v appimagetool >/dev/null 2>&1; then
    command -v appimagetool
    return 0
  fi

  local tools_dir="$BUILD_CACHE_DIR/tools"
  local filename
  case "$ARCH" in
    x86_64) filename="appimagetool-x86_64.AppImage" ;;
    aarch64) filename="appimagetool-aarch64.AppImage" ;;
    *)
      echo "ERROR: unsupported architecture for appimagetool: $ARCH" >&2
      return 1
      ;;
  esac

  mkdir -p "$tools_dir"
  local target="$tools_dir/$filename"
  if [[ ! -x "$target" ]]; then
    curl -fsSL "https://github.com/AppImage/AppImageKit/releases/download/continuous/$filename" -o "$target"
    chmod +x "$target"
  fi
  printf '%s\n' "$target"
}

echo "==> Building AppImage"
APPIMAGETOOL="$(resolve_appimagetool)"
APPIMAGE_PATH="$OUTPUT_DIR/CodexBar-linux-$ARCH.AppImage"
ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_PATH"

echo "✓ AppImage build complete"
printf '%s\n' "$APPIMAGE_PATH"
