from __future__ import annotations
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from codexbar_linux.store import ProviderData, RateWindow

GITHUB_RELEASES_API = "https://api.github.com/repos/steipete/CodexBar/releases/latest"
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "share" / "codexbar-linux" / "bin"
CODEXBAR_CONFIG_PATH = Path.home() / ".codexbar" / "config.json"
CLAUDE_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
GEMINI_CREDENTIALS_PATH = Path.home() / ".gemini" / "oauth_creds.json"
GEMINI_SETTINGS_PATH = Path.home() / ".gemini" / "settings.json"

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

/* ── CURL_OPENSSL_4: WebSocket stubs (libcurl < 7.86.0) ── */
/* curl_ws_send/recv/meta added in libcurl 7.86.0; Ubuntu 22.04 has 7.81.0.
   Binary uses lazy binding so load succeeds, but calling them crashes.
   curl_easy_setopt wrapper silences CURLE_UNKNOWN_OPTION (48) returned
   for new options like CURLOPT_WS_OPTIONS (320) on older libcurl. */
typedef struct { size_t age, recvd, bytes_remaining; int flags; } _cb_ws_frame;
int _cb_curl_ws_send(void *c,const void *b,size_t n,size_t *s,long long f,unsigned fl){
    (void)c;(void)b;(void)n;(void)f;(void)fl; if(s)*s=0; return 4;}
__asm__(".symver _cb_curl_ws_send,curl_ws_send@CURL_OPENSSL_4");
int _cb_curl_ws_recv(void *c,void *b,size_t n,size_t *r,const _cb_ws_frame **fr){
    (void)c;(void)b;(void)n;(void)r;(void)fr; return 4;}
__asm__(".symver _cb_curl_ws_recv,curl_ws_recv@CURL_OPENSSL_4");
const _cb_ws_frame *_cb_curl_ws_meta(void *c){(void)c;return NULL;}
__asm__(".symver _cb_curl_ws_meta,curl_ws_meta@CURL_OPENSSL_4");
/* Intercept curl_easy_setopt: on x86-64 SysV ABI, declaring (void*,int,long)
   captures the third arg correctly whether caller treats it as variadic or not. */
typedef int (*_setopt_fn)(void*,int,long);
int _cb_curl_easy_setopt(void *h,int opt,long val){
    static _setopt_fn r; if(!r)r=(_setopt_fn)dlsym(RTLD_NEXT,"curl_easy_setopt");
    int rc=r(h,opt,val); return (rc==48)?0:rc;}  /* CURLE_UNKNOWN_OPTION→OK */
__asm__(".symver _cb_curl_easy_setopt,curl_easy_setopt@CURL_OPENSSL_4");
"""

_GLIBC_SHIM_VER = """\
GLIBC_2.35 {
    strlcpy; strlcat;
    __isoc23_strtol; __isoc23_strtoll; __isoc23_strtoul; __isoc23_sscanf;
    fmod; fmodf;
};
CURL_OPENSSL_4 {
    curl_ws_send; curl_ws_recv; curl_ws_meta;
    curl_easy_setopt;
};
"""

# Bump when _GLIBC_SHIM_SRC changes to force a shim rebuild on next run
_SHIM_VERSION = "2"

# ELF hash constants for the VERNEED patch
_HASH_238 = b"\xb8\x91\x96\x06"  # elf_hash("GLIBC_2.38") = 0x069691b8
_HASH_235 = b"\xb5\x91\x96\x06"  # elf_hash("GLIBC_2.35") = 0x069691b5


def _runtime_cache_root() -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache) / "codexbar-linux" / "runtime"
    return Path.home() / ".cache" / "codexbar-linux" / "runtime"


def _prepare_runtime_cli(cli_path: Path, glibc_version: Optional[tuple[int, int]] = None) -> Path:
    if not cli_path.exists():
        return cli_path

    glibc_version = glibc_version or _glibc_version()
    if glibc_version >= (2, 38):
        return cli_path

    try:
        source_bytes = cli_path.read_bytes()
    except FileNotFoundError:
        return cli_path

    digest = hashlib.sha256(source_bytes).hexdigest()[:16]
    runtime_dir = _runtime_cache_root() / digest
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_cli = runtime_dir / cli_path.name

    if not runtime_cli.exists() or runtime_cli.read_bytes() != source_bytes:
        shutil.copy2(cli_path, runtime_cli)
        runtime_cli.chmod(runtime_cli.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return runtime_cli


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
    ver_file = binary_dir / "glibc_compat.ver"
    if shim.exists():
        if ver_file.exists() and ver_file.read_text().strip() == _SHIM_VERSION:
            return shim
        # Stale shim (source changed) — delete and rebuild
        shim.unlink(missing_ok=True)
        ver_file.unlink(missing_ok=True)

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
        ver_file.write_text(_SHIM_VERSION + "\n")
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


def _codex_auth_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home) / "auth.json"
    return Path.home() / ".codex" / "auth.json"


def _format_plan_name(plan_type: Optional[str]) -> Optional[str]:
    if not plan_type:
        return None
    return plan_type.replace("_", " ").title()


def _normalize_timestamp(raw: Optional[object]) -> Optional[datetime]:
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    if isinstance(raw, (int, float)):
        timestamp = float(raw)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return None


def _format_reset_description(timestamp: Optional[object]) -> Optional[str]:
    reset_at = _normalize_timestamp(timestamp)
    if reset_at is None:
        return None
    reset_at = reset_at.astimezone()
    return f"Resets {reset_at.strftime('%b %-d, %-I:%M%p').lower()}"


def _iso_reset_at(timestamp: Optional[object]) -> Optional[str]:
    reset_at = _normalize_timestamp(timestamp)
    if reset_at is None:
        return None
    return reset_at.isoformat().replace("+00:00", "Z")


def _window_from_wham(data: Optional[dict]) -> Optional[RateWindow]:  # type: ignore[type-arg]
    if not data:
        return None
    used_percent = float(data.get("used_percent", 0.0))
    reset_at = data.get("reset_at")
    return RateWindow(
        used_percent=used_percent,
        remaining_percent=max(0.0, 100.0 - used_percent),
        resets_at=_iso_reset_at(reset_at),
        reset_description=_format_reset_description(reset_at),
    )


def _load_codex_auth_payload() -> Optional[dict]:  # type: ignore[type-arg]
    auth_path = _codex_auth_path()
    if not auth_path.exists():
        return None
    try:
        return json.loads(auth_path.read_text())
    except Exception:
        return None


def _load_claude_credentials_payload() -> Optional[dict]:  # type: ignore[type-arg]
    if not CLAUDE_CREDENTIALS_PATH.exists():
        return None
    try:
        return json.loads(CLAUDE_CREDENTIALS_PATH.read_text())
    except Exception:
        return None


def _load_codexbar_config_payload() -> Optional[dict]:  # type: ignore[type-arg]
    if not CODEXBAR_CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CODEXBAR_CONFIG_PATH.read_text())
    except Exception:
        return None


def _provider_config(provider_id: str) -> Optional[dict]:  # type: ignore[type-arg]
    config = _load_codexbar_config_payload()
    if not config:
        return None
    for provider in config.get("providers") or []:
        if provider.get("id") == provider_id:
            return provider
    return None


def _fetch_json(request: urllib.request.Request, timeout: int = 20) -> Optional[dict]:  # type: ignore[type-arg]
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None


def _fetch_codex_oauth_provider() -> Optional[ProviderData]:
    auth_payload = _load_codex_auth_payload()
    if not auth_payload:
        return None

    access_token = auth_payload.get("OPENAI_API_KEY")
    account_id = None
    if not access_token:
        tokens = auth_payload.get("tokens") or {}
        access_token = tokens.get("access_token") or tokens.get("accessToken")
        account_id = tokens.get("account_id") or tokens.get("accountId")
    if not access_token:
        return None

    request = urllib.request.Request(
        "https://chatgpt.com/backend-api/wham/usage",
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "CodexBarLinux",
            "Accept": "application/json",
            **({"ChatGPT-Account-Id": account_id} if account_id else {}),
        },
    )

    payload = _fetch_json(request)
    if not payload:
        return None

    rate_limit = payload.get("rate_limit") or {}
    credits = payload.get("credits") or {}
    credits_balance = credits.get("balance")
    credits_remaining: Optional[float] = None
    credits_text: Optional[str] = None

    if credits_balance not in (None, ""):
        try:
            credits_remaining = float(credits_balance)
        except (TypeError, ValueError):
            credits_remaining = None
        if credits_remaining is not None and not credits.get("unlimited"):
            credits_text = f"${credits_remaining:.2f} remaining"

    return ProviderData(
        provider="codex",
        account=payload.get("email"),
        source="oauth",
        status_indicator="none",
        primary=_window_from_wham(rate_limit.get("primary_window")),
        secondary=_window_from_wham(rate_limit.get("secondary_window")),
        tertiary=None,
        credits_text=credits_text,
        credits_remaining=credits_remaining,
        plan_text=_format_plan_name(payload.get("plan_type")),
        error=None,
    )


def _infer_claude_plan_text(oauth: dict) -> Optional[str]:  # type: ignore[type-arg]
    subscription_type = oauth.get("subscriptionType")
    if isinstance(subscription_type, str) and subscription_type.strip():
        return _format_plan_name(subscription_type)

    tier = str(oauth.get("rateLimitTier") or "").lower()
    if "max" in tier:
        return "Max"
    if "team" in tier:
        return "Team"
    if "enterprise" in tier:
        return "Enterprise"
    if "pro" in tier:
        return "Pro"
    return None


def _window_from_utilization(data: Optional[dict]) -> Optional[RateWindow]:  # type: ignore[type-arg]
    if not data:
        return None
    used_percent = float(data.get("utilization", 0.0))
    resets_at = data.get("resets_at")
    return RateWindow(
        used_percent=used_percent,
        remaining_percent=max(0.0, 100.0 - used_percent),
        resets_at=_iso_reset_at(resets_at),
        reset_description=_format_reset_description(resets_at),
    )


def _fetch_claude_oauth_provider() -> Optional[ProviderData]:
    credentials = _load_claude_credentials_payload()
    if not credentials:
        return None

    oauth = credentials.get("claudeAiOauth") or {}
    access_token = oauth.get("accessToken")
    if not access_token:
        return None

    request = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/2.1.0",
        },
    )

    payload = _fetch_json(request)
    if not payload:
        return None

    return ProviderData(
        provider="claude",
        account=None,
        source="oauth",
        status_indicator="none",
        primary=_window_from_utilization(payload.get("five_hour")),
        secondary=_window_from_utilization(payload.get("seven_day")),
        tertiary=_window_from_utilization(payload.get("seven_day_sonnet")),
        credits_text=None,
        credits_remaining=None,
        plan_text=_infer_claude_plan_text(oauth),
        error=None,
    )


def _load_gemini_credentials_payload() -> Optional[dict]:  # type: ignore[type-arg]
    if not GEMINI_CREDENTIALS_PATH.exists():
        return None
    try:
        return json.loads(GEMINI_CREDENTIALS_PATH.read_text())
    except Exception:
        return None


def _load_gemini_settings_payload() -> Optional[dict]:  # type: ignore[type-arg]
    if not GEMINI_SETTINGS_PATH.exists():
        return None
    try:
        return json.loads(GEMINI_SETTINGS_PATH.read_text())
    except Exception:
        return None


def _gemini_auth_type() -> str:
    settings = _load_gemini_settings_payload() or {}
    security = settings.get("security") or {}
    auth = security.get("auth") or {}
    return str(auth.get("selectedType") or "unknown")


def _gemini_binary_path() -> Optional[Path]:
    superset_bin = str(Path.home() / ".superset" / "bin")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        expanded = str(Path(entry).expanduser())
        if expanded == superset_bin or expanded.startswith(str(Path.home() / ".superset-")):
            continue
        candidate = Path(entry).expanduser() / "gemini"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    found = shutil.which("gemini")
    return Path(found).resolve() if found else None


def _gemini_bundle_candidates() -> list[Path]:
    gemini_binary = _gemini_binary_path()
    if gemini_binary is None:
        return []

    if gemini_binary.name == "gemini.js" and gemini_binary.parent.name == "bundle":
        bundle_dir = gemini_binary.parent
    else:
        bundle_dir = gemini_binary.parent.parent / "lib" / "node_modules" / "@google" / "gemini-cli" / "bundle"
    if not bundle_dir.exists():
        return []

    candidates = list(sorted(bundle_dir.glob("chunk-*.js")))
    candidates.extend(sorted(bundle_dir.glob("oauth2-provider-*.js")))
    candidates.extend(sorted(bundle_dir.glob("*.js")))
    return candidates


def _gemini_oauth_client() -> Optional[tuple[str, str]]:
    client_id_pattern = re.compile(r'var OAUTH_CLIENT_ID = "([^"]+)";')
    client_secret_pattern = re.compile(r'var OAUTH_CLIENT_SECRET = "([^"]+)";')

    for candidate in _gemini_bundle_candidates():
        try:
            content = candidate.read_text()
        except Exception:
            continue
        client_id_match = client_id_pattern.search(content)
        client_secret_match = client_secret_pattern.search(content)
        if client_id_match and client_secret_match:
            return client_id_match.group(1), client_secret_match.group(1)
    return None


def _update_gemini_credentials(refresh_payload: dict) -> None:  # type: ignore[type-arg]
    credentials = _load_gemini_credentials_payload()
    if not credentials:
        return
    if "access_token" in refresh_payload:
        credentials["access_token"] = refresh_payload["access_token"]
    if "id_token" in refresh_payload:
        credentials["id_token"] = refresh_payload["id_token"]
    expires_in = refresh_payload.get("expires_in")
    if isinstance(expires_in, (int, float)):
        credentials["expiry_date"] = int((datetime.now(tz=timezone.utc).timestamp() + float(expires_in)) * 1000)
    GEMINI_CREDENTIALS_PATH.write_text(json.dumps(credentials, indent=2))


def _refresh_gemini_access_token(refresh_token: str) -> Optional[str]:
    oauth_client = _gemini_oauth_client()
    if oauth_client is None:
        return None

    client_id, client_secret = oauth_client
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    payload = _fetch_json(request)
    if not payload:
        return None
    _update_gemini_credentials(payload)
    return payload.get("access_token")


def _extract_jwt_claims(id_token: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not id_token:
        return None, None

    parts = id_token.split(".")
    if len(parts) < 2:
        return None, None

    payload = parts[1].replace("-", "+").replace("_", "/")
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        decoded = json.loads(base64.b64decode(payload))
    except Exception:
        return None, None
    return decoded.get("email"), decoded.get("hd")


def _gemini_access_token(credentials: dict) -> Optional[str]:  # type: ignore[type-arg]
    access_token = credentials.get("access_token")
    if not access_token:
        return None

    expiry_date = _normalize_timestamp(credentials.get("expiry_date"))
    if expiry_date is None or expiry_date > datetime.now(tz=timezone.utc):
        return access_token

    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        return None
    return _refresh_gemini_access_token(refresh_token)


def _gemini_code_assist_status(access_token: str) -> tuple[Optional[str], Optional[str]]:
    request = urllib.request.Request(
        "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
        data=b'{"metadata":{"ideType":"GEMINI_CLI","pluginType":"GEMINI"}}',
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    payload = _fetch_json(request)
    if not payload:
        return None, None

    project = payload.get("cloudaicompanionProject")
    if isinstance(project, dict):
        project = project.get("id") or project.get("projectId")

    tier = ((payload.get("currentTier") or {}).get("id"))
    normalized_project = project.strip() if isinstance(project, str) and project.strip() else None
    return (str(tier) if isinstance(tier, str) else None), normalized_project


def _gemini_quota_payload(access_token: str, project_id: Optional[str]) -> Optional[dict]:  # type: ignore[type-arg]
    request = urllib.request.Request(
        "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
        data=json.dumps({"project": project_id}).encode() if project_id else b"{}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return _fetch_json(request)


def _gemini_plan_text(tier: Optional[str], hosted_domain: Optional[str]) -> Optional[str]:
    if tier == "standard-tier":
        return "Paid"
    if tier == "free-tier" and hosted_domain:
        return "Workspace"
    if tier == "free-tier":
        return "Free"
    if tier == "legacy-tier":
        return "Legacy"
    return None


def _gemini_model_family(model_id: str) -> Optional[str]:
    lowered = model_id.lower()
    if "flash-lite" in lowered:
        return "flash-lite"
    if "flash" in lowered:
        return "flash"
    if "pro" in lowered:
        return "pro"
    return None


def _window_from_remaining_fraction(bucket: Optional[dict]) -> Optional[RateWindow]:  # type: ignore[type-arg]
    if not bucket:
        return None

    remaining_percent = float(bucket.get("remainingFraction", 0.0)) * 100.0
    reset_at = bucket.get("resetTime")
    return RateWindow(
        used_percent=max(0.0, 100.0 - remaining_percent),
        remaining_percent=max(0.0, remaining_percent),
        resets_at=_iso_reset_at(reset_at),
        reset_description=_format_reset_description(reset_at),
    )


def _fetch_gemini_provider() -> Optional[ProviderData]:
    if _gemini_auth_type() not in {"oauth-personal", "unknown"}:
        return None

    credentials = _load_gemini_credentials_payload()
    if not credentials:
        return None

    access_token = _gemini_access_token(credentials)
    if not access_token:
        return None

    tier, project_id = _gemini_code_assist_status(access_token)
    payload = _gemini_quota_payload(access_token, project_id)
    if not payload:
        return None

    worst_by_family: dict[str, dict] = {}
    for bucket in payload.get("buckets") or []:
        model_id = bucket.get("modelId")
        remaining_fraction = bucket.get("remainingFraction")
        if not isinstance(model_id, str) or not isinstance(remaining_fraction, (int, float)):
            continue
        family = _gemini_model_family(model_id)
        if family is None:
            continue
        existing = worst_by_family.get(family)
        if existing is None or float(remaining_fraction) < float(existing.get("remainingFraction", 1.0)):
            worst_by_family[family] = bucket

    if not worst_by_family:
        return None

    email, hosted_domain = _extract_jwt_claims(credentials.get("id_token"))
    return ProviderData(
        provider="gemini",
        account=email,
        source="oauth",
        status_indicator="none",
        primary=_window_from_remaining_fraction(worst_by_family.get("pro")),
        secondary=_window_from_remaining_fraction(worst_by_family.get("flash")),
        tertiary=_window_from_remaining_fraction(worst_by_family.get("flash-lite")),
        credits_text=None,
        credits_remaining=None,
        plan_text=_gemini_plan_text(tier, hosted_domain),
        error=None,
    )


def _zai_window_minutes(raw: dict) -> Optional[int]:  # type: ignore[type-arg]
    unit = raw.get("unit")
    number = raw.get("number")
    if not isinstance(number, int) or number <= 0:
        return None
    if unit == 5:
        return number
    if unit == 3:
        return number * 60
    if unit == 1:
        return number * 24 * 60
    if unit == 6:
        return number * 7 * 24 * 60
    return None


def _window_from_zai_limit(raw: Optional[dict]) -> Optional[RateWindow]:  # type: ignore[type-arg]
    if not raw:
        return None
    used_percent = float(raw.get("percentage", 0.0))
    reset_at = raw.get("nextResetTime")
    return RateWindow(
        used_percent=used_percent,
        remaining_percent=max(0.0, 100.0 - used_percent),
        resets_at=_iso_reset_at(reset_at),
        reset_description=_format_reset_description(reset_at),
    )


def _fetch_zai_provider() -> Optional[ProviderData]:
    provider_config = _provider_config("zai") or {}
    api_key = provider_config.get("apiKey") or os.environ.get("Z_AI_API_KEY")
    if not api_key:
        return None

    request = urllib.request.Request(
        "https://api.z.ai/api/monitor/usage/quota/limit",
        headers={
            "authorization": f"Bearer {api_key}",
            "accept": "application/json",
        },
    )

    payload = _fetch_json(request)
    if not payload or not payload.get("success") or payload.get("code") != 200:
        return None

    limits = (payload.get("data") or {}).get("limits") or []
    token_limits = [limit for limit in limits if limit.get("type") == "TOKENS_LIMIT"]
    token_limits.sort(key=lambda limit: _zai_window_minutes(limit) or 10**9)
    time_limit = next((limit for limit in limits if limit.get("type") == "TIME_LIMIT"), None)

    primary_limit = token_limits[0] if token_limits else time_limit
    secondary_limit = token_limits[1] if len(token_limits) > 1 else None
    if primary_limit is time_limit:
        secondary_limit = None

    return ProviderData(
        provider="zai",
        account=None,
        source="api",
        status_indicator="none",
        primary=_window_from_zai_limit(primary_limit),
        secondary=_window_from_zai_limit(secondary_limit),
        tertiary=None,
        credits_text=None,
        credits_remaining=None,
        plan_text=None,
        error=None,
    )


def _fallback_usage_providers() -> tuple[list[ProviderData], Optional[str]]:
    providers = []
    for fetcher in (
        _fetch_codex_oauth_provider,
        _fetch_claude_oauth_provider,
        _fetch_gemini_provider,
        _fetch_zai_provider,
    ):
        provider = fetcher()
        if provider is not None:
            providers.append(provider)
    return providers, None


def run_usage_json(
    cli_path: Path,
    timeout: int = 30,
) -> tuple[list[ProviderData], Optional[str]]:
    """Run `codexbar usage --json`, return (providers, error_string)."""
    # On GLIBC < 2.38: ensure binary is patched and shim is built
    env = os.environ.copy()
    glibc_version = _glibc_version()
    runtime_cli_path = _prepare_runtime_cli(cli_path, glibc_version=glibc_version)
    if glibc_version < (2, 38) and runtime_cli_path.exists():
        _patch_binary_for_glibc235(runtime_cli_path.resolve())
    shim = _ensure_glibc_shim(runtime_cli_path.parent)
    if shim:
        existing = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = f"{shim}:{existing}".rstrip(":")

    try:
        result = subprocess.run(
            [str(runtime_cli_path), "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            fallback_providers, fallback_error = _fallback_usage_providers()
            if fallback_providers:
                return fallback_providers, fallback_error
            return [], result.stderr.strip() or f"CLI exit code {result.returncode}"
        raw = json.loads(result.stdout)
        return parse_providers(raw), None
    except subprocess.TimeoutExpired:
        fallback_providers, fallback_error = _fallback_usage_providers()
        if fallback_providers:
            return fallback_providers, fallback_error
        return [], f"CLI timed out after {timeout}s"
    except json.JSONDecodeError as exc:
        fallback_providers, fallback_error = _fallback_usage_providers()
        if fallback_providers:
            return fallback_providers, fallback_error
        return [], f"Invalid JSON from CLI: {exc}"
    except Exception as exc:  # noqa: BLE001
        fallback_providers, fallback_error = _fallback_usage_providers()
        if fallback_providers:
            return fallback_providers, fallback_error
        return [], str(exc)
