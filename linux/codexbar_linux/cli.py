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

# The pre-built binary was compiled against GLIBC 2.38. On Ubuntu 22.04 (GLIBC 2.35)
# we need two fixes:
#   1. Binary-patch the binary's VERNEED section: replace "GLIBC_2.38" with "GLIBC_2.35"
#      (also patch the ELF hash from 0x069691b8 → 0x069691b5).
#   2. LD_PRELOAD a shim providing the 8 symbols that don't exist at GLIBC_2.35:
#      strlcpy, strlcat, __isoc23_{strtol,strtoll,strtoul,sscanf}, fmod, fmodf.
#
# After the binary patch the symbols are looked up as @GLIBC_2.35, which our shim
# provides. fmod/fmodf are delegated to libm via RTLD_NEXT.

_GLIBC_SHIM_SRC = r"""
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <dlfcn.h>

size_t _cb_strlcpy(char *d, const char *s, size_t n) {
    size_t l = strlen(s);
    if (n > 0) { size_t c = l < n-1 ? l : n-1; memcpy(d,s,c); d[c]=0; }
    return l;
}
__asm__(".symver _cb_strlcpy,strlcpy@GLIBC_2.35");

size_t _cb_strlcat(char *d, const char *s, size_t n) {
    size_t dl = strnlen(d, n);
    if (dl == n) return n + strlen(s);
    return dl + _cb_strlcpy(d+dl, s, n-dl);
}
__asm__(".symver _cb_strlcat,strlcat@GLIBC_2.35");

long _cb_strtol(const char *s,char **e,int b){return strtol(s,e,b);}
__asm__(".symver _cb_strtol,__isoc23_strtol@GLIBC_2.35");
long long _cb_strtoll(const char *s,char **e,int b){return strtoll(s,e,b);}
__asm__(".symver _cb_strtoll,__isoc23_strtoll@GLIBC_2.35");
unsigned long _cb_strtoul(const char *s,char **e,int b){return strtoul(s,e,b);}
__asm__(".symver _cb_strtoul,__isoc23_strtoul@GLIBC_2.35");
int _cb_sscanf(const char *s, const char *f, ...) {
    va_list a; va_start(a,f); int r=vsscanf(s,f,a); va_end(a); return r;
}
__asm__(".symver _cb_sscanf,__isoc23_sscanf@GLIBC_2.35");

typedef double (*fmod_t)(double,double);
typedef float  (*fmodf_t)(float,float);
double _cb_fmod(double x,double y){static fmod_t f;if(!f)f=(fmod_t)dlsym(RTLD_NEXT,"fmod");return f(x,y);}
__asm__(".symver _cb_fmod,fmod@GLIBC_2.35");
float _cb_fmodf(float x,float y){static fmodf_t f;if(!f)f=(fmodf_t)dlsym(RTLD_NEXT,"fmodf");return f(x,y);}
__asm__(".symver _cb_fmodf,fmodf@GLIBC_2.35");
"""

_GLIBC_SHIM_VER = """\
GLIBC_2.35 {
    strlcpy; strlcat;
    __isoc23_strtol; __isoc23_strtoll; __isoc23_strtoul; __isoc23_sscanf;
    fmod; fmodf;
};
"""

# ELF hash constants for the VERNEED patch
_HASH_238 = b"\xb8\x91\x96\x06"  # elf_hash("GLIBC_2.38") = 0x069691b8
_HASH_235 = b"\xb5\x91\x96\x06"  # elf_hash("GLIBC_2.35") = 0x069691b5


def _patch_binary_for_glibc235(binary: Path) -> None:
    """
    Patch the binary's VERNEED section in-place so GLIBC_2.38 requirements
    become GLIBC_2.35. Modifies both the version string and its ELF hash.
    Safe: both strings are 10 chars + NUL (same length); hash change is 1 byte.
    Idempotent: no-op if already patched.
    """
    data = binary.read_bytes()
    if b"GLIBC_2.38\x00" not in data:
        return  # already patched or different binary
    patched = data.replace(b"GLIBC_2.38\x00", b"GLIBC_2.35\x00")
    patched = patched.replace(_HASH_238, _HASH_235)
    binary.write_bytes(patched)


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
    ver_fd, ver_path = tempfile.mkstemp(suffix=".map")
    try:
        os.write(src_fd, _GLIBC_SHIM_SRC.encode())
        os.close(src_fd)
        os.write(ver_fd, _GLIBC_SHIM_VER.encode())
        os.close(ver_fd)
        result = subprocess.run(
            [
                "gcc", "-shared", "-fPIC", "-O2",
                src_path, "-o", str(shim),
                "-ldl", f"-Wl,--version-script={ver_path}",
            ],
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
        Path(ver_path).unlink(missing_ok=True)


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

    # On GLIBC < 2.38: patch binary's VERNEED section and build LD_PRELOAD shim
    if _glibc_version() < (2, 38):
        _patch_binary_for_glibc235(binary)
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
