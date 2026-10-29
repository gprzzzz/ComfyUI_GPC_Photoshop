import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "sizing", os.path.join(os.path.dirname(__file__), "..", "nodes", "sizing.py"))
sizing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sizing)


def test_small_crop_scales_up_into_range():
    w, h = sizing.fit_size(544, 560, 0.6, 1.2, 16)
    assert (w % 16, h % 16) == (0, 0)
    assert 0.55 * sizing.MEGAPIXEL < w * h < 0.7 * sizing.MEGAPIXEL
    assert abs(w / h - 544 / 560) < 0.03


def test_large_crop_scales_down():
    w, h = sizing.fit_size(4000, 3000, 0.6, 1.2, 16)
    assert w * h <= 1.25 * sizing.MEGAPIXEL
    assert abs(w / h - 4 / 3) < 0.02


def test_in_range_only_snaps():
    assert sizing.fit_size(1010, 1000, 0.6, 1.2, 16) == (1008, 992)


def test_never_below_one_multiple():
    assert sizing.fit_size(1, 2000, 0.0001, 16, 16)[0] == 16
