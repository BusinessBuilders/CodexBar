# CodexBar Linux — Design Spec
**Date:** 2026-04-12
**Repo:** BusinessBuilders/CodexBar (fork of steipete/CodexBar)

---

## Goal

Port CodexBar to Linux as a sleek, production-quality GTK4 system tray application that visually matches the macOS popup — borderless dark window, thin progress bars, provider cards — driven entirely by the existing `codexbar` CLI binary (no Swift compilation required).

---

## Architecture

Three cooperating components, each with a single clear purpose:

```
pystray (tray icon)
    │
    ├── click → show/hide GTK4 popup window
    │
    └── BackgroundPoller (daemon thread)
            │
            ├── subprocess: codexbar usage --json
            ├── writes → DataStore (thread-safe)
            └── signals GTK main loop → refresh UI
```

### Components

**1. BackgroundPoller** (`poller.py`)
- Daemon thread; runs `codexbar usage --json` every 2 minutes via `subprocess.run`
- Parses JSON into a list of `ProviderData` dataclasses
- Writes atomically to `DataStore` (a `threading.Lock`-guarded object)
- Posts a GLib idle callback (`GLib.idle_add`) to trigger UI refresh after each poll
- Supports on-demand refresh (triggered by "Refresh Now" button)

**2. DataStore** (`store.py`)
- Thread-safe in-memory store: `threading.Lock` + `list[ProviderData]`
- Also holds: `last_refreshed: datetime`, `is_loading: bool`, `cli_error: str | None`
- Single source of truth consumed by the popup window

**3. GTK4 Popup Window** (`window.py`)
- `Gtk.Window` with `set_decorated(False)` — no title bar
- Positioned directly below the tray icon on each show
- Auto-dismissed on `focus-out-event`
- Contains a `Gtk.ScrolledWindow` → `Gtk.Box` of `ProviderCard` widgets
- Footer: "Refreshed X ago" timestamp + "Refresh Now" button

**4. TrayIcon** (`tray.py`)
- `pystray.Icon` running on the main thread
- Icon image: dynamically generated `PIL.Image` — two-bar meter matching the original (top bar = session, bottom bar = weekly), colored green/yellow/red by worst-case provider status
- Left-click: toggle popup window visibility
- Right-click menu: Refresh Now, Settings, Quit

**5. CLI Manager** (`cli.py`)
- Locates the `codexbar` binary: checks `~/.local/share/codexbar-linux/bin/codexbar`, then `PATH`
- On first run: auto-downloads the correct pre-built binary from GitHub Releases (`steipete/CodexBar`) for the current arch (`x86_64` or `aarch64`), verifies SHA-256, marks executable
- Exposes `run_usage_json() -> list[dict]`

---

## Visual Design

Goal: match the macOS popup as closely as GTK4 allows.

### Window
- Size: 300px wide, auto-height (max 600px before scrolling)
- Background: `rgba(28, 28, 35, 0.97)` — near-black with subtle purple tint
- Border radius: 16px (via CSS `border-radius`)
- Box shadow: `0 8px 32px rgba(0,0,0,0.6)` for depth
- No window decorations; `set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)` to avoid taskbar entry

### Provider Card (`ProviderCard` widget)
Each provider renders as a card section:

```
Provider Name        email@domain.com
Plan subtitle                    Max

Session
████████░░░░░░  67% left   Resets in 3h 22m

Weekly
████░░░░░░░░░░  34% left   Resets in 3d 20h
Pace: Behind (-12%) · Runs out in 2d

Credits: $12.40 remaining
──────────────────────────────────────
```

- **Header row**: provider name (`font-weight: bold`, `font-size: 14px`) + email right-aligned (`color: #888`, `font-size: 12px`)
- **Subtitle row**: plan name / source / error message (`font-size: 11px`, muted)
- **Metric rows**: label left, progress bar center, "X% left" right-aligned, reset time below bar
- **Progress bar**: `Gtk.ProgressBar` styled via CSS — height 6px, rounded ends, color-coded:
  - Green `#30d158` when >25% remaining
  - Yellow `#ffd60a` when 10–25% remaining
  - Red `#ff453a` when <10% remaining
- **Divider**: `Gtk.Separator` between cards, `rgba(255,255,255,0.08)`
- **Padding**: 16px horizontal, 12px vertical per card

### Footer
- Last refreshed: `"Updated just now"` / `"Updated 2m ago"` — muted, 11px
- "Refresh Now" link-style button, right-aligned
- Stale indicator (>5 min): timestamp turns orange

### Tray Icon
- 22×22 PNG generated with Pillow
- Two horizontal bars like the original: top = session %, bottom = weekly %
- Color reflects worst-case status across all providers

---

## Data Model

```python
@dataclass
class RateWindow:
    used_percent: float
    remaining_percent: float
    resets_at: str | None        # ISO8601
    reset_description: str | None

@dataclass
class ProviderData:
    provider: str                 # "claude", "codex", "cursor", ...
    account: str | None
    source: str
    status_indicator: str        # "none" | "minor" | "major" | "critical"
    primary: RateWindow | None   # session
    secondary: RateWindow | None # weekly
    tertiary: RateWindow | None  # sonnet / opus
    credits_text: str | None
    credits_remaining: float | None
    plan_text: str | None
    error: str | None
```

Parsed from `codexbar usage --json` output (`ProviderPayload` → `UsageSnapshot`).

---

## Threading Model

GTK4 must run on the main thread. `pystray` also wants the main thread. Resolution:

- `pystray` runs via `threading.Thread(daemon=True)` — it supports this
- GTK4 runs on the main thread via `Gtk.main()`
- BackgroundPoller is a `threading.Thread(daemon=True)`
- All GTK UI updates happen via `GLib.idle_add(callback)` — never directly from the poller thread
- Window show/hide from tray click: `GLib.idle_add(window.present)` / `GLib.idle_add(window.hide)`

---

## File Layout (inside the fork)

```
linux/
├── install.sh              # one-liner installer
├── codexbar_linux/
│   ├── __main__.py         # entry point: wires components together
│   ├── cli.py              # CLI binary location + auto-download
│   ├── poller.py           # BackgroundPoller thread
│   ├── store.py            # DataStore (thread-safe)
│   ├── tray.py             # pystray TrayIcon
│   ├── window.py           # GTK4 popup window
│   ├── card.py             # ProviderCard GTK widget
│   ├── style.css           # All CSS for the popup
│   └── assets/
│       └── icon_template.png
├── requirements.txt        # pystray pillow pygobject
└── codexbar-linux.desktop  # freedesktop autostart entry
```

---

## Install Flow

`install.sh` (curl-pipe-bash):

1. Detect arch (`uname -m` → x86_64 or aarch64)
2. Download `CodexBarCLI-v{latest}-linux-{arch}.tar.gz` from `steipete/CodexBar` GitHub Releases
3. Verify SHA-256
4. Extract to `~/.local/share/codexbar-linux/bin/codexbar`
5. `pip install --user pystray pillow pygobject`
6. Copy `linux/codexbar_linux/` to `~/.local/share/codexbar-linux/app/`
7. Create `~/.config/autostart/codexbar-linux.desktop`
8. Create `~/.local/bin/codexbar-linux` launcher script
9. Optionally launch immediately

---

## Configuration

`~/.config/codexbar-linux/config.json`:
```json
{
  "refresh_interval_seconds": 120,
  "theme": "dark",
  "autostart": true,
  "cli_path": null
}
```

`cli_path: null` = auto-detect. All values configurable; no hardcoded constants in app code.

---

## Error Handling

- CLI binary not found → popup shows "CLI not installed" with install button
- CLI returns non-zero → DataStore stores `cli_error`, popup shows error card with raw stderr
- CLI times out (>30s) → treated as error, poller retries next cycle
- No providers enabled → popup shows "No providers enabled — run `codexbar config`"
- Network down → stale data shown with orange "Stale" badge

---

## Testing

- Unit tests for `DataStore` thread-safety (concurrent reads/writes)
- Unit tests for JSON parsing (`cli.py` → `ProviderData`) against fixture JSON files
- Manual smoke test: install script on clean Ubuntu 24.04 VM
- Visual test: screenshot comparison of popup against macOS original

---

## Success Criteria

1. `install.sh` completes in under 60 seconds on a fresh Ubuntu machine
2. Popup appears within 200ms of tray click
3. Data refreshes automatically every 2 minutes without user interaction
4. All providers supported by the CLI are displayed (Claude, Codex, Cursor, Gemini, Copilot, etc.)
5. Visual output matches the macOS app's layout and information hierarchy
6. No crashes on provider fetch failure — graceful error display
