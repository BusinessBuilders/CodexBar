# Gemini Fallback And Window Chrome Design

**Goal:** Add a Linux-native Gemini usage fallback and make the Linux popup feel like a normal tray utility by giving it a draggable header and minimize-to-tray behavior.

## Recommended Approach

1. Add a Gemini OAuth fallback in `linux/codexbar_linux/cli.py` that mirrors the existing Swift probe.
Reasoning: this matches the successful Codex and Claude strategy and removes another dependency on the unstable Swift binary path.

2. Add a compact custom header bar in `linux/codexbar_linux/window.py`.
Reasoning: a dedicated drag handle is more predictable than making the entire popup draggable, and a minimize button that hides back to the tray matches common tray-app behavior.

3. Keep the popup borderless and top-right by default, but preserve the dragged position for the current session.
Reasoning: this keeps the app lightweight while making it practical to place anywhere on screen.

## Gemini Data Flow

- Read `~/.gemini/settings.json` and require `security.auth.selectedType == "oauth-personal"` or tolerate missing/unknown settings.
- Read `~/.gemini/oauth_creds.json` for `access_token`, `refresh_token`, `id_token`, and `expiry_date`.
- If the access token is expired, refresh it using the Gemini CLI OAuth client metadata extracted from the installed `gemini` bundle and `https://oauth2.googleapis.com/token`.
- Call `POST https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist` to determine the user tier and preferred project.
- Call `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` with the detected project when available.
- Decode the quota buckets and map the worst remaining quota per family:
  - `pro` -> `primary`
  - `flash` -> `secondary`
  - `flash-lite` -> `tertiary`
- Decode the JWT email claim from `id_token` and infer plan text:
  - `standard-tier` -> `Paid`
  - `free-tier` with hosted domain -> `Workspace`
  - `free-tier` without hosted domain -> `Free`
  - `legacy-tier` -> `Legacy`

## Window Behavior

- Add a header row above the provider tabs.
- The header row contains:
  - a title label
  - a minimize button that hides the popup back to the tray
- Restrict dragging to the header row only.
- Keep explicit toggle behavior:
  - tray click shows/hides the popup
  - minimize hides the popup
  - focus loss does not auto-hide

## UI Labeling

- Keep provider tabs unchanged.
- Update metric section titles so provider-specific lanes render correctly:
  - Claude: `Session`, `Weekly`, `Sonnet`
  - Gemini: `Pro`, `Flash`, `Flash Lite`
  - `z.ai`: keep the existing generic labels for now unless separate UX work is requested

## Error Handling

- Gemini fallback should fail independently without breaking Codex, Claude, or `z.ai`.
- A missing Gemini CLI bundle or missing refresh metadata should only suppress Gemini fallback, not the entire refresh.
- If the stored Gemini access token still works, skip refresh and use it directly.

## Testing

- Add CLI tests for:
  - Gemini OAuth fallback on CLI timeout
  - Gemini token refresh before quota fetch
  - multi-provider fallback including Gemini
- Add window tests for:
  - default focus policy stays visible
  - header chrome state exposes minimize-to-tray intent
  - drag state still preserves manual position
