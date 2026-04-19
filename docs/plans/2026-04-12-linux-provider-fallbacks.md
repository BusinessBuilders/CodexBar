# Linux Provider Fallbacks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Linux-native Claude OAuth and z.ai API fallbacks, plus a draggable popup window, so the Linux Python app remains usable when the Swift CLI path fails.

**Architecture:** Keep `codexbar_linux.cli.run_usage_json()` as the main entry point. On CLI failure, compose provider-native fallback payloads for Codex, Claude, and z.ai into the existing `ProviderData` model. Add drag state to the GTK popup without changing the poller/store contract.

**Tech Stack:** Python 3.10+, urllib, GTK4/PyGObject, pytest

---

### Task 1: Document Claude and z.ai fallback behavior with failing tests

**Files:**
- Modify: `linux/tests/test_cli.py`

**Step 1: Write failing Claude OAuth fallback test**

Add a test that:
- Mocks `subprocess.run` to timeout
- Mocks `~/.claude/.credentials.json`
- Mocks the Claude OAuth usage HTTP response
- Asserts a `claude` `ProviderData` payload with primary/secondary/tertiary windows and plan text

**Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest linux/tests/test_cli.py -k claude_oauth -q`

Expected: FAIL because no Claude fallback exists yet.

**Step 3: Write failing z.ai fallback test**

Add a test that:
- Mocks CLI failure
- Mocks `~/.codexbar/config.json` with a `zai` provider `apiKey`
- Mocks the z.ai quota response
- Asserts `ProviderData(provider="zai")` with mapped windows

**Step 4: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest linux/tests/test_cli.py -k zai -q`

Expected: FAIL because no z.ai fallback exists yet.

### Task 2: Implement Claude OAuth fallback

**Files:**
- Modify: `linux/codexbar_linux/cli.py`
- Test: `linux/tests/test_cli.py`

**Step 1: Add Claude credential loading helpers**

Read `~/.claude/.credentials.json` and extract:
- `claudeAiOauth.accessToken`
- `claudeAiOauth.rateLimitTier`

**Step 2: Add Claude OAuth usage fetch helper**

Call:
- `GET https://api.anthropic.com/api/oauth/usage`

Headers:
- `Authorization: Bearer <token>`
- `Accept: application/json`
- `Content-Type: application/json`
- `anthropic-beta: oauth-2025-04-20`
- `User-Agent: claude-code/<version>`

**Step 3: Map OAuth usage response into `ProviderData`**

Map:
- `five_hour` → `primary`
- `seven_day` → `secondary`
- `seven_day_sonnet` → `tertiary`

Convert utilization to `used_percent`, `remaining_percent`, and preserve `resets_at`.

**Step 4: Run focused tests**

Run: `/usr/bin/python3 -m pytest linux/tests/test_cli.py -k claude_oauth -q`

Expected: PASS

### Task 3: Implement z.ai fallback

**Files:**
- Modify: `linux/codexbar_linux/cli.py`
- Test: `linux/tests/test_cli.py`

**Step 1: Add config reader for `~/.codexbar/config.json`**

Read provider entries and resolve:
- `providers[].id == "zai"`
- `apiKey`
- optional `region`

**Step 2: Add z.ai quota fetch helper**

Call:
- `GET https://api.z.ai/api/monitor/usage/quota/limit`

Headers:
- `authorization: Bearer <token>`
- `accept: application/json`

Fallback to `Z_AI_API_KEY` when config token is missing.

**Step 3: Map quota response into `ProviderData`**

Map:
- main token limit → `primary`
- time limit → `secondary`
- shorter token window when present → `tertiary`

**Step 4: Run focused tests**

Run: `/usr/bin/python3 -m pytest linux/tests/test_cli.py -k zai -q`

Expected: PASS

### Task 4: Compose fallback providers safely

**Files:**
- Modify: `linux/codexbar_linux/cli.py`
- Test: `linux/tests/test_cli.py`

**Step 1: Update fallback aggregator**

Compose available providers in this order:
- Codex
- Claude
- z.ai

Each provider should fail independently without aborting the others.

**Step 2: Add mixed-success test**

Add a test asserting that if one provider fallback fails and another succeeds, `run_usage_json()` still returns the successful provider list.

**Step 3: Run focused tests**

Run: `/usr/bin/python3 -m pytest linux/tests/test_cli.py -k fallback -q`

Expected: PASS

### Task 5: Add draggable popup behavior

**Files:**
- Modify: `linux/codexbar_linux/window.py`
- Create or modify: `linux/tests/test_window.py`

**Step 1: Write failing drag-state test**

Test pure position helpers for:
- default tray placement when no manual origin exists
- manual origin retained after a drag

**Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest linux/tests/test_window.py -q`

Expected: FAIL because no drag-state helper exists yet.

**Step 3: Implement minimal drag behavior**

Add:
- session-local manual window origin storage
- `Gtk.GestureDrag` handlers
- update origin on drag end
- reuse manual origin on subsequent `toggle()` calls

**Step 4: Run focused tests**

Run: `/usr/bin/python3 -m pytest linux/tests/test_window.py -q`

Expected: PASS

### Task 6: Verify end-to-end Linux behavior

**Files:**
- Modify: none

**Step 1: Run Linux Python test suite**

Run: `/usr/bin/python3 -m pytest linux/tests -q`

Expected: PASS

**Step 2: Run live fallback smoke check**

Run:

```bash
/usr/bin/python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'linux')
from codexbar_linux.cli import run_usage_json
providers, error = run_usage_json(Path.home()/'.local/share/codexbar-linux/bin/codexbar', timeout=5)
print(error)
for p in providers:
    print(p.provider, p.source, p.plan_text)
PY
```

Expected: live providers printed for the configured Linux account state.

