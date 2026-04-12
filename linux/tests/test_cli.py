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
    with patch("codexbar_linux.cli.subprocess.run") as mock_run:
        mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="codexbar", timeout=0.01)
        payloads, error = run_usage_json(Path("/fake/codexbar"), timeout=0.01)
    assert payloads == []
    assert "timed out" in error.lower()


def test_run_usage_json_bad_json():
    """If CLI returns non-JSON, we get a clean error string."""
    with patch("codexbar_linux.cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
        payloads, error = run_usage_json(Path("/fake/codexbar"))
    assert payloads == []
    assert error is not None


def test_find_cli_in_path(tmp_path):
    fake_binary = tmp_path / "codexbar"
    fake_binary.write_text("#!/bin/bash\necho ok")
    fake_binary.chmod(0o755)
    result = find_cli(config_path=str(fake_binary))
    assert result == fake_binary


def test_find_cli_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="codexbar CLI not found"):
        find_cli(config_path=str(tmp_path / "nonexistent"), search_install_dir=tmp_path)
