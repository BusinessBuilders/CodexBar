# Linux AppImage Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a build path that outputs a launchable Linux `AppImage` for the Python Linux port, bundling the app code and the Linux `codexbar` CLI while keeping user credentials external.

**Architecture:** Generate an `AppDir` from a small tested Python helper plus a packaging shell script. Bundle the app code, bundled CLI, icon, desktop file, and `Pillow`, then produce the final `AppImage` with Linux packaging tooling while still using host `/usr/bin/python3` and host GTK/GI runtime.

**Tech Stack:** Python 3.10+, shell, pytest, linuxdeploy/appimagetool

---

### Task 1: Add failing packaging helper tests

**Files:**
- Create: `linux/tests/test_appimage.py`
- Create: `linux/codexbar_linux/packaging.py`

**Step 1: Write a failing test for AppDir path generation**

Add a test asserting the helper returns stable paths for:
- `AppDir/AppRun`
- `AppDir/usr/bin/codexbar-linux`
- `AppDir/usr/bin/codexbar`
- `AppDir/usr/lib/codexbar-linux`

**Step 2: Write a failing test for launcher metadata**

Add a test asserting:
- launcher content prepends bundled `usr/bin` to `PATH`
- launcher content sets `PYTHONPATH`
- launcher executes `/usr/bin/python3 -m codexbar_linux`

**Step 3: Run the targeted tests to confirm they fail**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_appimage.py -q`

Expected: FAIL because the packaging helper does not exist yet.

### Task 2: Implement packaging metadata helpers

**Files:**
- Create: `linux/codexbar_linux/packaging.py`
- Test: `linux/tests/test_appimage.py`

**Step 1: Add AppDir path helpers**

Implement a small helper that returns canonical paths relative to an AppDir root.

**Step 2: Add launcher and desktop content helpers**

Implement tested string builders for:
- `AppRun`
- `usr/bin/codexbar-linux`
- desktop entry

**Step 3: Run the targeted tests**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_appimage.py -q`

Expected: PASS

### Task 3: Add the AppImage build script

**Files:**
- Create: `linux/package_appimage.sh`
- Modify: `linux/codexbar-linux.desktop`
- Reuse: `codexbar.png`

**Step 1: Build AppDir assembly logic**

Script responsibilities:
- resolve repo root and Linux worktree paths
- fetch or locate the Linux `codexbar` CLI
- create AppDir
- copy app code, desktop file, icon, and bundled CLI
- install `Pillow` into app-local site-packages
- write `AppRun` and bundled launcher

**Step 2: Add a smoke-test mode**

Support a mode such as `--appdir-only` so packaging can be validated without requiring the final AppImage tool.

**Step 3: Add final AppImage output mode**

Use installed tooling when available and download a portable tool as fallback if needed.

### Task 4: Verify packaging end-to-end

**Files:**
- Modify: none

**Step 1: Re-run the Linux Python test suite**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests -q`

Expected: PASS

**Step 2: Build an AppDir smoke artifact**

Run: `bash .worktrees/linux-port/linux/package_appimage.sh --appdir-only`

Expected: AppDir created successfully with bundled launcher and CLI.

**Step 3: Build the final AppImage**

Run: `bash .worktrees/linux-port/linux/package_appimage.sh`

Expected: an `.AppImage` file appears in the Linux worktree or a `dist/` folder.

**Step 4: Smoke-run the packaged app**

Run the produced AppImage and confirm:
- process launches
- bundled CLI is found
- live provider data still appears

### Task 5: Commit the packaging work

**Files:**
- Commit the tested packaging helper, tests, and build script

**Step 1: Stage the packaging files**

Run:

```bash
git -C .worktrees/linux-port add \
  linux/codexbar_linux/packaging.py \
  linux/tests/test_appimage.py \
  linux/package_appimage.sh \
  docs/plans/2026-04-12-appimage-design.md \
  docs/plans/2026-04-12-appimage-implementation.md
```

**Step 2: Commit**

Run:

```bash
git -C .worktrees/linux-port commit -m "Add Linux AppImage packaging"
```
