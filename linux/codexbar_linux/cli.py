from __future__ import annotations
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

from codexbar_linux.store import ProviderData, RateWindow

GITHUB_RELEASES_API = "https://api.github.com/repos/steipete/CodexBar/releases/latest"
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "share" / "codexbar-linux" / "bin"

# ── GLIBC 2.38 compatibility shim ────────────────────────────────────────────
# The pre-built CodexBarCLI binary requires GLIBC 2.38 (Ubuntu 24.04).
# On older systems (Ubuntu 22.04 = GLIBC 2.35), we compile a tiny LD_PRELOAD
# shim that provides the 8 missing symbols so the binary runs unchanged.

_GLIBC_SHIM_SRC = r"""
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <dlfcn.h>

/* strlcpy / strlcat — added to glibc in 2.38 */
static size_t _strlcpy(char *dst, const char *src, size_t size) {
    size_t srclen = strlen(src);
    if (size > 0) {
        size_t n = srclen < size - 1 ? srclen : size - 1;
        memcpy(dst, src, n);
        dst[n] = '\0';
    }
    return srclen;
}
__asm__(".symver _strlcpy,strlcpy@GLIBC_2.38");

static size_t _strlcat(char *dst, const char *src, size_t size) {
    size_t dstlen = strnlen(dst, size);
    if (dstlen == size) return size + strlen(src);
    return dstlen + _strlcpy(dst + dstlen, src, size - dstlen);
}
__asm__(".symver _strlcat,strlcat@GLIBC_2.38");

/* __isoc23_* — C23 standard variants (identical for our purposes) */
static long _isoc23_strtol(const char *s, char **e, int b) { return strtol(s, e, b); }
__asm__(".symver _isoc23_strtol,__isoc23_strtol@GLIBC_2.38");

static long long _isoc23_strtoll(const char *s, char **e, int b) { return strtoll(s, e, b); }
__asm__(".symver _isoc23_strtoll,__isoc23_strtoll@GLIBC_2.38");

static unsigned long _isoc23_strtoul(const char *s, char **e, int b) { return strtoul(s, e, b); }
__asm__(".symver _isoc23_strtoul,__isoc23_strtoul@GLIBC_2.38");

static int _isoc23_sscanf(const char *str, const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    int r = vsscanf(str, fmt, ap);
    va_end(ap); return r;
}
__asm__(".symver _isoc23_sscanf,__isoc23_sscanf@GLIBC_2.38");

/* fmod / fmodf — re-versioned in glibc 2.38; delegate to next library */
typedef double (*fmod_fn)(double, double);
typedef float  (*fmodf_fn)(float, float);

static double _fmod238(double x, double y) {
    static fmod_fn fn;
    if (!fn) fn = (fmod_fn)dlsym(RTLD_NEXT, "fmod");
    return fn(x, y);
}
__asm__(".symver _fmod238,fmod@GLIBC_2.38");

static float _fmodf238(float x, float y) {
    static fmodf_fn fn;
    if (!fn) fn = (fmodf_fn)dlsym(RTLD_NEXT, "fmodf");
    return fn(x, y);
}
__asm__(".symver _fmodf238,fmodf@GLIBC_2.38");
"""


def _glibc_version() -> tuple[int, int]:
    """Return the running GLIBC version as (major, minor)."""
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.gnu_get_libc_version.restype = ctypes.c_char_p
        ver = libc.gnu_get_libc_version().decode()
        major, minor = int(ver.split(".")[0]), int(ver.split(".")[1])
        return (major, minor)
    except Exception:
        return (2, 99)  # assume new enough if undetectable


def _ensure_glibc_shim(binary_dir: Path) -> Optional[Path]:
    """
    Compile a GLIBC 2.38 compat shim into binary_dir if the running system
    has GLIBC < 2.38. Returns the .so path on success, None if not needed
    or compilation fails.
    """
    if _glibc_version() >= (2, 38):
        return None  # running system is new enough — no shim needed

    shim = binary_dir / "glibc_compat.so"
    if shim.exists():
        return shim

    if not shutil.which("gcc"):
        print(
            "WARNING: gcc not found — cannot build GLIBC compat shim. "
            "Install build-essential or upgrade to Ubuntu 24.04.",
            flush=True,
        )
        return None

    src_fd, src_path = tempfile.mkstemp(suffix=".c")
    try:
        os.write(src_fd, _GLIBC_SHIM_SRC.encode())
        os.close(src_fd)
        result = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", src_path, "-o", str(shim), "-ldl"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"WARNING: GLIBC shim compile failed:\n{result.stderr}", flush=True)
            return None
        return shim
    except Exception as exc:
        print(f"WARNING: GLIBC shim compile error: {exc}", flush=True)
        return None
    finally:
        Path(src_path).unlink(missing_ok=True)


# ── Core CLI functions ────────────────────────────────────────────────────────

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

    # Compile GLIBC compat shim alongside the binary (best-effort)
    _ensure_glibc_shim(install_dir)

    return binary


def _parse_rate_window(data: Optional[dict]) -> Optional[RateWindow]:  # type: ignore[type-arg]
    if not data:
        return None
    return RateWindow(
        used_percent=float(data.get("usedPercent", 0.0)),
        remaining_percent=float(data.get("remainingPercent", 100.0)),
        resets_at=data.get("resetsAt"),
        reset_description=data.get("resetDescription"),
    )


def parse_providers(raw: list[dict]) -> list[ProviderData]:  # type: ignore[type-arg]
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
    # Build env with LD_PRELOAD shim for GLIBC < 2.38 systems
    env = os.environ.copy()
    shim = _ensure_glibc_shim(cli_path.parent)
    if shim:
        existing = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = f"{shim}:{existing}".rstrip(":")

    try:
        result = subprocess.run(
            [str(cli_path), "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
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
