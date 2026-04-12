from __future__ import annotations
import hashlib
import json
import platform
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Optional

from codexbar_linux.store import ProviderData, RateWindow

GITHUB_RELEASES_API = "https://api.github.com/repos/steipete/CodexBar/releases/latest"
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "share" / "codexbar-linux" / "bin"


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    raise RuntimeError(f"Unsupported architecture: {machine}")


def find_cli(
    config_path: Optional[str] = None,
    search_install_dir: Path = DEFAULT_INSTALL_DIR,
) -> Path:
    """Locate the codexbar binary: config path > install dir > PATH."""
    if config_path:
        p = Path(config_path)
        if p.is_file():
            return p
    installed = search_install_dir / "codexbar"
    if installed.is_file():
        return installed
    found = shutil.which("codexbar")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "codexbar CLI not found. Run linux/install.sh to install it."
    )


def download_cli(install_dir: Path = DEFAULT_INSTALL_DIR) -> Path:
    """Download the latest codexbar CLI binary for the current arch."""
    arch = _arch()
    req = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.load(resp)

    tag = release["tag_name"]
    asset_name = f"CodexBarCLI-{tag}-linux-{arch}.tar.gz"
    sha_name = f"{asset_name}.sha256"

    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    if asset_name not in assets:
        raise RuntimeError(f"No Linux binary for {arch} in release {tag}")

    install_dir.mkdir(parents=True, exist_ok=True)
    tarball = install_dir / asset_name

    with urllib.request.urlopen(assets[asset_name], timeout=120) as resp:
        tarball.write_bytes(resp.read())

    with urllib.request.urlopen(assets[sha_name], timeout=30) as resp:
        expected_sha = resp.read().decode().split()[0]

    actual_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        tarball.unlink()
        raise RuntimeError(f"SHA-256 mismatch for {asset_name}: download corrupted")

    with tarfile.open(tarball) as tf:
        tf.extractall(install_dir)

    binary = install_dir / "codexbar"
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    tarball.unlink()
    return binary


def _parse_rate_window(data: Optional[dict]) -> Optional[RateWindow]:
    if not data:
        return None
    return RateWindow(
        used_percent=float(data.get("usedPercent", 0.0)),
        remaining_percent=float(data.get("remainingPercent", 100.0)),
        resets_at=data.get("resetsAt"),
        reset_description=data.get("resetDescription"),
    )


def parse_providers(raw: list[dict]) -> list[ProviderData]:
    """Convert raw CLI JSON payload list to ProviderData list."""
    result = []
    for item in raw:
        usage = item.get("usage") or {}
        status = item.get("status") or {}
        credits = item.get("credits")
        error_payload = item.get("error")

        credits_remaining: Optional[float] = None
        credits_text: Optional[str] = None
        if credits and credits.get("remaining") is not None:
            credits_remaining = float(credits["remaining"])
            code = credits.get("currencyCode", "USD")
            if code == "Quota":
                credits_text = f"{credits_remaining:.0f} quota remaining"
            else:
                credits_text = f"${credits_remaining:.2f} remaining"

        result.append(ProviderData(
            provider=item.get("provider", "unknown"),
            account=item.get("account"),
            source=item.get("source", ""),
            status_indicator=status.get("indicator", "none"),
            primary=_parse_rate_window(usage.get("primary")),
            secondary=_parse_rate_window(usage.get("secondary")),
            tertiary=_parse_rate_window(usage.get("tertiary")),
            credits_text=credits_text,
            credits_remaining=credits_remaining,
            plan_text=usage.get("planText"),
            error=error_payload.get("message") if error_payload else None,
        ))
    return result


def run_usage_json(
    cli_path: Path,
    timeout: int = 30,
) -> tuple[list[ProviderData], Optional[str]]:
    """Run `codexbar usage --json`, return (providers, error_string)."""
    try:
        result = subprocess.run(
            [str(cli_path), "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return [], result.stderr.strip() or f"CLI exit code {result.returncode}"
        raw = json.loads(result.stdout)
        return parse_providers(raw), None
    except subprocess.TimeoutExpired:
        return [], f"CLI timed out after {timeout}s"
    except json.JSONDecodeError as exc:
        return [], f"Invalid JSON from CLI: {exc}"
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
