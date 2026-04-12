from __future__ import annotations
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray


ICON_SIZE = 22
BAR_WIDTH = 16
TOP_BAR_H = 5
BOTTOM_BAR_H = 2
GAP = 2
MARGIN_LEFT = (ICON_SIZE - BAR_WIDTH) // 2


def _color_for_percent(remaining_percent: float) -> tuple[int, int, int]:
    if remaining_percent < 10:
        return (255, 69, 58)
    if remaining_percent < 25:
        return (255, 214, 10)
    return (48, 209, 88)


def make_icon_image(
    session_remaining: float = 100.0,
    weekly_remaining: float = 100.0,
) -> Image.Image:
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    worst = min(session_remaining, weekly_remaining)
    color = _color_for_percent(worst)
    track_color = (180, 180, 180, 100)

    top_y = (ICON_SIZE - TOP_BAR_H - GAP - BOTTOM_BAR_H) // 2

    draw.rectangle(
        [MARGIN_LEFT, top_y, MARGIN_LEFT + BAR_WIDTH, top_y + TOP_BAR_H],
        fill=track_color,
    )
    fill_w = max(2, int((session_remaining / 100.0) * BAR_WIDTH))
    draw.rectangle(
        [MARGIN_LEFT, top_y, MARGIN_LEFT + fill_w, top_y + TOP_BAR_H],
        fill=color,
    )

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
            pystray.MenuItem("Refresh Now", lambda _icon, _item: self._on_refresh()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda _icon, _item: self._on_quit()),
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
