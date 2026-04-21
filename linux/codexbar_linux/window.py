from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
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


def _default_window_origin(monitor_x: int, monitor_y: int, monitor_width: int, window_width: int) -> tuple[int, int]:
    return (monitor_x + monitor_width - window_width - 8, monitor_y + PANEL_HEIGHT_ESTIMATE + 4)


def _clamp_window_origin(
    x: int,
    y: int,
    monitor_x: int,
    monitor_y: int,
    monitor_width: int,
    monitor_height: int,
    window_width: int,
    window_height: int,
) -> tuple[int, int]:
    max_x = max(monitor_x, monitor_x + monitor_width - max(window_width, 1))
    max_y = max(monitor_y, monitor_y + monitor_height - max(window_height, 1))
    return (
        min(max(x, monitor_x), max_x),
        min(max(y, monitor_y), max_y),
    )


@dataclass
class WindowDragState:
    manual_origin: Optional[tuple[int, int]] = None
    _drag_origin: Optional[tuple[int, int]] = None

    def begin(self, origin: tuple[int, int]) -> None:
        self._drag_origin = origin

    def update(self, offset_x: float, offset_y: float) -> Optional[tuple[int, int]]:
        if self._drag_origin is None:
            return None
        return (
            int(self._drag_origin[0] + offset_x),
            int(self._drag_origin[1] + offset_y),
        )

    def end(self, offset_x: float, offset_y: float) -> Optional[tuple[int, int]]:
        origin = self.update(offset_x, offset_y)
        self.manual_origin = origin
        self._drag_origin = None
        return origin


@dataclass(frozen=True)
class FocusBehavior:
    auto_hide_on_focus_leave: bool = False

    def should_hide_on_focus_leave(self) -> bool:
        return self.auto_hide_on_focus_leave


@dataclass(frozen=True)
class WindowChromeState:
    title: str = "CodexBar"
    draggable_from_header: bool = True
    minimize_hides_to_tray: bool = True


def _load_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_PATH.read_bytes())
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class PopupWindow(Gtk.Window):
    def __init__(self, store: DataStore, on_refresh: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self._store = store
        self._on_refresh = on_refresh
        self._active_provider: Optional[str] = None
        self._drag_state = WindowDragState()
        self._focus_behavior = FocusBehavior()
        self._chrome_state = WindowChromeState()
        self._window_origin: Optional[tuple[int, int]] = None

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
        self._header_bar = self._build_header_bar()
        self._outer.append(self._header_bar)
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._outer.append(self._content_box)

        self._tab_strip: Optional[ProviderTabStrip] = None
        self._scroll: Optional[Gtk.ScrolledWindow] = None
        self._footer: Optional[Gtk.Box] = None
        self._timestamp_label: Optional[Gtk.Label] = None

        self._build_empty_state()

    def _build_header_bar(self) -> Gtk.Box:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("window-header")

        drag_handle = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        drag_handle.add_css_class("window-drag-handle")
        drag_handle.set_hexpand(True)

        title = Gtk.Label(label=self._chrome_state.title, xalign=0)
        title.add_css_class("window-title")
        drag_handle.append(title)

        if self._chrome_state.draggable_from_header:
            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", self._on_drag_begin)
            drag.connect("drag-update", self._on_drag_update)
            drag.connect("drag-end", self._on_drag_end)
            drag_handle.add_controller(drag)

        header.append(drag_handle)

        minimize_button = Gtk.Button(label="—")
        minimize_button.add_css_class("window-minimize")
        minimize_button.connect("clicked", self._on_minimize_clicked)
        header.append(minimize_button)
        return header

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
        child = self._content_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._content_box.remove(child)
            child = nxt

        strip = ProviderTabStrip(provider_ids, active=self._active_provider or provider_ids[0])
        strip.connect("provider-changed", self._on_provider_changed)
        self._tab_strip = strip
        self._content_box.append(strip)

        scroll = Gtk.ScrolledWindow()
        scroll.add_css_class("provider-scroll")
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(520)
        scroll.set_propagate_natural_height(True)
        self._scroll = scroll
        self._content_box.append(scroll)

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
        self._content_box.append(footer)

    def _build_empty_state(self) -> None:
        child = self._content_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._content_box.remove(child)
            child = nxt
        msg = Gtk.Label(label="Loading usage data…")
        msg.set_margin_top(24)
        msg.set_margin_bottom(24)
        msg.set_margin_start(16)
        msg.set_margin_end(16)
        self._content_box.append(msg)

    def _show_error(self, error: str) -> None:
        child = self._content_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._content_box.remove(child)
            child = nxt
        msg = Gtk.Label(label=f"Error: {error}", wrap=True)
        msg.add_css_class("provider-error")
        msg.set_margin_top(16)
        msg.set_margin_bottom(16)
        msg.set_margin_start(16)
        msg.set_margin_end(16)
        self._content_box.append(msg)

    def _position_window(self) -> bool:
        if self._drag_state.manual_origin is not None:
            self._move_window(*self._drag_state.manual_origin)
            return False

        origin = self._default_origin_for_display()
        if origin is None:
            return False
        self._move_window(*origin)
        return False

    def _default_origin_for_display(self) -> Optional[tuple[int, int]]:
        display = Gdk.Display.get_default()
        if display is None:
            return None
        surface = self.get_surface()
        monitor = display.get_monitor_at_surface(surface) if surface is not None else None
        if monitor is None:
            monitors = display.get_monitors()
            monitor = monitors.get_item(0)
        if monitor is None:
            return None
        geo = monitor.get_geometry()
        w = self.get_width() or WINDOW_WIDTH
        h = self.get_height() or 1
        x, y = _default_window_origin(geo.x, geo.y, geo.width, w)
        return _clamp_window_origin(
            x=x,
            y=y,
            monitor_x=geo.x,
            monitor_y=geo.y,
            monitor_width=geo.width,
            monitor_height=geo.height,
            window_width=w,
            window_height=h,
        )

    def _move_window(self, x: int, y: int) -> None:
        self._window_origin = (x, y)
        surface = self.get_surface()
        if surface is not None:
            try:
                from gi.repository import GdkX11
                if isinstance(surface, GdkX11.X11Surface):
                    surface.move(x, y)
            except (ImportError, AttributeError, TypeError):
                pass

    def _on_focus_leave(self, _ctrl) -> None:
        if self._focus_behavior.should_hide_on_focus_leave():
            GLib.idle_add(self.hide)

    def _on_drag_begin(self, _gesture: Gtk.GestureDrag, _start_x: float, _start_y: float) -> None:
        origin = self._window_origin or self._drag_state.manual_origin or self._default_origin_for_display()
        if origin is not None:
            self._drag_state.begin(origin)

    def _on_drag_update(self, _gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        origin = self._drag_state.update(offset_x, offset_y)
        if origin is not None:
            self._move_window(*origin)

    def _on_drag_end(self, _gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        origin = self._drag_state.end(offset_x, offset_y)
        if origin is not None:
            self._move_window(*origin)

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

    def _on_minimize_clicked(self, _btn) -> None:
        if self._chrome_state.minimize_hides_to_tray:
            self.hide()

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
