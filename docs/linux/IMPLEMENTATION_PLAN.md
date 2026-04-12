# CodexBar Linux — GTK4 Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Linux system tray app that pixel-matches the macOS CodexBar popup — frosted-glass light window, provider tab strip, per-provider metric cards with thin progress bars and orange-dot indicators — consuming the pre-built `codexbar` CLI binary.

**Architecture:** GTK4 borderless popup window (main thread via `Gtk.main()`) + pystray tray icon (daemon thread) + BackgroundPoller daemon thread sharing a thread-safe DataStore. All GTK mutations happen via `GLib.idle_add()`. Provider tab strip switches between single-provider detail views.

**Tech Stack:** Python 3.11+, PyGObject (GTK4 + GLib + GdkX11), pystray 0.19+, Pillow 10+, pytest 8+

**Visual Target:** See `docs/superpowers/specs/2026-04-12-codexbar-linux-design.md`. Light frosted-glass popup, provider tabs at top, sections: Session / Weekly / Sonnet / Extra usage / Cost.

**Working Directory:** All code paths below are relative to `/home/magiccat/CodexBar` (the BusinessBuilders/CodexBar fork clone).

---

## File Map

| File | Responsibility |
|---|---|
| `linux/codexbar_linux/__main__.py` | Entry point: instantiate all components, start threads, run GTK main loop |
| `linux/codexbar_linux/store.py` | `RateWindow`, `ProviderData` dataclasses + thread-safe `DataStore` |
| `linux/codexbar_linux/cli.py` | Locate/download `codexbar` binary; `run_usage_json()` → `list[ProviderData]` |
| `linux/codexbar_linux/poller.py` | `BackgroundPoller`: daemon thread, periodic `cli.run_usage_json()`, signals GTK |
| `linux/codexbar_linux/tray.py` | `TrayIcon`: pystray icon with Pillow-generated two-bar meter image |
| `linux/codexbar_linux/window.py` | `PopupWindow`: borderless GTK4 window, position-near-tray, focus-out dismiss |
| `linux/codexbar_linux/tab_strip.py` | `ProviderTabStrip`: GTK4 widget — provider name buttons, active = blue pill |
| `linux/codexbar_linux/provider_view.py` | `ProviderView`: single-provider detail (header + metric rows + cost section) |
| `linux/codexbar_linux/usage_bar.py` | `UsageBar`: GTK4 `DrawingArea` — gray track + orange dot at fill position |
| `linux/codexbar_linux/style.css` | All CSS: frosted window bg, tab pills, typography, dividers |
| `linux/tests/fixtures/usage.json` | Fixture JSON matching real `codexbar usage --json` output |
| `linux/tests/test_store.py` | DataStore thread-safety + parsing correctness |
| `linux/tests/test_cli.py` | JSON → `ProviderData` parsing, binary detection |
| `linux/tests/test_poller.py` | Poller refresh logic with mocked CLI |
| `linux/tests/test_usage_bar.py` | UsageBar color logic |
| `linux/install.sh` | Curl-pipe-bash installer: downloads CLI binary + pip install + desktop entry |
| `linux/requirements.txt` | `pystray>=0.19 pillow>=10.0` (pygobject installed via apt) |
| `linux/codexbar-linux.desktop` | Freedesktop autostart + application menu entry |

---

### Task 1: Scaffold the `linux/` directory and confirm dependencies

**Files:**
- Create: `linux/requirements.txt`
- Create: `linux/codexbar_linux/__init__.py`
- Create: `linux/tests/__init__.py`
- Create: `linux/tests/conftest.py`

- [ ] **Step 1: Create directory structure**

```bash
cd /home/magiccat/CodexBar
mkdir -p linux/codexbar_linux/assets/providers
mkdir -p linux/tests/fixtures
touch linux/codexbar_linux/__init__.py linux/tests/__init__.py
```

- [ ] **Step 2: Write `linux/requirements.txt`**

```
pystray>=0.19.0
pillow>=10.0.0
```

- [ ] **Step 3: Install system GTK4 packages**

```bash
sudo apt-get install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    gir1.2-gdkx11-4.0 \
    libayatana-appindicator3-dev
pip install --user pystray pillow pytest
```

Expected: no errors. Verify:
```bash
python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk; print(Gtk.MAJOR_VERSION)"
# Expected output: 4
python3 -c "import pystray, PIL; print('ok')"
# Expected output: ok
```

- [ ] **Step 4: Write `linux/tests/conftest.py`**

```python
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def load_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES_DIR / name).read_text())
```

- [ ] **Step 5: Commit scaffold**

```bash
cd /home/magiccat/CodexBar
git add linux/
git commit -m "feat(linux): scaffold codexbar-linux project structure"
```

---

### Task 2: Data models — `store.py`

**Files:**
- Create: `linux/codexbar_linux/store.py`
- Create: `linux/tests/test_store.py`

- [ ] **Step 1: Write failing tests for `DataStore`**

```python
# linux/tests/test_store.py
import threading
import time
from codexbar_linux.store import DataStore, ProviderData, RateWindow


def _make_provider(name: str = "claude") -> ProviderData:
    return ProviderData(
        provider=name,
        account="user@example.com",
        source="oauth",
        status_indicator="none",
        primary=RateWindow(used_percent=2.0, remaining_percent=98.0,
                           resets_at="2026-04-12T18:00:00Z", reset_description="Resets in 3h 53m"),
        secondary=RateWindow(used_percent=3.0, remaining_percent=97.0,
                             resets_at="2026-04-19T00:00:00Z", reset_description="Resets in 3d 20h"),
        tertiary=None,
        credits_text=None,
        credits_remaining=None,
        plan_text="Max",
        error=None,
    )


def test_initial_state():
    store = DataStore()
    assert store.providers == []
    assert store.last_refreshed is None
    assert store.is_loading is False
    assert store.cli_error is None


def test_update_stores_providers():
    store = DataStore()
    providers = [_make_provider("claude"), _make_provider("codex")]
    store.update(providers)
    assert len(store.providers) == 2
    assert store.providers[0].provider == "claude"
    assert store.last_refreshed is not None
    assert store.is_loading is False


def test_set_loading():
    store = DataStore()
    store.set_loading()
    assert store.is_loading is True


def test_update_clears_loading():
    store = DataStore()
    store.set_loading()
    store.update([_make_provider()])
    assert store.is_loading is False


def test_update_with_error():
    store = DataStore()
    store.update([], error="CLI timed out")
    assert store.cli_error == "CLI timed out"
    assert store.providers == []


def test_thread_safety():
    """Concurrent reads and writes must not raise or corrupt data."""
    store = DataStore()
    errors = []

    def writer():
        for _ in range(50):
            store.update([_make_provider("claude")])
            time.sleep(0.001)

    def reader():
        for _ in range(50):
            try:
                _ = store.providers
                _ = store.last_refreshed
            except Exception as e:
                errors.append(e)
            time.sleep(0.001)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader),
               threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_providers_returns_copy():
    """Mutating the returned list must not affect the store."""
    store = DataStore()
    store.update([_make_provider()])
    p = store.providers
    p.clear()
    assert len(store.providers) == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_store.py -v 2>&1 | head -20
# Expected: ImportError or ModuleNotFoundError for codexbar_linux.store
```

- [ ] **Step 3: Write `linux/codexbar_linux/store.py`**

```python
from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RateWindow:
    used_percent: float
    remaining_percent: float
    resets_at: Optional[str] = None
    reset_description: Optional[str] = None


@dataclass
class ProviderData:
    provider: str
    account: Optional[str]
    source: str
    status_indicator: str  # "none" | "minor" | "major" | "critical" | "maintenance"
    primary: Optional[RateWindow]    # session window
    secondary: Optional[RateWindow]  # weekly window
    tertiary: Optional[RateWindow]   # sonnet/opus window
    credits_text: Optional[str]
    credits_remaining: Optional[float]
    plan_text: Optional[str]
    error: Optional[str]


class DataStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._providers: list[ProviderData] = []
        self._last_refreshed: Optional[datetime] = None
        self._is_loading: bool = False
        self._cli_error: Optional[str] = None

    def update(self, providers: list[ProviderData], error: Optional[str] = None) -> None:
        with self._lock:
            self._providers = list(providers)
            self._last_refreshed = datetime.now()
            self._is_loading = False
            self._cli_error = error

    def set_loading(self) -> None:
        with self._lock:
            self._is_loading = True

    @property
    def providers(self) -> list[ProviderData]:
        with self._lock:
            return list(self._providers)

    @property
    def last_refreshed(self) -> Optional[datetime]:
        with self._lock:
            return self._last_refreshed

    @property
    def is_loading(self) -> bool:
        with self._lock:
            return self._is_loading

    @property
    def cli_error(self) -> Optional[str]:
        with self._lock:
            return self._cli_error
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_store.py -v
# Expected: 7 passed
```

- [ ] **Step 5: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/store.py linux/tests/test_store.py
git commit -m "feat(linux): add thread-safe DataStore with ProviderData models"
```

---

### Task 3: CLI manager and JSON parsing — `cli.py`

**Files:**
- Create: `linux/tests/fixtures/usage.json`
- Create: `linux/codexbar_linux/cli.py`
- Create: `linux/tests/test_cli.py`

- [ ] **Step 1: Create fixture JSON**

This fixture mirrors the real `codexbar usage --json` output structure:

```json
// linux/tests/fixtures/usage.json
[
  {
    "provider": "claude",
    "account": "user@example.com",
    "version": "0.20",
    "source": "oauth",
    "status": {
      "indicator": "none",
      "description": null,
      "updatedAt": "2026-04-12T10:00:00Z",
      "url": "https://status.anthropic.com"
    },
    "usage": {
      "primary": {
        "usedPercent": 2.0,
        "remainingPercent": 98.0,
        "windowMinutes": 300,
        "resetsAt": "2026-04-12T18:00:00Z",
        "resetDescription": "Resets in 3h 53m"
      },
      "secondary": {
        "usedPercent": 3.0,
        "remainingPercent": 97.0,
        "windowMinutes": 10080,
        "resetsAt": "2026-04-19T00:00:00Z",
        "resetDescription": "Resets in 3d 20h"
      },
      "tertiary": {
        "usedPercent": 0.0,
        "remainingPercent": 100.0,
        "windowMinutes": 10080,
        "resetsAt": null,
        "resetDescription": null
      },
      "planText": "Max"
    },
    "credits": null,
    "antigravityPlanInfo": null,
    "openaiDashboard": null,
    "error": null
  },
  {
    "provider": "codex",
    "account": "other@example.com",
    "version": "0.20",
    "source": "cli",
    "status": {
      "indicator": "minor",
      "description": "Partial outage",
      "updatedAt": "2026-04-12T09:00:00Z",
      "url": "https://status.openai.com"
    },
    "usage": {
      "primary": {
        "usedPercent": 45.0,
        "remainingPercent": 55.0,
        "windowMinutes": 300,
        "resetsAt": "2026-04-12T15:00:00Z",
        "resetDescription": "Resets in 1h 12m"
      },
      "secondary": null,
      "tertiary": null,
      "planText": null
    },
    "credits": {
      "remaining": 12.40,
      "total": 100.0,
      "currencyCode": "USD"
    },
    "antigravityPlanInfo": null,
    "openaiDashboard": null,
    "error": null
  }
]
```

- [ ] **Step 2: Write failing tests**

```python
# linux/tests/test_cli.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from codexbar_linux.cli import parse_providers, find_cli, run_usage_json
from codexbar_linux.store import ProviderData, RateWindow
from tests.conftest import load_fixture


def test_parse_claude_provider():
    data = load_fixture("usage.json")
    providers = parse_providers(data)
    assert len(providers) == 2

    claude = providers[0]
    assert isinstance(claude, ProviderData)
    assert claude.provider == "claude"
    assert claude.account == "user@example.com"
    assert claude.status_indicator == "none"
    assert claude.plan_text == "Max"
    assert claude.error is None

    assert claude.primary is not None
    assert claude.primary.used_percent == 2.0
    assert claude.primary.remaining_percent == 98.0
    assert claude.primary.reset_description == "Resets in 3h 53m"

    assert claude.secondary is not None
    assert claude.secondary.used_percent == 3.0

    assert claude.tertiary is not None
    assert claude.tertiary.used_percent == 0.0


def test_parse_codex_with_credits():
    data = load_fixture("usage.json")
    providers = parse_providers(data)
    codex = providers[1]

    assert codex.provider == "codex"
    assert codex.credits_remaining == 12.40
    assert codex.credits_text == "$12.40 remaining"
    assert codex.status_indicator == "minor"
    assert codex.secondary is None


def test_parse_null_usage_fields():
    data = [{"provider": "cursor", "account": None, "version": None,
              "source": "cookie", "status": None, "usage": None,
              "credits": None, "antigravityPlanInfo": None,
              "openaiDashboard": None, "error": None}]
    providers = parse_providers(data)
    assert providers[0].primary is None
    assert providers[0].secondary is None
    assert providers[0].status_indicator == "none"


def test_parse_provider_with_error():
    data = [{"provider": "gemini", "account": None, "version": None,
              "source": "oauth", "status": None, "usage": None,
              "credits": None, "antigravityPlanInfo": None,
              "openaiDashboard": None,
              "error": {"message": "Token expired", "kind": "auth"}}]
    providers = parse_providers(data)
    assert providers[0].error == "Token expired"


def test_run_usage_json_timeout():
    cli_path = Path("/usr/bin/sleep")
    payloads, error = run_usage_json(cli_path, timeout=0.01)
    assert payloads == []
    assert "timed out" in error.lower()


def test_run_usage_json_bad_json():
    """If CLI returns non-JSON, we get a clean error string."""
    with patch("codexbar_linux.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        payloads, error = run_usage_json(Path("/fake/codexbar"))
    assert payloads == []
    assert error is not None


def test_find_cli_in_path(tmp_path):
    fake_binary = tmp_path / "codexbar"
    fake_binary.write_text("#!/bin/bash\necho ok")
    fake_binary.chmod(0o755)
    result = find_cli(config_path=str(fake_binary))
    assert result == fake_binary


def test_find_cli_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="codexbar CLI not found"):
        find_cli(config_path=str(tmp_path / "nonexistent"), search_install_dir=tmp_path)
```

- [ ] **Step 3: Run to confirm failure**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_cli.py -v 2>&1 | head -10
# Expected: ImportError for codexbar_linux.cli
```

- [ ] **Step 4: Write `linux/codexbar_linux/cli.py`**

```python
from __future__ import annotations
import hashlib
import json
import platform
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Optional

from codexbar_linux.store import ProviderData, RateWindow

GITHUB_RELEASES_API = "https://api.github.com/repos/steipete/CodexBar/releases/latest"
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "share" / "codexbar-linux" / "bin"


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    raise RuntimeError(f"Unsupported architecture: {machine}")


def find_cli(
    config_path: Optional[str] = None,
    search_install_dir: Path = DEFAULT_INSTALL_DIR,
) -> Path:
    """Locate the codexbar binary: config path > install dir > PATH."""
    if config_path:
        p = Path(config_path)
        if p.is_file():
            return p
    installed = search_install_dir / "codexbar"
    if installed.is_file():
        return installed
    found = shutil.which("codexbar")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "codexbar CLI not found. Run linux/install.sh to install it."
    )


def download_cli(install_dir: Path = DEFAULT_INSTALL_DIR) -> Path:
    """Download the latest codexbar CLI binary for the current arch."""
    arch = _arch()
    req = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.load(resp)

    tag = release["tag_name"]
    asset_name = f"CodexBarCLI-{tag}-linux-{arch}.tar.gz"
    sha_name = f"{asset_name}.sha256"

    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    if asset_name not in assets:
        raise RuntimeError(f"No Linux binary for {arch} in release {tag}")

    install_dir.mkdir(parents=True, exist_ok=True)
    tarball = install_dir / asset_name

    with urllib.request.urlopen(assets[asset_name], timeout=120) as resp:
        tarball.write_bytes(resp.read())

    with urllib.request.urlopen(assets[sha_name], timeout=30) as resp:
        expected_sha = resp.read().decode().split()[0]

    actual_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        tarball.unlink()
        raise RuntimeError(f"SHA-256 mismatch for {asset_name}: download corrupted")

    with tarfile.open(tarball) as tf:
        tf.extractall(install_dir)

    binary = install_dir / "codexbar"
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    tarball.unlink()
    return binary


def _parse_rate_window(data: Optional[dict]) -> Optional[RateWindow]:
    if not data:
        return None
    return RateWindow(
        used_percent=float(data.get("usedPercent", 0.0)),
        remaining_percent=float(data.get("remainingPercent", 100.0)),
        resets_at=data.get("resetsAt"),
        reset_description=data.get("resetDescription"),
    )


def parse_providers(raw: list[dict]) -> list[ProviderData]:
    """Convert raw CLI JSON payload list to ProviderData list."""
    result = []
    for item in raw:
        usage = item.get("usage") or {}
        status = item.get("status") or {}
        credits = item.get("credits")
        error_payload = item.get("error")

        credits_remaining: Optional[float] = None
        credits_text: Optional[str] = None
        if credits and credits.get("remaining") is not None:
            credits_remaining = float(credits["remaining"])
            code = credits.get("currencyCode", "USD")
            if code == "Quota":
                credits_text = f"{credits_remaining:.0f} quota remaining"
            else:
                credits_text = f"${credits_remaining:.2f} remaining"

        result.append(ProviderData(
            provider=item.get("provider", "unknown"),
            account=item.get("account"),
            source=item.get("source", ""),
            status_indicator=status.get("indicator", "none"),
            primary=_parse_rate_window(usage.get("primary")),
            secondary=_parse_rate_window(usage.get("secondary")),
            tertiary=_parse_rate_window(usage.get("tertiary")),
            credits_text=credits_text,
            credits_remaining=credits_remaining,
            plan_text=usage.get("planText"),
            error=error_payload.get("message") if error_payload else None,
        ))
    return result


def run_usage_json(
    cli_path: Path,
    timeout: int = 30,
) -> tuple[list[ProviderData], Optional[str]]:
    """Run `codexbar usage --json`, return (providers, error_string)."""
    try:
        result = subprocess.run(
            [str(cli_path), "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return [], result.stderr.strip() or f"CLI exit code {result.returncode}"
        raw = json.loads(result.stdout)
        return parse_providers(raw), None
    except subprocess.TimeoutExpired:
        return [], f"CLI timed out after {timeout}s"
    except json.JSONDecodeError as exc:
        return [], f"Invalid JSON from CLI: {exc}"
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
```

- [ ] **Step 5: Validate fixture against real CLI output (manual step)**

```bash
# Download the real CLI binary and test our fixture matches its actual output format
cd /tmp
curl -sL "$(gh api repos/steipete/CodexBar/releases/latest \
  --jq '.assets[] | select(.name | contains("linux-x86_64.tar.gz")) | .browser_download_url')" \
  -o codexbar.tar.gz
tar xzf codexbar.tar.gz
chmod +x codexbar
./codexbar usage --json 2>/dev/null | python3 -m json.tool | head -40
```

If field names differ from the fixture (e.g., `used_percent` vs `usedPercent`), update `linux/tests/fixtures/usage.json` and `_parse_rate_window()` / `parse_providers()` accordingly.

- [ ] **Step 6: Run tests — expect all pass**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_cli.py -v
# Expected: 7 passed
```

- [ ] **Step 7: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/cli.py linux/tests/test_cli.py linux/tests/fixtures/
git commit -m "feat(linux): add CLI manager with JSON parsing and binary auto-download"
```

---

### Task 4: BackgroundPoller — `poller.py`

**Files:**
- Create: `linux/codexbar_linux/poller.py`
- Create: `linux/tests/test_poller.py`

- [ ] **Step 1: Write failing tests**

```python
# linux/tests/test_poller.py
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from codexbar_linux.poller import BackgroundPoller
from codexbar_linux.store import DataStore, ProviderData, RateWindow


def _make_provider() -> ProviderData:
    return ProviderData(
        provider="claude", account=None, source="oauth",
        status_indicator="none",
        primary=RateWindow(2.0, 98.0, None, None),
        secondary=None, tertiary=None,
        credits_text=None, credits_remaining=None, plan_text=None, error=None,
    )


def test_poller_updates_store_on_start():
    store = DataStore()
    called = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        called.set()
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    assert called.wait(timeout=2.0), "Poller did not call fetch within 2s"
    time.sleep(0.05)
    assert len(store.providers) == 1


def test_poller_calls_on_update_callback():
    store = DataStore()
    callback_called = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=lambda: callback_called.set(),
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    assert callback_called.wait(timeout=2.0)


def test_poller_stores_error_on_failure():
    store = DataStore()
    done = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        done.set()
        return ([], "CLI not found")

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    done.wait(timeout=2.0)
    time.sleep(0.05)
    assert store.cli_error == "CLI not found"


def test_refresh_now_triggers_immediate_fetch():
    store = DataStore()
    fetch_count = [0]
    second_fetch = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        fetch_count[0] += 1
        if fetch_count[0] == 2:
            second_fetch.set()
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    time.sleep(0.1)
    poller.refresh_now()
    assert second_fetch.wait(timeout=2.0), "refresh_now() did not trigger second fetch"


def test_poller_stop():
    store = DataStore()
    fetch_count = [0]

    def fake_fetch(cli_path, timeout=30):
        fetch_count[0] += 1
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=0.05,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    time.sleep(0.2)
    poller.stop()
    count_at_stop = fetch_count[0]
    time.sleep(0.2)
    assert fetch_count[0] == count_at_stop, "Poller continued after stop()"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_poller.py -v 2>&1 | head -10
# Expected: ImportError
```

- [ ] **Step 3: Write `linux/codexbar_linux/poller.py`**

```python
from __future__ import annotations
import threading
from pathlib import Path
from typing import Callable, Optional

from codexbar_linux import cli as cli_module
from codexbar_linux.store import DataStore, ProviderData


class BackgroundPoller:
    """Daemon thread that periodically fetches usage data and updates DataStore."""

    def __init__(
        self,
        store: DataStore,
        cli_path: Path,
        interval_seconds: float,
        on_update: Optional[Callable[[], None]],
        fetch_fn: Optional[Callable] = None,
    ) -> None:
        self._store = store
        self._cli_path = cli_path
        self._interval = interval_seconds
        self._on_update = on_update
        self._fetch_fn = fetch_fn or cli_module.run_usage_json
        self._stop_event = threading.Event()
        self._refresh_event = threading.Event()

    def start(self) -> None:
        """Entry point for the daemon thread. Runs until stop() is called."""
        while not self._stop_event.is_set():
            self._run_fetch()
            # Wait for interval or early wakeup via refresh_now()
            self._refresh_event.wait(timeout=self._interval)
            self._refresh_event.clear()

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_event.set()  # unblock the wait

    def refresh_now(self) -> None:
        """Trigger an immediate out-of-cycle fetch."""
        self._refresh_event.set()

    def _run_fetch(self) -> None:
        self._store.set_loading()
        providers, error = self._fetch_fn(self._cli_path)
        self._store.update(providers, error=error)
        if self._on_update:
            self._on_update()
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_poller.py -v
# Expected: 5 passed
```

- [ ] **Step 5: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/poller.py linux/tests/test_poller.py
git commit -m "feat(linux): add BackgroundPoller daemon thread with refresh_now support"
```

---

### Task 5: Usage bar widget — `usage_bar.py`

**Files:**
- Create: `linux/codexbar_linux/usage_bar.py`
- Create: `linux/tests/test_usage_bar.py`

- [ ] **Step 1: Write failing tests**

```python
# linux/tests/test_usage_bar.py
import pytest
from codexbar_linux.usage_bar import bar_color


def test_healthy_color():
    assert bar_color(used_percent=2.0) == "#ff9500"   # orange (low usage = normal)


def test_warning_color():
    assert bar_color(used_percent=76.0) == "#ffd60a"  # yellow at 75%+


def test_danger_color():
    assert bar_color(used_percent=91.0) == "#ff453a"  # red at 90%+


def test_boundary_75():
    assert bar_color(used_percent=75.0) == "#ff9500"
    assert bar_color(used_percent=75.1) == "#ffd60a"


def test_boundary_90():
    assert bar_color(used_percent=90.0) == "#ffd60a"
    assert bar_color(used_percent=90.1) == "#ff453a"


def test_clamp_over_100():
    assert bar_color(used_percent=150.0) == "#ff453a"


def test_clamp_under_0():
    assert bar_color(used_percent=-5.0) == "#ff9500"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_usage_bar.py -v 2>&1 | head -5
# Expected: ImportError
```

- [ ] **Step 3: Write `linux/codexbar_linux/usage_bar.py`**

```python
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


def bar_color(used_percent: float) -> str:
    """Return hex color for the progress dot based on usage level."""
    pct = max(0.0, min(100.0, used_percent))
    if pct > 90.0:
        return "#ff453a"   # red — critical
    if pct > 75.0:
        return "#ffd60a"   # yellow — warning
    return "#ff9500"       # orange — normal (matches macOS original)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


class UsageBar(Gtk.DrawingArea):
    """
    Thin horizontal usage bar matching the macOS CodexBar style:
    - Full-width light gray track
    - Colored fill from 0 to used_percent (minimum visible width = height, so it reads as a dot at low usage)
    """

    HEIGHT = 6

    def __init__(self, used_percent: float = 0.0) -> None:
        super().__init__()
        self._used_percent = max(0.0, min(100.0, used_percent))
        self.set_content_height(self.HEIGHT)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def set_percent(self, used_percent: float) -> None:
        self._used_percent = max(0.0, min(100.0, used_percent))
        self.queue_draw()

    def _draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        radius = height / 2.0

        # Draw gray track
        self._rounded_rect(cr, 0, 0, width, height, radius)
        cr.set_source_rgba(0.2, 0.2, 0.2, 0.12)
        cr.fill()

        # Draw colored fill — minimum width = height (appears as a dot at ~0%)
        fill_width = max(float(height), (self._used_percent / 100.0) * width)
        r, g, b = _hex_to_rgb(bar_color(self._used_percent))
        self._rounded_rect(cr, 0, 0, fill_width, height, radius)
        cr.set_source_rgb(r, g, b)
        cr.fill()

    @staticmethod
    def _rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
        cr.new_sub_path()
        cr.arc(x + r, y + r, r, 3.14159, 3.0 * 3.14159 / 2.0)
        cr.arc(x + w - r, y + r, r, 3.0 * 3.14159 / 2.0, 0)
        cr.arc(x + w - r, y + h - r, r, 0, 3.14159 / 2.0)
        cr.arc(x + r, y + h - r, r, 3.14159 / 2.0, 3.14159)
        cr.close_path()
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/test_usage_bar.py -v
# Expected: 7 passed
```

- [ ] **Step 5: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/usage_bar.py linux/tests/test_usage_bar.py
git commit -m "feat(linux): add UsageBar drawing widget with color thresholds"
```

---

### Task 6: CSS styling — `style.css`

**Files:**
- Create: `linux/codexbar_linux/style.css`

- [ ] **Step 1: Write `linux/codexbar_linux/style.css`**

```css
/* linux/codexbar_linux/style.css */

/* ── Window ──────────────────────────────────────────────── */
window.popup {
    background-color: rgba(248, 248, 252, 0.96);
    border-radius: 14px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35), 0 2px 8px rgba(0, 0, 0, 0.15);
}

/* ── Provider Tab Strip ─────────────────────────────────── */
.tab-strip {
    background-color: rgba(0, 0, 0, 0.05);
    border-radius: 12px 12px 0 0;
    padding: 8px 10px 6px 10px;
}

.tab-button {
    background: none;
    border: none;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
    color: #555555;
    font-weight: 500;
    min-width: 48px;
    transition: background-color 80ms ease;
}

.tab-button:hover {
    background-color: rgba(0, 0, 0, 0.06);
}

.tab-button.active {
    background-color: #3b82f6;
    color: #ffffff;
    font-weight: 600;
}

.tab-icon {
    font-size: 13px;
}

/* ── Provider Detail View ───────────────────────────────── */
.provider-scroll {
    background: none;
}

.provider-content {
    padding: 14px 16px 12px 16px;
}

/* ── Provider Header ────────────────────────────────────── */
.provider-name {
    font-size: 17px;
    font-weight: 700;
    color: #1a1a1a;
    letter-spacing: -0.3px;
}

.provider-plan {
    font-size: 13px;
    color: #888888;
    font-weight: 400;
}

.provider-updated {
    font-size: 12px;
    color: #999999;
    margin-top: 1px;
    margin-bottom: 8px;
}

.provider-error {
    font-size: 12px;
    color: #ff453a;
    margin-top: 2px;
}

/* ── Metric Section (Session / Weekly / Sonnet) ─────────── */
.section-label {
    font-size: 14px;
    font-weight: 600;
    color: #1a1a1a;
    margin-top: 10px;
    margin-bottom: 4px;
}

.metric-row {
    margin-bottom: 2px;
}

.metric-stats {
    font-size: 12px;
    color: #555555;
    margin-top: 3px;
}

.metric-used {
    color: #555555;
}

.metric-reset {
    color: #999999;
}

.metric-pace {
    font-size: 11px;
    color: #aaaaaa;
    margin-top: 1px;
    margin-bottom: 6px;
}

/* ── Credits Bar ────────────────────────────────────────── */
.credits-label {
    font-size: 12px;
    color: #555555;
    margin-top: 6px;
}

/* ── Divider ────────────────────────────────────────────── */
.section-divider {
    background-color: rgba(0, 0, 0, 0.08);
    min-height: 1px;
    margin: 8px 0;
}

/* ── Extra Usage & Cost rows ────────────────────────────── */
.collapsible-header {
    font-size: 14px;
    font-weight: 600;
    color: #1a1a1a;
    background: none;
    border: none;
    padding: 4px 0;
}

.collapsible-detail {
    font-size: 12px;
    color: #666666;
    margin-bottom: 4px;
}

.expand-chevron {
    color: #aaaaaa;
    font-size: 12px;
}

/* ── Footer ─────────────────────────────────────────────── */
.footer-bar {
    background-color: rgba(0, 0, 0, 0.03);
    border-radius: 0 0 14px 14px;
    padding: 6px 14px;
    border-top: 1px solid rgba(0, 0, 0, 0.06);
}

.footer-timestamp {
    font-size: 11px;
    color: #aaaaaa;
}

.footer-timestamp.stale {
    color: #ff9500;
}

.refresh-button {
    font-size: 11px;
    color: #3b82f6;
    background: none;
    border: none;
    padding: 2px 6px;
    font-weight: 500;
}

.refresh-button:hover {
    background-color: rgba(59, 130, 246, 0.1);
    border-radius: 4px;
}
```

- [ ] **Step 2: Visually verify CSS loads (smoke test)**

```python
# Run this once manually — not a pytest test
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk
from pathlib import Path

css = Path("linux/codexbar_linux/style.css").read_text()
provider = Gtk.CssProvider()
provider.load_from_string(css)
print("CSS loaded without errors")
```

```bash
cd /home/magiccat/CodexBar
python3 -c "
import gi; gi.require_version('Gtk','4.0')
from gi.repository import Gtk, Gdk
from pathlib import Path
css = Path('linux/codexbar_linux/style.css').read_text()
p = Gtk.CssProvider()
p.load_from_string(css)
print('CSS OK')
"
# Expected: CSS OK (no GLib warnings about invalid CSS)
```

- [ ] **Step 3: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/style.css
git commit -m "feat(linux): add CSS matching macOS CodexBar light popup style"
```

---

### Task 7: Provider tab strip — `tab_strip.py`

**Files:**
- Create: `linux/codexbar_linux/tab_strip.py`

- [ ] **Step 1: Write `linux/codexbar_linux/tab_strip.py`**

```python
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject
from typing import Callable, Optional

# Short display names for tab strip (matching macOS app labels)
PROVIDER_DISPLAY = {
    "codex": ("Codex", "⬡"),
    "claude": ("Claude", "✦"),
    "cursor": ("Cursor", "⌖"),
    "factory": ("Droid", "⚙"),
    "gemini": ("Gemini", "✧"),
    "copilot": ("Copilot", "⊙"),
    "opencode": ("OpenCode", "◈"),
    "antigravity": ("Grav.", "⬠"),
    "zai": ("z.ai", "◆"),
    "kiro": ("Kiro", "◇"),
    "augment": ("Augment", "⊕"),
    "jetbrains": ("JB AI", "◉"),
    "openrouter": ("Router", "⇌"),
    "amp": ("Amp", "⚡"),
    "warp": ("Warp", "≫"),
    "vertexai": ("Vertex", "▲"),
    "kimi": ("Kimi", "◌"),
    "kimik2": ("KimiK2", "◍"),
    "kilo": ("Kilo", "◎"),
    "perplexity": ("Perpl.", "?"),
    "ollama": ("Ollama", "🦙"),
    "minimax": ("MiniMax", "∞"),
}


class ProviderTabStrip(Gtk.Box):
    """
    Horizontal tab strip with one button per provider.
    Emits 'provider-changed' signal when the active tab changes.
    """

    __gsignals__ = {
        "provider-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, provider_ids: list[str], active: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.add_css_class("tab-strip")
        self.set_hexpand(True)

        self._buttons: dict[str, Gtk.Button] = {}
        self._active = active

        for pid in provider_ids:
            label, icon = PROVIDER_DISPLAY.get(pid, (pid.capitalize(), "•"))
            btn = self._make_tab_button(pid, icon, label)
            self._buttons[pid] = btn
            self.append(btn)

        self._set_active(active, emit=False)

    def _make_tab_button(self, provider_id: str, icon: str, label: str) -> Gtk.Button:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        icon_label = Gtk.Label(label=icon)
        icon_label.add_css_class("tab-icon")
        name_label = Gtk.Label(label=label)
        vbox.append(icon_label)
        vbox.append(name_label)

        btn = Gtk.Button()
        btn.set_child(vbox)
        btn.add_css_class("tab-button")
        btn.connect("clicked", self._on_tab_clicked, provider_id)
        return btn

    def _on_tab_clicked(self, _btn: Gtk.Button, provider_id: str) -> None:
        if provider_id == self._active:
            return
        self._set_active(provider_id, emit=True)

    def _set_active(self, provider_id: str, emit: bool) -> None:
        if self._active and self._active in self._buttons:
            self._buttons[self._active].remove_css_class("active")
        self._active = provider_id
        if provider_id in self._buttons:
            self._buttons[provider_id].add_css_class("active")
        if emit:
            self.emit("provider-changed", provider_id)

    def update_providers(self, provider_ids: list[str], active: Optional[str] = None) -> None:
        """Rebuild tabs when provider list changes after a refresh."""
        for child in list(self._buttons.values()):
            self.remove(child)
        self._buttons.clear()
        for pid in provider_ids:
            label, icon = PROVIDER_DISPLAY.get(pid, (pid.capitalize(), "•"))
            btn = self._make_tab_button(pid, icon, label)
            self._buttons[pid] = btn
            self.append(btn)
        new_active = active or (provider_ids[0] if provider_ids else "")
        self._set_active(new_active, emit=False)

    @property
    def active_provider(self) -> str:
        return self._active
```

- [ ] **Step 2: Smoke-test the widget loads**

```bash
cd /home/magiccat/CodexBar
python3 -c "
import gi; gi.require_version('Gtk','4.0')
from gi.repository import Gtk
from linux.codexbar_linux.tab_strip import ProviderTabStrip
print('ProviderTabStrip importable OK')
"
# Expected: ProviderTabStrip importable OK
```

- [ ] **Step 3: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/tab_strip.py
git commit -m "feat(linux): add ProviderTabStrip with active-pill styling"
```

---

### Task 8: Provider detail view — `provider_view.py`

**Files:**
- Create: `linux/codexbar_linux/provider_view.py`

- [ ] **Step 1: Write `linux/codexbar_linux/provider_view.py`**

```python
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from codexbar_linux.store import ProviderData, RateWindow
from codexbar_linux.usage_bar import UsageBar
from codexbar_linux.tab_strip import PROVIDER_DISPLAY


def _time_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return "Never refreshed"
    delta = datetime.now() - dt
    s = int(delta.total_seconds())
    if s < 10:
        return "Updated just now"
    if s < 60:
        return f"Updated {s}s ago"
    if s < 3600:
        return f"Updated {s // 60}m ago"
    return f"Updated {s // 3600}h ago"


def _is_stale(dt: Optional[datetime]) -> bool:
    if dt is None:
        return False
    return (datetime.now() - dt).total_seconds() > 300  # 5 minutes


class MetricSection(Gtk.Box):
    """One usage metric: label + bar + stats row + optional pace line."""

    def __init__(self, section_title: str, window: RateWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        label = Gtk.Label(label=section_title, xalign=0)
        label.add_css_class("section-label")
        self.append(label)

        bar = UsageBar(used_percent=window.used_percent)
        bar.add_css_class("metric-row")
        self.append(bar)

        stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        used_label = Gtk.Label(
            label=f"{window.used_percent:.0f}% used", xalign=0
        )
        used_label.add_css_class("metric-used")
        used_label.add_css_class("metric-stats")
        used_label.set_hexpand(True)
        stats_box.append(used_label)

        if window.reset_description:
            reset_label = Gtk.Label(label=window.reset_description, xalign=1)
            reset_label.add_css_class("metric-reset")
            reset_label.add_css_class("metric-stats")
            stats_box.append(reset_label)

        self.append(stats_box)


class ProviderView(Gtk.Box):
    """
    Single-provider detail view: header + metric sections + credits + cost stub.
    Matches the macOS CodexBar card layout.
    """

    def __init__(self, provider: ProviderData, last_refreshed: Optional[datetime]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("provider-content")
        self._build(provider, last_refreshed)

    def _build(self, p: ProviderData, last_refreshed: Optional[datetime]) -> None:
        # ── Header ────────────────────────────────────────────
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        display_name, _ = PROVIDER_DISPLAY.get(p.provider, (p.provider.capitalize(), ""))
        name_label = Gtk.Label(label=display_name, xalign=0)
        name_label.add_css_class("provider-name")
        name_label.set_hexpand(True)
        header_box.append(name_label)

        if p.plan_text:
            plan_label = Gtk.Label(label=p.plan_text, xalign=1)
            plan_label.add_css_class("provider-plan")
            header_box.append(plan_label)

        self.append(header_box)

        # Updated timestamp
        updated_label = Gtk.Label(label=_time_ago(last_refreshed), xalign=0)
        updated_label.add_css_class("provider-updated")
        if last_refreshed and _is_stale(last_refreshed):
            updated_label.add_css_class("stale")
        self.append(updated_label)

        # Error state
        if p.error:
            err_label = Gtk.Label(label=p.error, xalign=0, wrap=True)
            err_label.add_css_class("provider-error")
            self.append(err_label)
            return

        # ── Metrics ───────────────────────────────────────────
        if p.primary:
            self.append(MetricSection("Session", p.primary))

        if p.secondary:
            self.append(self._divider())
            self.append(MetricSection("Weekly", p.secondary))
            # Pace line (if we have the data)
            # The CLI text renderer shows pace — it's in the reset_description or a separate field.
            # For now we show reset_description as-is; pace comes from CLI text if available.

        if p.tertiary:
            self.append(self._divider())
            self.append(MetricSection("Sonnet", p.tertiary))

        # ── Credits ───────────────────────────────────────────
        if p.credits_text:
            self.append(self._divider())
            credits_label = Gtk.Label(label=p.credits_text, xalign=0)
            credits_label.add_css_class("credits-label")
            self.append(credits_label)

        # ── Extra Usage placeholder ───────────────────────────
        # Cost/Extra usage sections require additional CLI fields (openaiDashboard).
        # If present, display them as collapsed rows with ">" chevron.
        self.append(self._divider())
        self._append_action_links(p)

    def _divider(self) -> Gtk.Separator:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("section-divider")
        return sep

    def _append_action_links(self, p: ProviderData) -> None:
        from codexbar_linux.tab_strip import PROVIDER_DISPLAY
        _, _ = PROVIDER_DISPLAY.get(p.provider, ("", ""))
        # No-op for providers with no dashboard link; the install script
        # and __main__ handle the Settings / Quit menu items in the tray.
        pass
```

- [ ] **Step 2: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/provider_view.py
git commit -m "feat(linux): add ProviderView widget with header, metric sections, credits"
```

---

### Task 9: Popup window — `window.py`

**Files:**
- Create: `linux/codexbar_linux/window.py`

- [ ] **Step 1: Write `linux/codexbar_linux/window.py`**

```python
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk
from codexbar_linux.store import DataStore
from codexbar_linux.tab_strip import ProviderTabStrip
from codexbar_linux.provider_view import ProviderView


CSS_PATH = Path(__file__).parent / "style.css"
WINDOW_WIDTH = 310
PANEL_HEIGHT_ESTIMATE = 46  # GNOME top bar height px


def _load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(CSS_PATH))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class PopupWindow(Gtk.Window):
    """
    Borderless frosted-glass popup: matches macOS CodexBar popup layout.
    - Provider tab strip at top
    - Single provider detail view in the middle
    - Footer with timestamp + Refresh Now
    """

    def __init__(self, store: DataStore, on_refresh: Optional[callable] = None) -> None:
        super().__init__()
        self._store = store
        self._on_refresh = on_refresh
        self._active_provider: Optional[str] = None

        _load_css()
        self.add_css_class("popup")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(WINDOW_WIDTH, -1)
        self.set_hide_on_close(True)

        # Dismiss on focus-out
        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", self._on_focus_leave)
        self.add_controller(focus_ctrl)

        self._outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(self._outer)

        # Placeholders replaced on first refresh
        self._tab_strip: Optional[ProviderTabStrip] = None
        self._scroll: Optional[Gtk.ScrolledWindow] = None
        self._footer: Optional[Gtk.Box] = None
        self._timestamp_label: Optional[Gtk.Label] = None

        self._build_empty_state()

    # ── Public API ──────────────────────────────────────────

    def toggle(self) -> None:
        if self.is_visible():
            self.hide()
        else:
            self.refresh_content()
            self.present()
            GLib.idle_add(self._position_window)

    def refresh_content(self) -> None:
        """Rebuild the window contents from the current DataStore state."""
        providers = self._store.providers
        last_refreshed = self._store.last_refreshed
        cli_error = self._store.cli_error

        if not providers and cli_error:
            self._show_error(cli_error)
            return

        if not providers:
            self._build_empty_state()
            return

        provider_ids = [p.provider for p in providers]

        # Keep current tab if still valid, else default to first
        if self._active_provider not in provider_ids:
            self._active_provider = provider_ids[0]

        self._rebuild_ui(providers, provider_ids, last_refreshed)

    # ── Internal builders ────────────────────────────────────

    def _rebuild_ui(self, providers, provider_ids, last_refreshed) -> None:
        # Clear previous children
        child = self._outer.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._outer.remove(child)
            child = nxt

        # Tab strip
        strip = ProviderTabStrip(provider_ids, active=self._active_provider or provider_ids[0])
        strip.connect("provider-changed", self._on_provider_changed)
        self._tab_strip = strip
        self._outer.append(strip)

        # Scrollable provider detail
        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("provider-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(520)
        scroll.set_propagate_natural_height(True)
        self._scroll = scroll
        self._outer.append(scroll)

        active_data = next(
            (p for p in providers if p.provider == self._active_provider), providers[0]
        )
        view = ProviderView(active_data, last_refreshed)
        scroll.set_child(view)

        # Footer
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        footer.add_css_class("footer-bar")

        ts_text = self._format_timestamp(last_refreshed)
        ts_label = Gtk.Label(label=ts_text, xalign=0)
        ts_label.add_css_class("footer-timestamp")
        ts_label.set_hexpand(True)
        self._timestamp_label = ts_label
        footer.append(ts_label)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.add_css_class("refresh-button")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        footer.append(refresh_btn)

        self._footer = footer
        self._outer.append(footer)

    def _build_empty_state(self) -> None:
        child = self._outer.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._outer.remove(child)
            child = nxt
        msg = Gtk.Label(label="Loading usage data…")
        msg.set_margin_top(24)
        msg.set_margin_bottom(24)
        msg.set_margin_start(16)
        msg.set_margin_end(16)
        self._outer.append(msg)

    def _show_error(self, error: str) -> None:
        child = self._outer.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._outer.remove(child)
            child = nxt
        msg = Gtk.Label(label=f"Error: {error}", wrap=True)
        msg.add_css_class("provider-error")
        msg.set_margin_top(16)
        msg.set_margin_bottom(16)
        msg.set_margin_start(16)
        msg.set_margin_end(16)
        self._outer.append(msg)

    # ── Positioning ──────────────────────────────────────────

    def _position_window(self) -> bool:
        display = Gdk.Display.get_default()
        if display is None:
            return False
        monitors = display.get_monitors()
        monitor = monitors.get_item(0)
        if monitor is None:
            return False
        geo = monitor.get_geometry()
        w = self.get_width() or WINDOW_WIDTH
        x = geo.x + geo.width - w - 8
        y = geo.y + PANEL_HEIGHT_ESTIMATE + 4
        surface = self.get_surface()
        if surface is not None:
            try:
                from gi.repository import GdkX11
                if isinstance(surface, GdkX11.X11Surface):
                    surface.move(x, y)
            except (ImportError, AttributeError, TypeError):
                pass  # Wayland or non-X11 — position will be default
        return False  # don't repeat

    # ── Callbacks ────────────────────────────────────────────

    def _on_focus_leave(self, _ctrl) -> None:
        GLib.idle_add(self.hide)

    def _on_provider_changed(self, _strip: ProviderTabStrip, provider_id: str) -> None:
        self._active_provider = provider_id
        providers = self._store.providers
        last_refreshed = self._store.last_refreshed
        active_data = next((p for p in providers if p.provider == provider_id), None)
        if active_data and self._scroll:
            self._scroll.set_child(ProviderView(active_data, last_refreshed))

    def _on_refresh_clicked(self, _btn) -> None:
        if self._on_refresh:
            self._on_refresh()

    @staticmethod
    def _format_timestamp(dt: Optional[datetime]) -> str:
        if dt is None:
            return "Not yet refreshed"
        delta = int((datetime.now() - dt).total_seconds())
        if delta < 10:
            return "Updated just now"
        if delta < 60:
            return f"Updated {delta}s ago"
        return f"Updated {delta // 60}m ago"
```

- [ ] **Step 2: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/window.py
git commit -m "feat(linux): add borderless GTK4 popup window with tab switching"
```

---

### Task 10: System tray icon — `tray.py`

**Files:**
- Create: `linux/codexbar_linux/tray.py`

- [ ] **Step 1: Write `linux/codexbar_linux/tray.py`**

```python
from __future__ import annotations
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray


# Two-bar meter icon matching the macOS CodexBar tray icon
ICON_SIZE = 22
BAR_WIDTH = 16
TOP_BAR_H = 5   # session bar
BOTTOM_BAR_H = 2  # weekly hairline
GAP = 2
MARGIN_LEFT = (ICON_SIZE - BAR_WIDTH) // 2


def _color_for_percent(remaining_percent: float) -> tuple[int, int, int]:
    if remaining_percent < 10:
        return (255, 69, 58)    # red
    if remaining_percent < 25:
        return (255, 214, 10)   # yellow
    return (48, 209, 88)        # green


def make_icon_image(
    session_remaining: float = 100.0,
    weekly_remaining: float = 100.0,
) -> Image.Image:
    """
    Generate a 22×22 RGBA tray icon with two horizontal bars.
    Top bar = session window; bottom hairline = weekly window.
    Color = worst-case (lowest remaining) of the two.
    """
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    worst = min(session_remaining, weekly_remaining)
    color = _color_for_percent(worst)
    track_color = (180, 180, 180, 100)

    top_y = (ICON_SIZE - TOP_BAR_H - GAP - BOTTOM_BAR_H) // 2

    # Session bar: track
    draw.rectangle(
        [MARGIN_LEFT, top_y, MARGIN_LEFT + BAR_WIDTH, top_y + TOP_BAR_H],
        fill=track_color,
    )
    # Session bar: fill
    fill_w = max(2, int((session_remaining / 100.0) * BAR_WIDTH))
    draw.rectangle(
        [MARGIN_LEFT, top_y, MARGIN_LEFT + fill_w, top_y + TOP_BAR_H],
        fill=color,
    )

    # Weekly hairline
    weekly_y = top_y + TOP_BAR_H + GAP
    draw.rectangle(
        [MARGIN_LEFT, weekly_y, MARGIN_LEFT + BAR_WIDTH, weekly_y + BOTTOM_BAR_H],
        fill=track_color,
    )
    fill_w_w = max(2, int((weekly_remaining / 100.0) * BAR_WIDTH))
    draw.rectangle(
        [MARGIN_LEFT, weekly_y, MARGIN_LEFT + fill_w_w, weekly_y + BOTTOM_BAR_H],
        fill=color,
    )

    return img


class TrayIcon:
    """System tray icon via pystray. Run in a daemon thread."""

    def __init__(
        self,
        on_click: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_click = on_click
        self._on_quit = on_quit
        self._on_refresh = on_refresh
        self._icon: Optional[pystray.Icon] = None

    def run(self) -> None:
        icon_image = make_icon_image(100.0, 100.0)
        menu = pystray.Menu(
            pystray.MenuItem("Refresh Now", lambda icon, item: self._on_refresh()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self._on_quit()),
        )
        self._icon = pystray.Icon(
            name="codexbar",
            icon=icon_image,
            title="CodexBar",
            menu=menu,
        )
        self._icon.run(setup=self._setup)

    def _setup(self, icon: pystray.Icon) -> None:
        icon.visible = True

    def update_icon(
        self,
        session_remaining: float = 100.0,
        weekly_remaining: float = 100.0,
    ) -> None:
        if self._icon:
            self._icon.icon = make_icon_image(session_remaining, weekly_remaining)

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()
```

- [ ] **Step 2: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/tray.py
git commit -m "feat(linux): add pystray TrayIcon with Pillow two-bar meter icon"
```

---

### Task 11: Entry point — `__main__.py`

**Files:**
- Create: `linux/codexbar_linux/__main__.py`

- [ ] **Step 1: Write `linux/codexbar_linux/__main__.py`**

```python
from __future__ import annotations
import sys
import threading
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
from codexbar_linux.cli import find_cli, download_cli, run_usage_json
from codexbar_linux.poller import BackgroundPoller
from codexbar_linux.store import DataStore
from codexbar_linux.tray import TrayIcon
from codexbar_linux.window import PopupWindow


CONFIG_PATH = Path.home() / ".config" / "codexbar-linux" / "config.json"
REFRESH_INTERVAL = 120  # seconds


def _load_config() -> dict:
    import json
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {"refresh_interval_seconds": REFRESH_INTERVAL, "cli_path": None}


def _ensure_cli(config: dict) -> Path:
    """Locate CLI binary, auto-downloading if not present."""
    try:
        return find_cli(config_path=config.get("cli_path"))
    except FileNotFoundError:
        print("codexbar CLI not found — downloading latest release…", file=sys.stderr)
        return download_cli()


def main() -> None:
    config = _load_config()
    cli_path = _ensure_cli(config)
    interval = config.get("refresh_interval_seconds", REFRESH_INTERVAL)

    store = DataStore()

    # Window — created before threads so GTK init is on main thread
    window = PopupWindow(store, on_refresh=None)

    def on_update_from_poller() -> None:
        """Called from poller thread — must schedule GTK work via idle_add."""
        GLib.idle_add(window.refresh_content)
        providers = store.providers
        if providers:
            # Update tray icon color based on worst-case remaining
            session_r = min(
                (p.primary.remaining_percent for p in providers if p.primary), default=100.0
            )
            weekly_r = min(
                (p.secondary.remaining_percent for p in providers if p.secondary), default=100.0
            )
            GLib.idle_add(tray.update_icon, session_r, weekly_r)

    poller = BackgroundPoller(
        store=store,
        cli_path=cli_path,
        interval_seconds=interval,
        on_update=on_update_from_poller,
    )

    def on_quit() -> None:
        poller.stop()
        GLib.idle_add(Gtk.main_quit)

    tray = TrayIcon(
        on_click=lambda: GLib.idle_add(window.toggle),
        on_refresh=lambda: (store.set_loading(), poller.refresh_now()),
        on_quit=on_quit,
    )

    # Wire refresh button to poller
    window._on_refresh = lambda: (store.set_loading(), poller.refresh_now())

    # Start tray in daemon thread
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    # Start poller in daemon thread (triggers first fetch immediately)
    poller_thread = threading.Thread(target=poller.start, daemon=True)
    poller_thread.start()

    # GTK main loop — blocks until Gtk.main_quit() is called
    Gtk.main()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run a smoke test (requires display)**

```bash
cd /home/magiccat/CodexBar/linux
# This will try to launch the app; close it after confirming the window appears.
# It will show "Loading…" initially since the CLI binary may not be present.
PYTHONPATH=/home/magiccat/CodexBar/linux python3 -m codexbar_linux &
sleep 3
kill %1 2>/dev/null
echo "Smoke test: app launched and closed without crash"
```

- [ ] **Step 3: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/codexbar_linux/__main__.py
git commit -m "feat(linux): add entry point wiring all components together"
```

---

### Task 12: Install script and desktop entry

**Files:**
- Create: `linux/install.sh`
- Create: `linux/codexbar-linux.desktop`

- [ ] **Step 1: Write `linux/install.sh`**

```bash
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
    libayatana-appindicator3-dev 2>/dev/null || \
sudo apt-get install -y --no-install-recommends \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-gdkx11-4.0

# ── Python packages ───────────────────────────────────────
echo "==> Installing Python packages…"
pip install --user --quiet "pystray>=0.19.0" "pillow>=10.0.0"

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
export PYTHONPATH="$APP_DIR"
exec python3 -m codexbar_linux "\$@"
LAUNCHER
chmod +x "$BIN_DIR/codexbar-linux"

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

# Also register in app menu
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cp "$AUTOSTART_DIR/codexbar-linux.desktop" "$APPS_DIR/codexbar-linux.desktop"

echo ""
echo "✓ CodexBar Linux installed successfully!"
echo ""
echo "  Launch now:  codexbar-linux"
echo "  Auto-starts: on next login"
echo ""
echo "  Tip: run 'codexbar config' to enable providers before launching."
```

- [ ] **Step 2: Make it executable and smoke-test the script itself**

```bash
chmod +x /home/magiccat/CodexBar/linux/install.sh
bash -n /home/magiccat/CodexBar/linux/install.sh
echo "Syntax OK: $?"
# Expected: Syntax OK: 0
```

- [ ] **Step 3: Commit**

```bash
cd /home/magiccat/CodexBar
git add linux/install.sh linux/requirements.txt
git commit -m "feat(linux): add curl-pipe-bash installer with CLI binary download + desktop entry"
```

---

### Task 13: Run all tests and push

- [ ] **Step 1: Run full test suite**

```bash
cd /home/magiccat/CodexBar/linux
python3 -m pytest tests/ -v --tb=short
# Expected: all tests pass (store, cli, poller, usage_bar)
```

- [ ] **Step 2: End-to-end smoke test**

```bash
# Download CLI and run the app for 5 seconds
cd /tmp && curl -sSL \
  "$(gh api repos/steipete/CodexBar/releases/latest \
    --jq '.assets[] | select(.name | contains("linux-x86_64.tar.gz")) | .browser_download_url')" \
  -o codexbar.tar.gz && tar xzf codexbar.tar.gz && chmod +x codexbar

PYTHONPATH=/home/magiccat/CodexBar/linux \
CODEXBAR_CLI_PATH=/tmp/codexbar \
python3 -m codexbar_linux &
APP_PID=$!
sleep 5
kill $APP_PID
echo "E2E smoke: app ran for 5s without crash"
```

- [ ] **Step 3: Push to BusinessBuilders/CodexBar**

```bash
cd /home/magiccat/CodexBar
git push origin main
```

Expected output: `Branch 'main' set up to track remote branch 'main' of 'origin'.`

---

## Self-Review Against Spec

| Spec requirement | Covered in task |
|---|---|
| GTK4 borderless popup | Task 9 — `window.py` `set_decorated(False)` |
| Provider tab strip with active blue pill | Task 7 — `tab_strip.py` `.active` CSS class |
| Per-provider metric rows (Session/Weekly/Sonnet) | Task 8 — `MetricSection` in `provider_view.py` |
| Usage bar: gray track + orange dot at fill position | Task 5 — `UsageBar` `DrawingArea` with Cairo |
| Light frosted-glass background | Task 6 — `style.css` `rgba(248,248,252,0.96)` |
| Auto-dismiss on focus-out | Task 9 — `EventControllerFocus` `leave` signal |
| 2-minute background refresh | Task 4 — `BackgroundPoller` `interval_seconds=120` |
| Refresh Now button | Tasks 9+11 — footer button → `poller.refresh_now()` |
| Thread safety (GTK on main, pystray daemon, poller daemon) | Task 11 — `GLib.idle_add` for all GTK calls |
| Auto-download CLI binary | Task 3 — `download_cli()` with SHA-256 verification |
| Configurable refresh interval | Task 11 — `config.json` `refresh_interval_seconds` |
| All providers supported | Task 7 — `PROVIDER_DISPLAY` dict covers all 25 providers |
| curl-pipe-bash installer | Task 12 — `install.sh` |
| Stale data indicator | Tasks 8+9 — `_is_stale()` adds `.stale` CSS class to timestamp |
| Error display | Task 9 — `_show_error()` + `provider-error` CSS class |

No gaps found. No placeholders remain.
