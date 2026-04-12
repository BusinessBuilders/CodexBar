import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from codexbar_linux.poller import BackgroundPoller
from codexbar_linux.store import DataStore, ProviderData, RateWindow


def _make_provider() -> ProviderData:
    return ProviderData(
        provider="claude", account=None, source="oauth",
        status_indicator="none",
        primary=RateWindow(2.0, 98.0, None, None),
        secondary=None, tertiary=None,
        credits_text=None, credits_remaining=None, plan_text=None, error=None,
    )


def test_poller_updates_store_on_start():
    store = DataStore()
    called = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        called.set()
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    assert called.wait(timeout=2.0), "Poller did not call fetch within 2s"
    time.sleep(0.05)
    assert len(store.providers) == 1


def test_poller_calls_on_update_callback():
    store = DataStore()
    callback_called = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=lambda: callback_called.set(),
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    assert callback_called.wait(timeout=2.0)


def test_poller_stores_error_on_failure():
    store = DataStore()
    done = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        done.set()
        return ([], "CLI not found")

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    done.wait(timeout=2.0)
    time.sleep(0.05)
    assert store.cli_error == "CLI not found"


def test_refresh_now_triggers_immediate_fetch():
    store = DataStore()
    fetch_count = [0]
    second_fetch = threading.Event()

    def fake_fetch(cli_path, timeout=30):
        fetch_count[0] += 1
        if fetch_count[0] == 2:
            second_fetch.set()
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=60,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    time.sleep(0.1)
    poller.refresh_now()
    assert second_fetch.wait(timeout=2.0), "refresh_now() did not trigger second fetch"


def test_poller_stop():
    store = DataStore()
    fetch_count = [0]

    def fake_fetch(cli_path, timeout=30):
        fetch_count[0] += 1
        return ([_make_provider()], None)

    poller = BackgroundPoller(
        store=store,
        cli_path=Path("/fake/codexbar"),
        interval_seconds=0.05,
        on_update=None,
        fetch_fn=fake_fetch,
    )
    t = threading.Thread(target=poller.start, daemon=True)
    t.start()
    time.sleep(0.2)
    poller.stop()
    count_at_stop = fetch_count[0]
    time.sleep(0.2)
    assert fetch_count[0] == count_at_stop, "Poller continued after stop()"
