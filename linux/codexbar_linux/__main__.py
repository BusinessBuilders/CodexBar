from __future__ import annotations
import sys
import threading
from pathlib import Path
from typing import Optional
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib
from codexbar_linux.cli import find_cli, download_cli
from codexbar_linux.poller import BackgroundPoller
from codexbar_linux.store import DataStore
from codexbar_linux.tray import TrayIcon
from codexbar_linux.window import PopupWindow


CONFIG_PATH = Path.home() / ".config" / "codexbar-linux" / "config.json"
REFRESH_INTERVAL = 120  # seconds


def _load_config() -> dict:  # type: ignore[type-arg]
    import json
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {"refresh_interval_seconds": REFRESH_INTERVAL, "cli_path": None}


def _resolve_cli(config: dict) -> Path:  # type: ignore[type-arg]
    """Locate CLI binary, auto-downloading if not present."""
    try:
        return find_cli(config_path=config.get("cli_path"))
    except FileNotFoundError:
        print("codexbar CLI not found — downloading latest release…", file=sys.stderr)
        return download_cli()


def main() -> None:
    config = _load_config()
    store = DataStore()
    loop = GLib.MainLoop()
    window = PopupWindow(store, on_refresh=None)

    _poller: Optional[BackgroundPoller] = None

    def on_update_from_poller() -> None:
        GLib.idle_add(window.refresh_content)
        providers = store.providers
        if providers:
            session_r = min(
                (p.primary.remaining_percent for p in providers if p.primary), default=100.0
            )
            weekly_r = min(
                (p.secondary.remaining_percent for p in providers if p.secondary), default=100.0
            )
            GLib.idle_add(tray.update_icon, session_r, weekly_r)

    def _do_refresh() -> None:
        store.set_loading()
        if _poller is not None:
            _poller.refresh_now()

    def on_quit() -> None:
        if _poller is not None:
            _poller.stop()
        GLib.idle_add(loop.quit)

    tray = TrayIcon(
        on_click=lambda: GLib.idle_add(window.toggle),
        on_refresh=_do_refresh,
        on_quit=on_quit,
    )
    window._on_refresh = _do_refresh

    # Start tray immediately — don't wait for CLI
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    # Show the window immediately on first launch
    GLib.idle_add(window.present)
    GLib.idle_add(window.refresh_content)

    def _start_poller() -> None:
        """Resolve CLI (may download) then start polling — runs on background thread."""
        nonlocal _poller
        try:
            cli_path = _resolve_cli(config)
        except Exception as exc:
            store.update([], error=str(exc))
            GLib.idle_add(window.refresh_content)
            return
        interval = int(config.get("refresh_interval_seconds", REFRESH_INTERVAL))
        _poller = BackgroundPoller(
            store=store,
            cli_path=cli_path,
            interval_seconds=interval,
            on_update=on_update_from_poller,
        )
        _poller.start()

    threading.Thread(target=_start_poller, daemon=True).start()

    loop.run()


if __name__ == "__main__":
    main()
