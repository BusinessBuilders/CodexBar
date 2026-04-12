import threading
import time
from codexbar_linux.store import DataStore, ProviderData, RateWindow


def _make_provider(name: str = "claude") -> ProviderData:
    return ProviderData(
        provider=name,
        account="user@example.com",
        source="oauth",
        status_indicator="none",
        primary=RateWindow(used_percent=2.0, remaining_percent=98.0,
                           resets_at="2026-04-12T18:00:00Z", reset_description="Resets in 3h 53m"),
        secondary=RateWindow(used_percent=3.0, remaining_percent=97.0,
                             resets_at="2026-04-19T00:00:00Z", reset_description="Resets in 3d 20h"),
        tertiary=None,
        credits_text=None,
        credits_remaining=None,
        plan_text="Max",
        error=None,
    )


def test_initial_state():
    store = DataStore()
    assert store.providers == []
    assert store.last_refreshed is None
    assert store.is_loading is False
    assert store.cli_error is None


def test_update_stores_providers():
    store = DataStore()
    providers = [_make_provider("claude"), _make_provider("codex")]
    store.update(providers)
    assert len(store.providers) == 2
    assert store.providers[0].provider == "claude"
    assert store.last_refreshed is not None
    assert store.is_loading is False


def test_set_loading():
    store = DataStore()
    store.set_loading()
    assert store.is_loading is True


def test_update_clears_loading():
    store = DataStore()
    store.set_loading()
    store.update([_make_provider()])
    assert store.is_loading is False


def test_update_with_error():
    store = DataStore()
    store.update([], error="CLI timed out")
    assert store.cli_error == "CLI timed out"
    assert store.providers == []


def test_thread_safety():
    """Concurrent reads and writes must not raise or corrupt data."""
    store = DataStore()
    errors = []

    def writer():
        for _ in range(50):
            store.update([_make_provider("claude")])
            time.sleep(0.001)

    def reader():
        for _ in range(50):
            try:
                _ = store.providers
                _ = store.last_refreshed
            except Exception as e:
                errors.append(e)
            time.sleep(0.001)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader),
               threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_providers_returns_copy():
    """Mutating the returned list must not affect the store."""
    store = DataStore()
    store.update([_make_provider()])
    p = store.providers
    p.clear()
    assert len(store.providers) == 1
