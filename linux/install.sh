#!/usr/bin/env bash
# CodexBar Linux Installer
# Usage: curl -sSL https://raw.githubusercontent.com/BusinessBuilders/CodexBar/main/linux/install.sh | bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/codexbar-linux"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$INSTALL_DIR/app"
CLI_DIR="$INSTALL_DIR/bin"
AUTOSTART_DIR="$HOME/.config/autostart"
REPO="steipete/CodexBar"

echo "==> Installing CodexBar Linux…"

# ── Detect arch ───────────────────────────────────────────
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH="x86_64" ;;
  aarch64|arm64) ARCH="aarch64" ;;
  *) echo "ERROR: Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# ── System dependencies ───────────────────────────────────
echo "==> Installing system packages (requires sudo)…"
sudo apt-get install -y --no-install-recommends \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkx11-4.0 \
    gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
    gnome-shell-extension-appindicator 2>/dev/null || \
sudo apt-get install -y --no-install-recommends \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-gdkx11-4.0 \
    gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1

# ── Python packages ───────────────────────────────────────
echo "==> Installing Python packages…"
/usr/bin/python3 -m pip install --user --quiet "pillow>=10.0.0"

# ── Download codexbar CLI binary ──────────────────────────
echo "==> Fetching latest codexbar CLI release…"
RELEASE_JSON="$(curl -sSL "https://api.github.com/repos/$REPO/releases/latest" \
  -H "Accept: application/vnd.github+json")"
TAG="$(echo "$RELEASE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")"
ASSET_NAME="CodexBarCLI-${TAG}-linux-${ARCH}.tar.gz"
SHA_NAME="${ASSET_NAME}.sha256"
ASSET_URL="$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assets = {a['name']: a['browser_download_url'] for a in data['assets']}
print(assets['$ASSET_NAME'])
")"
SHA_URL="$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assets = {a['name']: a['browser_download_url'] for a in data['assets']}
print(assets['$SHA_NAME'])
")"

mkdir -p "$CLI_DIR"
TARBALL="$CLI_DIR/$ASSET_NAME"
curl -sSL "$ASSET_URL" -o "$TARBALL"

EXPECTED_SHA="$(curl -sSL "$SHA_URL" | awk '{print $1}')"
ACTUAL_SHA="$(sha256sum "$TARBALL" | awk '{print $1}')"
if [ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]; then
  echo "ERROR: SHA-256 mismatch — download may be corrupted." >&2
  rm -f "$TARBALL"
  exit 1
fi

tar -xzf "$TARBALL" -C "$CLI_DIR"
chmod +x "$CLI_DIR/codexbar"
rm -f "$TARBALL"
echo "    codexbar CLI installed at $CLI_DIR/codexbar (${TAG})"

# ── Install app files ─────────────────────────────────────
echo "==> Copying app files…"
mkdir -p "$APP_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SCRIPT_DIR/codexbar_linux" "$APP_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/"

# ── Create launcher script ────────────────────────────────
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/codexbar-linux" <<LAUNCHER
#!/usr/bin/env bash
# Use system python3 — PyGObject (gi) bindings are only available there
export PYTHONPATH="$APP_DIR"
exec /usr/bin/python3 -m codexbar_linux "\$@"
LAUNCHER
chmod +x "$BIN_DIR/codexbar-linux"

cat > "$BIN_DIR/codexbar-linux-quota" <<LAUNCHER
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR"
exec /usr/bin/python3 -m codexbar_linux.quota_server "\$@"
LAUNCHER
chmod +x "$BIN_DIR/codexbar-linux-quota"

# ── Desktop / autostart entries ───────────────────────────
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/codexbar-linux.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=CodexBar
Comment=AI usage stats in your system tray
Exec=$BIN_DIR/codexbar-linux
Icon=utilities-system-monitor
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
DESKTOP

APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cp "$AUTOSTART_DIR/codexbar-linux.desktop" "$APPS_DIR/codexbar-linux.desktop"

echo ""
echo "✓ CodexBar Linux installed successfully!"
echo ""
echo "  Launch now:  codexbar-linux"
echo "  Quota API:   codexbar-linux-quota --host 127.0.0.1 --port 8787"
echo "  Auto-starts: on next login"
echo ""
echo "  Tip: run 'codexbar config' to enable providers before launching."
