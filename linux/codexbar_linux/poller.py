from __future__ import annotations
import threading
from pathlib import Path
from typing import Callable, Optional

from codexbar_linux import cli as cli_module
from codexbar_linux.store import DataStore


class BackgroundPoller:
    """Daemon thread that periodically fetches usage data and updates DataStore."""

    def __init__(
        self,
        store: DataStore,
        cli_path: Path,
        interval_seconds: float,
        on_update: Optional[Callable[[], None]],
        fetch_fn: Optional[Callable] = None,
    ) -> None:
        self._store = store
        self._cli_path = cli_path
        self._interval = interval_seconds
        self._on_update = on_update
        self._fetch_fn = fetch_fn or cli_module.run_usage_json
        self._stop_event = threading.Event()
        self._refresh_event = threading.Event()

    def start(self) -> None:
        """Entry point for the daemon thread. Runs until stop() is called."""
        while not self._stop_event.is_set():
            self._run_fetch()
            self._refresh_event.wait(timeout=self._interval)
            self._refresh_event.clear()

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_event.set()  # unblock the wait

    def refresh_now(self) -> None:
        """Trigger an immediate out-of-cycle fetch."""
        self._refresh_event.set()

    def _run_fetch(self) -> None:
        self._store.set_loading()
        providers, error = self._fetch_fn(self._cli_path)
        self._store.update(providers, error=error)
        if self._on_update:
            self._on_update()
