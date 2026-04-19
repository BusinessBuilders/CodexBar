from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

_WORKER = Path(__file__).parent / "tray_worker.py"


class TrayIcon:
    """
    Manages the system tray icon via a subprocess.

    The worker (tray_worker.py) runs AyatanaAppIndicator3 (GTK3) in its own
    process so it doesn't conflict with the main app's GTK4 imports.
    JSON lines on stdin/stdout are used for bidirectional communication.
    """

    def __init__(
        self,
        on_click: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_click = on_click
        self._on_quit = on_quit
        self._on_refresh = on_refresh
        self._proc: Optional[subprocess.Popen[str]] = None

    def run(self) -> None:
        """Start subprocess and block reading events (call from a daemon thread)."""
        self._proc = subprocess.Popen(
            [sys.executable, str(_WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = evt.get("event")
            if event == "click":
                self._on_click()
            elif event == "refresh":
                self._on_refresh()
            elif event == "quit":
                self._on_quit()
                break

    def update_icon(
        self,
        session_remaining: float = 100.0,
        weekly_remaining: float = 100.0,
    ) -> None:
        if self._proc and self._proc.poll() is None:
            self._send({"cmd": "update_icon", "session": session_remaining, "weekly": weekly_remaining})

    def stop(self) -> None:
        if self._proc:
            self._send({"cmd": "quit"})
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def _send(self, cmd: dict) -> None:  # type: ignore[type-arg]
        if self._proc and self._proc.poll() is None:
            assert self._proc.stdin is not None
            try:
                self._proc.stdin.write(json.dumps(cmd) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
