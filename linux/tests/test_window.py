from codexbar_linux.window import (
    FocusBehavior,
    WindowChromeState,
    WindowDragState,
    _clamp_window_origin,
    _default_window_origin,
)


def test_default_window_origin_anchors_to_top_right():
    origin = _default_window_origin(monitor_x=10, monitor_y=20, monitor_width=300, window_width=100)
    assert origin == (202, 70)


def test_clamp_window_origin_keeps_popup_inside_monitor():
    origin = _clamp_window_origin(
        x=350,
        y=-20,
        monitor_x=10,
        monitor_y=20,
        monitor_width=300,
        monitor_height=200,
        window_width=100,
        window_height=80,
    )

    assert origin == (210, 20)


def test_drag_state_retains_manual_origin_after_drag():
    state = WindowDragState()
    state.begin((100, 200))

    assert state.update(15.2, -10.8) == (115, 189)
    assert state.end(15.2, -10.8) == (115, 189)
    assert state.manual_origin == (115, 189)


def test_focus_behavior_does_not_hide_window_by_default():
    behavior = FocusBehavior()

    assert behavior.should_hide_on_focus_leave() is False


def test_window_chrome_uses_header_drag_and_minimize_to_tray():
    chrome = WindowChromeState()

    assert chrome.draggable_from_header is True
    assert chrome.minimize_hides_to_tray is True
