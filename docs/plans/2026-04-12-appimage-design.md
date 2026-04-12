# Linux AppImage Packaging Design

**Goal:** Produce a single-file Linux `AppImage` for the Python Linux port so users can launch CodexBar without running the install script first.

## Recommended Approach

1. Build a practical AppImage around the current Linux port.
Reasoning: fastest path and the least churn. The provider logic already works; packaging should not force a frontend rewrite.

2. Bundle the Python app code, bundled `codexbar` CLI binary, launcher scripts, desktop file, icon, and `Pillow`.
Reasoning: these are app-owned assets and should travel with the package.

3. Keep auth and config external in the user’s home directory.
Reasoning: credentials must never be embedded into the package, and runtime behavior should match the current Linux app.

4. Continue using host `/usr/bin/python3` and host GI/GTK/AppIndicator runtime.
Reasoning: the current app depends on PyGObject and Linux tray libraries that are already installed from distro packages. Trying to fully vendor them now would add a lot of packaging risk.

## Scope

Bundle:
- `linux/codexbar_linux/*`
- the Linux `codexbar` CLI binary
- `Pillow` into an app-local site-packages directory
- desktop metadata
- icon assets
- `AppRun`
- a user-facing launcher script inside the AppDir

Do not bundle:
- `~/.codex/auth.json`
- `~/.claude/.credentials.json`
- `~/.gemini/oauth_creds.json`
- `~/.codexbar/config.json`
- distro GTK/GI/AppIndicator libraries

## AppDir Layout

- `AppDir/AppRun`
- `AppDir/codexbar-linux.desktop`
- `AppDir/codexbar-linux.png`
- `AppDir/usr/bin/codexbar-linux`
- `AppDir/usr/bin/codexbar`
- `AppDir/usr/lib/codexbar-linux/codexbar_linux/...`
- `AppDir/usr/lib/codexbar-linux/site-packages/...`

## Runtime Behavior

- `AppRun` prepends bundled `usr/bin` to `PATH`.
- `AppRun` sets `PYTHONPATH` to the bundled app code and bundled site-packages.
- `AppRun` executes `/usr/bin/python3 -m codexbar_linux`.
- Because the bundled CLI is on `PATH`, `find_cli()` will discover it before failing over to host paths.
- The app continues to read usage credentials from the user home directory at runtime.

## Portability Expectation

- First target: your current Linux desktop and similar mainstream desktop distributions with working GTK tray support.
- This is a real AppImage, but not a promise of perfect behavior on every compositor or minimal distro.
- If needed, later work can focus on broader desktop compatibility or a different cross-platform UI stack.

## Testing Strategy

- Add unit tests for packaging metadata generation:
  - AppDir path layout
  - launcher environment
  - desktop file content
- Add a packaging script smoke test mode that builds an AppDir without producing the final AppImage.
- Manual verification:
  - build AppImage
  - run it
  - confirm bundled CLI is used
  - confirm live providers still appear
