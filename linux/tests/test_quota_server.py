import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from codexbar_linux.quota_server import QuotaServer, QuotaService, build_quota_payload
from codexbar_linux.store import DataStore, ProviderData, RateWindow


def _make_provider(
    provider: str,
    primary: RateWindow | None = None,
    secondary: RateWindow | None = None,
    error: str | None = None,
) -> ProviderData:
    return ProviderData(
        provider=provider,
        account=None,
        source="test",
        status_indicator="none",
        primary=primary,
        secondary=secondary,
        tertiary=None,
        credits_text=None,
        credits_remaining=None,
        plan_text=None,
        error=error,
    )


def test_build_quota_payload_maps_required_ids_and_windows():
    session_reset = "2026-04-22T18:00:00Z"
    weekly_reset = "2026-04-28T00:00:00Z"
    payload = build_quota_payload(
        providers=[
            _make_provider("ollama"),
            _make_provider(
                "claude",
                primary=RateWindow(12.0, 88.0, session_reset, None),
                secondary=RateWindow(44.0, 56.0, weekly_reset, None),
            ),
            _make_provider(
                "zai",
                primary=RateWindow(40.0, 60.0, session_reset, None),
                secondary=RateWindow(30.0, 70.0, weekly_reset, None),
            ),
            _make_provider("alibaba"),
            _make_provider("codex", error="timed out"),
            _make_provider(
                "gemini",
                primary=RateWindow(94.0, 6.0, session_reset, None),
                secondary=RateWindow(17.0, 83.0, weekly_reset, None),
            ),
            _make_provider("mystery"),
        ],
        fetched_at=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
        ttl_seconds=60,
    )

    assert {
        "qwen_local",
        "glm",
        "glm_air",
        "codex",
        "gemini_pro",
        "gemini_flash",
        "claude",
        "cursor",
        "gemini",
        "mystery",
    } <= set(payload["providers"].keys())
    assert payload["providers"]["qwen_local"]["displayName"] == "Qwen Local"
    assert payload["providers"]["glm"]["session"] == {
        "used": 40,
        "limit": 100,
        "resetAt": session_reset,
    }
    assert payload["providers"]["glm"]["weekly"] == {
        "used": 30,
        "limit": 100,
        "resetAt": weekly_reset,
    }
    assert payload["providers"]["codex"]["available"] is False
    assert payload["providers"]["gemini_pro"]["session"]["used"] == 94
    assert payload["providers"]["gemini_flash"]["session"]["used"] == 17
    assert payload["providers"]["gemini"]["weekly"]["used"] == 17
    assert payload["providers"]["claude"]["session"]["used"] == 12
    assert payload["providers"]["claude"]["weekly"]["used"] == 44
    assert payload["providers"]["cursor"] == {
        "id": "cursor",
        "displayName": "Cursor",
        "available": False,
    }
    assert payload["providers"]["mystery"] == {
        "id": "mystery",
        "displayName": "Mystery",
        "available": True,
    }


def test_build_quota_payload_omits_missing_optional_windows_and_marks_unavailable():
    payload = build_quota_payload(
        providers=[
            _make_provider("zai"),
        ],
        fetched_at=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
        ttl_seconds=60,
    )

    assert payload["providers"]["qwen_local"] == {
        "id": "qwen_local",
        "displayName": "Qwen Local",
        "available": False,
    }
    assert payload["providers"]["glm"] == {
        "id": "glm",
        "displayName": "GLM 5.1",
        "available": True,
    }
    assert payload["providers"]["codex"] == {
        "id": "codex",
        "displayName": "Codex",
        "available": False,
    }
    assert payload["providers"]["claude"] == {
        "id": "claude",
        "displayName": "Claude",
        "available": False,
    }


def test_quota_server_serves_quota_json():
    store = DataStore()
    store.update([
        _make_provider(
            "gemini",
            primary=RateWindow(94.0, 6.0, "2026-04-22T18:00:00Z", None),
            secondary=None,
        ),
    ])
    server = QuotaServer(store, host="127.0.0.1", port=0, ttl_seconds=60)
    server.start()
    host, port = server.server_address

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/quota", timeout=2) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["ttlSeconds"] == 60
        assert payload["providers"]["gemini_pro"]["session"] == {
            "used": 94,
            "limit": 100,
            "resetAt": "2026-04-22T18:00:00Z",
        }
    finally:
        server.stop()


def test_quota_server_rejects_non_get():
    store = DataStore()
    server = QuotaServer(store, host="127.0.0.1", port=0, ttl_seconds=60)
    server.start()
    host, port = server.server_address

    request = urllib.request.Request(
        f"http://{host}:{port}/quota",
        method="POST",
        data=b"{}",
    )
    try:
        try:
            urllib.request.urlopen(request, timeout=2)
            raise AssertionError("Expected HTTP 405")
        except urllib.error.HTTPError as error:
            assert error.code == 405
            assert error.headers["Allow"] == "GET"
    finally:
        server.stop()


def test_quota_service_starts_polling_and_serves_quota():
    def fake_fetch(_cli_path: Path, _timeout: int = 30):
        return ([
            _make_provider(
                "gemini",
                primary=RateWindow(88.0, 12.0, "2026-04-22T18:00:00Z", None),
            ),
        ], None)

    service = QuotaService(
        cli_path=Path("/fake/codexbar"),
        host="127.0.0.1",
        port=0,
        ttl_seconds=75,
        refresh_interval_seconds=60,
        fetch_fn=fake_fetch,
    )
    service.start()
    host, port = service.server_address

    try:
        deadline = time.time() + 2.0
        last_payload = None
        while time.time() < deadline:
            with urllib.request.urlopen(f"http://{host}:{port}/quota", timeout=2) as response:
                last_payload = json.loads(response.read().decode("utf-8"))
            if "session" in last_payload["providers"]["gemini_pro"]:
                break
            time.sleep(0.05)

        assert last_payload is not None
        assert last_payload["ttlSeconds"] == 75
        assert last_payload["providers"]["gemini_pro"]["session"] == {
            "used": 88,
            "limit": 100,
            "resetAt": "2026-04-22T18:00:00Z",
        }
    finally:
        service.stop()


def test_quota_service_stop_ignores_keyboard_interrupt_during_join():
    service = QuotaService(
        cli_path=Path("/fake/codexbar"),
        host="127.0.0.1",
        port=0,
        ttl_seconds=60,
        refresh_interval_seconds=60,
        fetch_fn=lambda _cli_path, _timeout=30: ([], None),
    )

    class InterruptingThread:
        def join(self, timeout: float) -> None:
            raise KeyboardInterrupt

    stopped = {"poller": False, "server": False}

    service._poller = type("PollerStub", (), {"stop": lambda self: stopped.__setitem__("poller", True)})()
    service._server = type(
        "ServerStub",
        (),
        {
            "stop": lambda self: stopped.__setitem__("server", True),
            "server_address": ("127.0.0.1", 8787),
        },
    )()
    service._poller_thread = InterruptingThread()

    service.stop()

    assert stopped == {"poller": True, "server": True}
    assert service._poller_thread is None
