from pathlib import Path

from codexbar_linux.packaging import PackagingPaths, render_apprun, render_desktop_entry, render_launcher


def test_packaging_paths_cover_expected_appdir_layout():
    paths = PackagingPaths.from_root(Path("/tmp/CodexBar.AppDir"))

    assert paths.apprun == Path("/tmp/CodexBar.AppDir/AppRun")
    assert paths.launcher == Path("/tmp/CodexBar.AppDir/usr/bin/codexbar-linux")
    assert paths.cli == Path("/tmp/CodexBar.AppDir/usr/bin/codexbar")
    assert paths.lib_dir == Path("/tmp/CodexBar.AppDir/usr/lib/codexbar-linux")
    assert paths.site_packages == Path("/tmp/CodexBar.AppDir/usr/lib/codexbar-linux/site-packages")


def test_render_launcher_sets_path_and_pythonpath():
    paths = PackagingPaths.from_root(Path("/tmp/CodexBar.AppDir"))

    launcher = render_launcher(paths)

    assert 'export PATH="$APPDIR/usr/bin:${PATH:-}"' in launcher
    assert 'export PYTHONPATH="$APPDIR/usr/lib/codexbar-linux:$APPDIR/usr/lib/codexbar-linux/site-packages' in launcher
    assert 'exec /usr/bin/python3 -m codexbar_linux "$@"' in launcher


def test_render_apprun_execs_bundled_launcher():
    paths = PackagingPaths.from_root(Path("/tmp/CodexBar.AppDir"))

    apprun = render_apprun(paths)

    assert 'exec "$HERE/usr/bin/codexbar-linux" "$@"' in apprun


def test_render_desktop_entry_uses_packaged_exec_and_icon():
    desktop = render_desktop_entry(exec_name="codexbar-linux", icon_name="codexbar-linux")

    assert "Exec=codexbar-linux" in desktop
    assert "Icon=codexbar-linux" in desktop
