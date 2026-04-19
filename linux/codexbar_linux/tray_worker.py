"""
Tray icon subprocess — runs in isolation with GTK3 + AyatanaAppIndicator3.
Communicates with the main (GTK4) process via JSON lines on stdin/stdout.

stdin  commands: {"cmd": "update_icon", "session": float, "weekly": float}
                 {"cmd": "quit"}
stdout events:   {"event": "click"}
                 {"event": "refresh"}
                 {"event": "quit"}
"""
from __future__ import annotations
import json
import sys
import threading
from pathlib import Path

import gi
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Gtk", "3.0")
from gi.repository import AyatanaAppIndicator3, GLib, Gtk
from PIL import Image, ImageDraw

# ── Icon generation ──────────────────────────────────────────────────────────

ICON_SIZE = 22
BAR_WIDTH = 16
TOP_BAR_H = 5
BOTTOM_BAR_H = 2
GAP = 2
MARGIN_LEFT = (ICON_SIZE - BAR_WIDTH) // 2
ICON_DIR = Path.home() / ".config" / "codexbar-linux" / "icons"
ICON_DIR.mkdir(parents=True, exist_ok=True)


def _color_for_percent(pct: float) -> tuple[int, int, int]:
    if pct < 10:
        return (255, 69, 58)
    if pct < 25:
        return (255, 214, 10)
    return (48, 209, 88)


def _write_icon(session: float, weekly: float, slot: int) -> str:
    """Render icon to disk and return the icon name (without .png)."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = _color_for_percent(min(session, weekly))
    track = (180, 180, 180, 100)
    top_y = (ICON_SIZE - TOP_BAR_H - GAP - BOTTOM_BAR_H) // 2
    draw.rectangle([MARGIN_LEFT, top_y, MARGIN_LEFT + BAR_WIDTH, top_y + TOP_BAR_H], fill=track)
    fw = max(2, int((session / 100.0) * BAR_WIDTH))
    draw.rectangle([MARGIN_LEFT, top_y, MARGIN_LEFT + fw, top_y + TOP_BAR_H], fill=color)
    wy = top_y + TOP_BAR_H + GAP
    draw.rectangle([MARGIN_LEFT, wy, MARGIN_LEFT + BAR_WIDTH, wy + BOTTOM_BAR_H], fill=track)
    fww = max(2, int((weekly / 100.0) * BAR_WIDTH))
    draw.rectangle([MARGIN_LEFT, wy, MARGIN_LEFT + fww, wy + BOTTOM_BAR_H], fill=color)
    name = f"codexbar-{slot}"
    img.save(str(ICON_DIR / f"{name}.png"))
    return name


# ── AppIndicator setup ───────────────────────────────────────────────────────

_slot = 0
_initial_name = _write_icon(100.0, 100.0, _slot)

indicator = AyatanaAppIndicator3.Indicator.new(
    "codexbar",
    _initial_name,
    AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
)
indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
indicator.set_icon_theme_path(str(ICON_DIR))


def _emit(event: str) -> None:
    print(json.dumps({"event": event}), flush=True)


# ── GTK3 menu ────────────────────────────────────────────────────────────────

menu = Gtk.Menu()

_item_show = Gtk.MenuItem(label="Show / Hide")
_item_show.connect("activate", lambda _: _emit("click"))
menu.append(_item_show)

menu.append(Gtk.SeparatorMenuItem())

_item_refresh = Gtk.MenuItem(label="Refresh Now")
_item_refresh.connect("activate", lambda _: _emit("refresh"))
menu.append(_item_refresh)

menu.append(Gtk.SeparatorMenuItem())

_item_quit = Gtk.MenuItem(label="Quit")
_item_quit.connect("activate", lambda _: _emit("quit"))
menu.append(_item_quit)

menu.show_all()
indicator.set_menu(menu)


# ── Command handler (called on GLib main thread) ─────────────────────────────

def _handle_command(cmd: dict) -> bool:
    global _slot
    if cmd.get("cmd") == "update_icon":
        _slot = 1 - _slot
        name = _write_icon(
            float(cmd.get("session", 100.0)),
            float(cmd.get("weekly", 100.0)),
            _slot,
        )
        indicator.set_icon_full(name, "CodexBar usage")
    elif cmd.get("cmd") == "quit":
        Gtk.main_quit()
    return False


# ── stdin reader thread ──────────────────────────────────────────────────────

def _stdin_reader() -> None:
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                GLib.idle_add(_handle_command, json.loads(raw))
            except json.JSONDecodeError:
                pass
    finally:
        GLib.idle_add(Gtk.main_quit)


threading.Thread(target=_stdin_reader, daemon=True).start()

Gtk.main()
