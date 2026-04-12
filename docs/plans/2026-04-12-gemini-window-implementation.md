# Gemini Fallback And Window Chrome Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Linux-native Gemini fallback and a draggable/minimizable popup header so the Linux app works without the Swift CLI and behaves like a normal tray utility.

**Architecture:** Extend `run_usage_json()` with a Gemini fallback alongside the existing Codex, Claude, and `z.ai` fallbacks. Add a small custom chrome layer to the GTK popup and keep drag state pure enough to test without a live display.

**Tech Stack:** Python 3.10+, urllib, GTK4/PyGObject, pytest

---

### Task 1: Add failing Gemini fallback tests

**Files:**
- Modify: `linux/tests/test_cli.py`

**Step 1: Write the failing Gemini timeout fallback test**

Add a test that:
- forces `subprocess.run` to time out
- mocks Gemini settings and OAuth credential loading
- mocks token refresh, `loadCodeAssist`, and quota responses
- asserts a `ProviderData(provider="gemini")` result with `Paid` plan and three model windows

**Step 2: Run the targeted test to confirm it fails**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_cli.py -k gemini -q`

Expected: FAIL because no Gemini fallback exists yet.

### Task 2: Implement Gemini OAuth helpers

**Files:**
- Modify: `linux/codexbar_linux/cli.py`
- Test: `linux/tests/test_cli.py`

**Step 1: Add Gemini credential and settings helpers**

Add helpers for:
- `~/.gemini/oauth_creds.json`
- `~/.gemini/settings.json`
- auth-type validation
- JWT email/domain extraction

**Step 2: Add refresh-token support**

Implement:
- Gemini CLI bundle discovery from the installed `gemini` binary
- OAuth client ID/secret extraction from the bundle
- token refresh against `https://oauth2.googleapis.com/token`
- stored credential update after refresh

**Step 3: Add quota fetch and mapping**

Implement:
- `loadCodeAssist`
- quota request
- bucket grouping into `Pro`, `Flash`, and `Flash Lite`
- `ProviderData` mapping

**Step 4: Run targeted tests**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_cli.py -k gemini -q`

Expected: PASS

### Task 3: Compose Gemini with the existing fallback set

**Files:**
- Modify: `linux/codexbar_linux/cli.py`
- Modify: `linux/tests/test_cli.py`

**Step 1: Add Gemini to the fallback aggregator**

Include Gemini in `_fallback_usage_providers()` without changing the independence of the other providers.

**Step 2: Extend mixed-success coverage**

Add or update a mixed-provider test so a successful Gemini fallback can coexist with other successful providers.

**Step 3: Run targeted fallback tests**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_cli.py -k 'gemini or multiple_fallback' -q`

Expected: PASS

### Task 4: Add window chrome tests first

**Files:**
- Modify: `linux/tests/test_window.py`

**Step 1: Write a failing header chrome test**

Add a simple state-oriented test asserting:
- the chrome exposes minimize-to-tray behavior
- drag should be enabled from the header

**Step 2: Run the targeted test to confirm it fails**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_window.py -q`

Expected: FAIL because the header chrome state does not exist yet.

### Task 5: Implement header dragging and minimize-to-tray

**Files:**
- Modify: `linux/codexbar_linux/window.py`
- Modify: `linux/codexbar_linux/style.css`
- Modify: `linux/codexbar_linux/provider_view.py`
- Test: `linux/tests/test_window.py`

**Step 1: Add header chrome state and UI**

Implement:
- header title
- minimize button
- a dedicated drag handle area

**Step 2: Restrict drag gestures to the header**

Move gesture handling from the whole popup to the header row while preserving session-local manual position.

**Step 3: Fix provider-specific metric titles**

Update `ProviderView` so Gemini shows `Pro`, `Flash`, and `Flash Lite` instead of the Claude-oriented defaults.

**Step 4: Run targeted window tests**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests/test_window.py -q`

Expected: PASS

### Task 6: Verify end-to-end Linux behavior

**Files:**
- Modify: none

**Step 1: Run the full Linux suite**

Run: `/usr/bin/python3 -m pytest .worktrees/linux-port/linux/tests -q`

Expected: PASS

**Step 2: Run a live Gemini fallback smoke test**

Run:

```bash
/usr/bin/python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, '/home/magiccat/CodexBar/.worktrees/linux-port/linux')
from codexbar_linux.cli import run_usage_json
providers, error = run_usage_json(Path.home()/'.local/share/codexbar-linux/bin/codexbar', timeout=5)
print(error)
for provider in providers:
    print(provider.provider, provider.source, provider.plan_text)
PY
```

Expected: Gemini appears when local OAuth state is available.

**Step 3: Run the app launch smoke test**

Run:

```bash
timeout 8s bash -lc 'DISPLAY=:1 PYTHONPATH=/home/magiccat/CodexBar/.worktrees/linux-port/linux /usr/bin/python3 -m codexbar_linux'
```

Expected: process remains alive for the full timeout.
