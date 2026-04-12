from __future__ import annotations
from datetime import datetime
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
    return (datetime.now() - dt).total_seconds() > 300


class MetricSection(Gtk.Box):
    def __init__(self, section_title: str, window: RateWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        label = Gtk.Label(label=section_title, xalign=0)
        label.add_css_class("section-label")
        self.append(label)

        bar = UsageBar(used_percent=window.used_percent)
        bar.add_css_class("metric-row")
        self.append(bar)

        stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        used_label = Gtk.Label(label=f"{window.used_percent:.0f}% used", xalign=0)
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
    def __init__(self, provider: ProviderData, last_refreshed: Optional[datetime]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("provider-content")
        self._build(provider, last_refreshed)

    def _build(self, p: ProviderData, last_refreshed: Optional[datetime]) -> None:
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

        updated_label = Gtk.Label(label=_time_ago(last_refreshed), xalign=0)
        updated_label.add_css_class("provider-updated")
        if last_refreshed and _is_stale(last_refreshed):
            updated_label.add_css_class("stale")
        self.append(updated_label)

        if p.error:
            err_label = Gtk.Label(label=p.error, xalign=0, wrap=True)
            err_label.add_css_class("provider-error")
            self.append(err_label)
            return

        if p.primary:
            self.append(MetricSection("Session", p.primary))

        if p.secondary:
            self.append(self._divider())
            self.append(MetricSection("Weekly", p.secondary))

        if p.tertiary:
            self.append(self._divider())
            self.append(MetricSection("Sonnet", p.tertiary))

        if p.credits_text:
            self.append(self._divider())
            credits_label = Gtk.Label(label=p.credits_text, xalign=0)
            credits_label.add_css_class("credits-label")
            self.append(credits_label)

        self.append(self._divider())

    def _divider(self) -> Gtk.Separator:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("section-divider")
        return sep
