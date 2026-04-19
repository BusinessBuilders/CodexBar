from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GObject
from typing import Optional

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
