from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackagingPaths:
    root: Path
    apprun: Path
    launcher: Path
    cli: Path
    lib_dir: Path
    site_packages: Path
    desktop: Path
    icon: Path

    @classmethod
    def from_root(cls, root: Path) -> "PackagingPaths":
        lib_dir = root / "usr" / "lib" / "codexbar-linux"
        return cls(
            root=root,
            apprun=root / "AppRun",
            launcher=root / "usr" / "bin" / "codexbar-linux",
            cli=root / "usr" / "bin" / "codexbar",
            lib_dir=lib_dir,
            site_packages=lib_dir / "site-packages",
            desktop=root / "codexbar-linux.desktop",
            icon=root / "codexbar-linux.png",
        )


def render_launcher(paths: PackagingPaths) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPDIR="$(cd "$HERE/../.." && pwd)"
export PATH="$APPDIR/usr/bin:${PATH:-}"
export PYTHONPATH="$APPDIR/usr/lib/codexbar-linux:$APPDIR/usr/lib/codexbar-linux/site-packages${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m codexbar_linux "$@"
"""


def render_apprun(paths: PackagingPaths) -> str:
    return """#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/codexbar-linux" "$@"
"""


def render_desktop_entry(exec_name: str, icon_name: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=CodexBar
GenericName=AI Usage Monitor
Comment=AI usage stats in your system tray
Exec={exec_name}
Icon={icon_name}
Terminal=false
Categories=Utility;Monitor;
Keywords=claude;codex;gemini;z.ai;ai;usage;
StartupNotify=false
X-GNOME-Autostart-enabled=false
"""
