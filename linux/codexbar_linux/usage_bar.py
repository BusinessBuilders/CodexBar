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

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
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
        import math
        cr.new_sub_path()
        cr.arc(x + r, y + r, r, math.pi, 3.0 * math.pi / 2.0)
        cr.arc(x + w - r, y + r, r, 3.0 * math.pi / 2.0, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2.0)
        cr.arc(x + r, y + h - r, r, math.pi / 2.0, math.pi)
        cr.close_path()
