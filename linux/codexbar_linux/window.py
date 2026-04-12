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
PANEL_HEIGHT_ESTIMATE = 46


def _load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_path(str(CSS_PATH))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class PopupWindow(Gtk.Window):
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

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", self._on_focus_leave)
        self.add_controller(focus_ctrl)

        self._outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(self._outer)

        self._tab_strip: Optional[ProviderTabStrip] = None
        self._scroll: Optional[Gtk.ScrolledWindow] = None
        self._footer: Optional[Gtk.Box] = None
        self._timestamp_label: Optional[Gtk.Label] = None

        self._build_empty_state()

    def toggle(self) -> None:
        if self.is_visible():
            self.hide()
        else:
            self.refresh_content()
            self.present()
            GLib.idle_add(self._position_window)

    def refresh_content(self) -> None:
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

        if self._active_provider not in provider_ids:
            self._active_provider = provider_ids[0]

        self._rebuild_ui(providers, provider_ids, last_refreshed)

    def _rebuild_ui(self, providers, provider_ids, last_refreshed) -> None:
        child = self._outer.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._outer.remove(child)
            child = nxt

        strip = ProviderTabStrip(provider_ids, active=self._active_provider or provider_ids[0])
        strip.connect("provider-changed", self._on_provider_changed)
        self._tab_strip = strip
        self._outer.append(strip)

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
                pass
        return False

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
