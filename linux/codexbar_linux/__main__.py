from __future__ import annotations
import sys
import threading
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
from codexbar_linux.cli import find_cli, download_cli
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

    window = PopupWindow(store, on_refresh=None)

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

    window._on_refresh = lambda: (store.set_loading(), poller.refresh_now())

    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    poller_thread = threading.Thread(target=poller.start, daemon=True)
    poller_thread.start()

    Gtk.main()


if __name__ == "__main__":
    main()
