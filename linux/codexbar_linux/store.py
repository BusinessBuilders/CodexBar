from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class RateWindow:
    used_percent: float
    remaining_percent: float
    resets_at: Optional[str] = None
    reset_description: Optional[str] = None


@dataclass
class ProviderData:
    provider: str
    account: Optional[str]
    source: str
    status_indicator: str  # "none" | "minor" | "major" | "critical" | "maintenance"
    primary: Optional[RateWindow]    # session window
    secondary: Optional[RateWindow]  # weekly window
    tertiary: Optional[RateWindow]   # sonnet/opus window
    credits_text: Optional[str]
    credits_remaining: Optional[float]
    plan_text: Optional[str]
    error: Optional[str]


class DataStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._providers: list[ProviderData] = []
        self._last_refreshed: Optional[datetime] = None
        self._is_loading: bool = False
        self._cli_error: Optional[str] = None

    def update(self, providers: list[ProviderData], error: Optional[str] = None) -> None:
        with self._lock:
            self._providers = list(providers)
            self._last_refreshed = datetime.now()
            self._is_loading = False
            self._cli_error = error

    def set_loading(self) -> None:
        with self._lock:
            self._is_loading = True

    @property
    def providers(self) -> list[ProviderData]:
        with self._lock:
            return list(self._providers)

    @property
    def last_refreshed(self) -> Optional[datetime]:
        with self._lock:
            return self._last_refreshed

    @property
    def is_loading(self) -> bool:
        with self._lock:
            return self._is_loading

    @property
    def cli_error(self) -> Optional[str]:
        with self._lock:
            return self._cli_error
