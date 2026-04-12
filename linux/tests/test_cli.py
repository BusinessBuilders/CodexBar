from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from codexbar_linux.cli import parse_providers, find_cli, run_usage_json
from codexbar_linux.store import ProviderData
from tests.conftest import load_fixture


def test_parse_claude_provider():
    data = load_fixture("usage.json")
    providers = parse_providers(data)
    assert len(providers) == 2

    claude = providers[0]
    assert isinstance(claude, ProviderData)
    assert claude.provider == "claude"
    assert claude.account == "user@example.com"
    assert claude.status_indicator == "none"
    assert claude.plan_text == "Max"
    assert claude.error is None

    assert claude.primary is not None
    assert claude.primary.used_percent == 2.0
    assert claude.primary.remaining_percent == 98.0
    assert claude.primary.reset_description == "Resets in 3h 53m"

    assert claude.secondary is not None
    assert claude.secondary.used_percent == 3.0

    assert claude.tertiary is not None
    assert claude.tertiary.used_percent == 0.0


def test_parse_codex_with_credits():
    data = load_fixture("usage.json")
    providers = parse_providers(data)
    codex = providers[1]

    assert codex.provider == "codex"
    assert codex.credits_remaining == 12.40
    assert codex.credits_text == "$12.40 remaining"
    assert codex.status_indicator == "minor"
    assert codex.secondary is None


def test_parse_null_usage_fields():
    data = [{"provider": "cursor", "account": None, "version": None,
              "source": "cookie", "status": None, "usage": None,
              "credits": None, "antigravityPlanInfo": None,
              "openaiDashboard": None, "error": None}]
    providers = parse_providers(data)
    assert providers[0].primary is None
    assert providers[0].secondary is None
    assert providers[0].status_indicator == "none"


def test_parse_provider_with_error():
    data = [{"provider": "gemini", "account": None, "version": None,
              "source": "oauth", "status": None, "usage": None,
              "credits": None, "antigravityPlanInfo": None,
              "openaiDashboard": None,
              "error": {"message": "Token expired", "kind": "auth"}}]
    providers = parse_providers(data)
    assert providers[0].error == "Token expired"


def test_run_usage_json_timeout():
    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli._fallback_usage_providers", return_value=([], None)):
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)
    assert payloads == []
    assert "timed out" in error.lower()


def test_run_usage_json_bad_json():
    """If CLI returns non-JSON, we get a clean error string."""
    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli._fallback_usage_providers", return_value=([], None)):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        payloads, error = run_usage_json(Path("/fake/codexbar"))
    assert payloads == []
    assert error is not None


def test_run_usage_json_falls_back_to_codex_oauth_when_cli_times_out():
    auth_payload = {
        "tokens": {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "account_id": "acct-123",
        }
    }
    usage_payload = {
        "email": "user@example.com",
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {
                "used_percent": 16,
                "reset_at": 1_776_033_521,
                "limit_window_seconds": 18_000,
            },
            "secondary_window": {
                "used_percent": 3,
                "reset_at": 1_776_620_321,
                "limit_window_seconds": 604_800,
            },
        },
        "credits": {
            "has_credits": False,
            "unlimited": False,
            "balance": "0",
        },
    }

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = __import__("json").dumps(usage_payload).encode()

    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli.Path.read_text", return_value=__import__("json").dumps(auth_payload)), \
            patch("codexbar_linux.cli.Path.exists", return_value=True), \
            patch("codexbar_linux.cli.urllib.request.urlopen", return_value=mock_response):
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)

    assert error is None
    assert len(payloads) == 1
    codex = payloads[0]
    assert codex.provider == "codex"
    assert codex.account == "user@example.com"
    assert codex.plan_text == "Plus"
    assert codex.primary is not None
    assert codex.primary.used_percent == 16.0
    assert codex.primary.remaining_percent == 84.0
    assert codex.secondary is not None
    assert codex.secondary.used_percent == 3.0
    assert codex.secondary.remaining_percent == 97.0


def test_run_usage_json_falls_back_to_claude_oauth_when_cli_times_out():
    claude_credentials = {
        "claudeAiOauth": {
            "accessToken": "claude-token",
            "rateLimitTier": "default_claude_max_5x",
            "subscriptionType": "max",
        }
    }
    claude_usage = {
        "five_hour": {
            "utilization": 40.0,
            "resets_at": "2026-04-12T23:00:00+00:00",
        },
        "seven_day": {
            "utilization": 20.0,
            "resets_at": "2026-04-17T12:00:00+00:00",
        },
        "seven_day_sonnet": {
            "utilization": 10.0,
            "resets_at": "2026-04-19T15:00:00+00:00",
        },
    }

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = __import__("json").dumps(claude_usage).encode()

    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli._load_codex_auth_payload", return_value=None), \
            patch("codexbar_linux.cli.Path.read_text", return_value=__import__("json").dumps(claude_credentials)), \
            patch("codexbar_linux.cli.urllib.request.urlopen", return_value=mock_response):
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)

    assert error is None
    assert len(payloads) == 1
    claude = payloads[0]
    assert claude.provider == "claude"
    assert claude.source == "oauth"
    assert claude.plan_text == "Max"
    assert claude.primary is not None
    assert claude.primary.used_percent == 40.0
    assert claude.primary.remaining_percent == 60.0
    assert claude.secondary is not None
    assert claude.secondary.used_percent == 20.0
    assert claude.tertiary is not None
    assert claude.tertiary.used_percent == 10.0


def test_run_usage_json_falls_back_to_zai_api_when_cli_times_out():
    config_payload = {
        "providers": [
            {"id": "zai", "apiKey": "zai-key", "enabled": True, "source": "api"}
        ]
    }
    zai_usage = {
        "code": 200,
        "msg": "Operation successful",
        "success": True,
        "data": {
            "limits": [
                {
                    "type": "TOKENS_LIMIT",
                    "unit": 3,
                    "number": 5,
                    "percentage": 4,
                    "nextResetTime": 1776027246354,
                },
                {
                    "type": "TOKENS_LIMIT",
                    "unit": 6,
                    "number": 1,
                    "percentage": 2,
                    "nextResetTime": 1776629341998,
                },
                {
                    "type": "TIME_LIMIT",
                    "unit": 5,
                    "number": 1,
                    "usage": 1000,
                    "currentValue": 6,
                    "remaining": 994,
                    "percentage": 1,
                    "nextResetTime": 1776288541997,
                },
            ]
        },
    }

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = __import__("json").dumps(zai_usage).encode()

    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli._load_codex_auth_payload", return_value=None), \
            patch("codexbar_linux.cli._load_claude_credentials_payload", return_value=None), \
            patch("codexbar_linux.cli.Path.read_text", return_value=__import__("json").dumps(config_payload)), \
            patch("codexbar_linux.cli.urllib.request.urlopen", return_value=mock_response):
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)

    assert error is None
    assert len(payloads) == 1
    zai = payloads[0]
    assert zai.provider == "zai"
    assert zai.source == "api"
    assert zai.primary is not None
    assert zai.primary.used_percent == 4.0
    assert zai.primary.remaining_percent == 96.0
    assert zai.secondary is not None
    assert zai.secondary.used_percent == 2.0
    assert zai.secondary.remaining_percent == 98.0


def test_run_usage_json_returns_multiple_fallback_providers():
    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli._fetch_codex_oauth_provider", return_value=ProviderData(
                provider="codex",
                account=None,
                source="oauth",
                status_indicator="none",
                primary=None,
                secondary=None,
                tertiary=None,
                credits_text=None,
                credits_remaining=None,
                plan_text="Plus",
                error=None,
            )), \
            patch("codexbar_linux.cli._fetch_claude_oauth_provider", return_value=ProviderData(
                provider="claude",
                account=None,
                source="oauth",
                status_indicator="none",
                primary=None,
                secondary=None,
                tertiary=None,
                credits_text=None,
                credits_remaining=None,
                plan_text="Max",
                error=None,
            )), \
            patch("codexbar_linux.cli._fetch_gemini_provider", return_value=ProviderData(
                provider="gemini",
                account=None,
                source="oauth",
                status_indicator="none",
                primary=None,
                secondary=None,
                tertiary=None,
                credits_text=None,
                credits_remaining=None,
                plan_text="Paid",
                error=None,
            )), \
            patch("codexbar_linux.cli._fetch_zai_provider", return_value=None):
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)

    assert error is None
    assert [provider.provider for provider in payloads] == ["codex", "claude", "gemini"]


def test_run_usage_json_returns_gemini_fallback_provider():
    with patch("codexbar_linux.cli.subprocess.run") as mock_run, \
            patch("codexbar_linux.cli._patch_binary_for_glibc235"), \
            patch("codexbar_linux.cli._ensure_glibc_shim", return_value=None), \
            patch("codexbar_linux.cli._fetch_codex_oauth_provider", return_value=None), \
            patch("codexbar_linux.cli._fetch_claude_oauth_provider", return_value=None), \
            patch("codexbar_linux.cli._fetch_zai_provider", return_value=None), \
            patch("codexbar_linux.cli._fetch_gemini_provider", return_value=ProviderData(
                provider="gemini",
                account="gemini@example.com",
                source="oauth",
                status_indicator="none",
                primary=None,
                secondary=None,
                tertiary=None,
                credits_text=None,
                credits_remaining=None,
                plan_text="Paid",
                error=None,
            ), create=True):
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)

    assert error is None
    assert [provider.provider for provider in payloads] == ["gemini"]


def test_find_cli_in_path(tmp_path):
    fake_binary = tmp_path / "codexbar"
    fake_binary.write_text("#!/bin/bash\necho ok")
    fake_binary.chmod(0o755)
    result = find_cli(config_path=str(fake_binary))
    assert result == fake_binary


def test_find_cli_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="codexbar CLI not found"):
        find_cli(config_path=str(tmp_path / "nonexistent"), search_install_dir=tmp_path)
