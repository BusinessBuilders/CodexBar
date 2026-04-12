from codexbar_linux.usage_bar import bar_color


def test_healthy_color():
    assert bar_color(used_percent=2.0) == "#ff9500"   # orange (low usage = normal)


def test_warning_color():
    assert bar_color(used_percent=76.0) == "#ffd60a"  # yellow at 75%+


def test_danger_color():
    assert bar_color(used_percent=91.0) == "#ff453a"  # red at 90%+


def test_boundary_75():
    assert bar_color(used_percent=75.0) == "#ff9500"
    assert bar_color(used_percent=75.1) == "#ffd60a"


def test_boundary_90():
    assert bar_color(used_percent=90.0) == "#ffd60a"
    assert bar_color(used_percent=90.1) == "#ff453a"


def test_clamp_over_100():
    assert bar_color(used_percent=150.0) == "#ff453a"


def test_clamp_under_0():
    assert bar_color(used_percent=-5.0) == "#ff9500"
