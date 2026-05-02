from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

from codexbar_linux.cli import download_cli, find_cli
from codexbar_linux.poller import BackgroundPoller
from codexbar_linux.store import DataStore, ProviderData, RateWindow

CONFIG_PATH = Path.home() / ".config" / "codexbar-linux" / "config.json"
DEFAULT_REFRESH_INTERVAL = 120

REQUIRED_PROVIDER_SPECS = (
    ("qwen_local", "Qwen Local", "ollama", "primary", "secondary"),
    ("glm", "GLM 5.1", "zai", "primary", "secondary"),
    ("glm_air", "GLM 4.7", "alibaba", "primary", "secondary"),
    ("codex", "Codex", "codex", "primary", "secondary"),
    ("gemini_pro", "Gemini Pro", "gemini", "primary", None),
    ("gemini_flash", "Gemini Flash", "gemini", "secondary", None),
)

NATIVE_PROVIDER_DISPLAY_NAMES = {
    "codex": "Codex",
    "claude": "Claude",
    "cursor": "Cursor",
    "factory": "Droid",
    "gemini": "Gemini",
    "copilot": "Copilot",
    "opencode": "OpenCode",
    "antigravity": "Grav.",
    "zai": "z.ai",
    "kiro": "Kiro",
    "augment": "Augment",
    "jetbrains": "JB AI",
    "openrouter": "Router",
    "amp": "Amp",
    "warp": "Warp",
    "vertexai": "Vertex",
    "kimi": "Kimi",
    "kimik2": "KimiK2",
    "kilo": "Kilo",
    "perplexity": "Perpl.",
    "ollama": "Ollama",
    "minimax": "MiniMax",
}


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _window_payload(window: Optional[RateWindow]) -> Optional[dict]:
    if window is None or not window.resets_at:
        return None
    return {
        "used": int(round(window.used_percent)),
        "limit": 100,
        "resetAt": window.resets_at,
    }


def _provider_payload(
    provider_id: str,
    display_name: str,
    provider: Optional[ProviderData],
    session_window: Optional[RateWindow],
    weekly_window: Optional[RateWindow],
) -> dict:
    payload = {
        "id": provider_id,
        "displayName": display_name,
        "available": provider is not None and not provider.error,
    }
    session = _window_payload(session_window)
    weekly = _window_payload(weekly_window)
    if session is not None:
        payload["session"] = session
    if weekly is not None:
        payload["weekly"] = weekly
    return payload


def _window_for(provider: Optional[ProviderData], attribute: Optional[str]) -> Optional[RateWindow]:
    if provider is None or attribute is None:
        return None
    return getattr(provider, attribute)


def _fallback_display_name(provider_id: str) -> str:
    return provider_id.replace("_", " ").title()


def build_quota_payload(
    providers: list[ProviderData],
    fetched_at: Optional[datetime],
    ttl_seconds: int = 60,
) -> dict:
    by_provider = {provider.provider: provider for provider in providers}
    payload_providers: dict[str, dict] = {}

    stamp = fetched_at or datetime.now(timezone.utc)

    for provider_id, display_name, source_provider_id, session_attr, weekly_attr in REQUIRED_PROVIDER_SPECS:
        provider = by_provider.get(source_provider_id)
        payload_providers[provider_id] = _provider_payload(
            provider_id,
            display_name,
            provider,
            _window_for(provider, session_attr),
            _window_for(provider, weekly_attr),
        )

    for provider_id, display_name in NATIVE_PROVIDER_DISPLAY_NAMES.items():
        if provider_id in payload_providers:
            continue
        provider = by_provider.get(provider_id)
        payload_providers[provider_id] = _provider_payload(
            provider_id,
            display_name,
            provider,
            _window_for(provider, "primary"),
            _window_for(provider, "secondary"),
        )

    for provider_id, provider in by_provider.items():
        if provider_id in payload_providers:
            continue
        payload_providers[provider_id] = _provider_payload(
            provider_id,
            _fallback_display_name(provider_id),
            provider,
            _window_for(provider, "primary"),
            _window_for(provider, "secondary"),
        )

    return {
        "fetchedAt": _iso_utc(stamp),
        "ttlSeconds": ttl_seconds,
        "providers": payload_providers,
    }


def make_handler(store: DataStore, ttl_seconds: int):
    class QuotaHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/quota":
                self.send_error(404)
                return

            payload = build_quota_payload(
                providers=store.providers,
                fetched_at=store.last_refreshed,
                ttl_seconds=ttl_seconds,
            )
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] == "/quota":
                self.send_response(405)
                self.send_header("Allow", "GET")
                self.end_headers()
                return
            self.send_error(404)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    return QuotaHandler


class QuotaServer:
    def __init__(
        self,
        store: DataStore,
        host: str = "127.0.0.1",
        port: int = 8787,
        ttl_seconds: int = 60,
    ) -> None:
        self._server = ThreadingHTTPServer((host, port), make_handler(store, ttl_seconds))
        self._thread: Optional[threading.Thread] = None

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {
        "refresh_interval_seconds": DEFAULT_REFRESH_INTERVAL,
        "cli_path": None,
        "quota_server_enabled": True,
        "quota_server_host": "127.0.0.1",
        "quota_server_port": 8787,
        "quota_server_ttl_seconds": 60,
    }


def resolve_cli(config: dict, cli_path_override: Optional[str] = None) -> Path:
    configured_path = cli_path_override or config.get("cli_path")
    try:
        return find_cli(config_path=configured_path)
    except FileNotFoundError:
        print("codexbar CLI not found — downloading latest release…", file=sys.stderr)
        return download_cli()


class QuotaService:
    def __init__(
        self,
        cli_path: Path,
        host: str = "127.0.0.1",
        port: int = 8787,
        ttl_seconds: int = 60,
        refresh_interval_seconds: float = DEFAULT_REFRESH_INTERVAL,
        fetch_fn: Optional[Callable] = None,
    ) -> None:
        self._store = DataStore()
        self._server = QuotaServer(
            store=self._store,
            host=host,
            port=port,
            ttl_seconds=ttl_seconds,
        )
        self._poller = BackgroundPoller(
            store=self._store,
            cli_path=cli_path,
            interval_seconds=refresh_interval_seconds,
            on_update=None,
            fetch_fn=fetch_fn,
        )
        self._poller_thread: Optional[threading.Thread] = None

    @property
    def server_address(self) -> tuple[str, int]:
        return self._server.server_address

    def start(self) -> None:
        self._server.start()
        if self._poller_thread is not None:
            return
        self._poller_thread = threading.Thread(target=self._poller.start, daemon=True)
        self._poller_thread.start()

    def stop(self) -> None:
        self._poller.stop()
        if self._poller_thread is not None:
            try:
                self._poller_thread.join(timeout=2.0)
            except KeyboardInterrupt:
                pass
            self._poller_thread = None
        self._server.stop()

    def serve_forever(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                self.stop()
            except KeyboardInterrupt:
                pass


def main(argv: Optional[list[str]] = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description="Run the CodexBar Linux quota API server.")
    parser.add_argument("--host", default=str(config.get("quota_server_host", "127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(config.get("quota_server_port", 8787)))
    parser.add_argument("--ttl-seconds", type=int, default=int(config.get("quota_server_ttl_seconds", 60)))
    parser.add_argument(
        "--refresh-interval-seconds",
        type=float,
        default=float(config.get("refresh_interval_seconds", DEFAULT_REFRESH_INTERVAL)),
    )
    parser.add_argument("--cli-path", default=config.get("cli_path"))
    args = parser.parse_args(argv)

    cli_path: Path
    try:
        cli_path = resolve_cli(config, cli_path_override=args.cli_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to resolve codexbar CLI: {exc}", file=sys.stderr)
        fallback = args.cli_path or str(Path.home() / ".local" / "share" / "codexbar-linux" / "bin" / "codexbar")
        cli_path = Path(fallback)

    service = QuotaService(
        cli_path=cli_path,
        host=str(args.host),
        port=int(args.port),
        ttl_seconds=int(args.ttl_seconds),
        refresh_interval_seconds=float(args.refresh_interval_seconds),
    )
    host, port = service.server_address
    print(f"Serving quota API on http://{host}:{port}/quota", file=sys.stderr)
    service.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
