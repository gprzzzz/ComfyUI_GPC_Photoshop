import importlib.util
import os

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location("colour", os.path.join(os.path.dirname(__file__), "..", "nodes", "colour.py"))
colour = importlib.util.module_from_spec(spec)
spec.loader.exec_module(colour)


def patch(h, s, v, rows=100, width=200):
    return np.tile(np.array(colour.hsb_rgb(h, s, v), dtype=np.float32), (rows, width, 1))


def scene(sky=(203, 0.45, 0.85), leaves=(95, 0.55, 0.45), grey=(0.5, 0.5, 0.5)):
    """Sky on top, foliage, then a grey band, a black and a white strip."""
    parts = []
    if sky:
        parts.append(patch(*sky, rows=80))
    parts.append(patch(*leaves, rows=80))
    parts.append(np.tile(np.array(grey, dtype=np.float32), (30, 200, 1)))
    parts.append(np.full((5, 200, 3), 0.02, dtype=np.float32))
    parts.append(np.full((5, 200, 3), 0.86, dtype=np.float32))
    return (np.concatenate(parts) * 255).round().astype(np.uint8)


def by_key(result):
    return {f["key"]: f for f in result["findings"]}


def test_a_good_scene_passes_without_layers():
    result = colour.check(scene())
    f = by_key(result)
    assert all(f[k]["status"] == "ok" for k in ("blacks", "whites", "tint", "sky", "foliage", "spread")), f
    assert result["layers"] == []


def test_a_green_cyan_sky_gets_a_hue_layer_toward_210():
    result = colour.check(scene(sky=(185, 0.45, 0.85)))
    sky = by_key(result)["sky"]
    assert sky["status"] == "warn" and "185°" in sky["text"]
    assert len(sky["swatches"]) == 2
    (layer,) = [l for l in result["layers"] if l["name"].startswith("Sky")]
    (rng,) = layer["ranges"]
    # A bright sky aims near the horizon colour (203-210°): about +20.
    assert 17 <= rng["hue"] <= 25
    assert rng["slotName"] == "Cyans"
    lo, sustain_lo, sustain_hi, hi = rng["ramps"]
    assert sustain_lo <= 185 <= sustain_hi and lo < sustain_lo and hi > sustain_hi
    assert layer["blendIf"] == [80, 100, 255, 255]


def test_an_orange_sunset_sky_is_not_judged():
    result = colour.check(scene(sky=(30, 0.6, 0.9)))
    assert by_key(result)["sky"]["status"] == "skip"


def test_blue_green_foliage_moves_toward_82_at_most_30():
    result = colour.check(scene(leaves=(140, 0.55, 0.45)))
    assert by_key(result)["foliage"]["status"] == "warn"
    (layer,) = [l for l in result["layers"] if l["name"].startswith("Foliage hue")]
    assert layer["ranges"][0]["hue"] == -30
    assert "140°→110°" in layer["name"]


def test_spread_foliage_is_pinched_from_both_sides():
    leaves = np.concatenate([patch(75, 0.55, 0.45, rows=40), patch(115, 0.55, 0.45, rows=40)])
    img = scene()
    img[80:160] = (leaves * 255).round().astype(np.uint8)
    result = colour.check(img)
    assert by_key(result)["spread"]["status"] == "warn"
    (layer,) = [l for l in result["layers"] if l["name"].startswith("Foliage spread")]
    low, high = layer["ranges"]
    assert low["hue"] > 0 > high["hue"]


def test_raised_blacks_get_a_luminosity_levels_layer():
    img = scene().astype(np.float32) / 255
    img = (0.18 + img * 0.82) * 255  # nothing darker than 18%
    result = colour.check(img.round().astype(np.uint8))
    assert by_key(result)["blacks"]["status"] == "warn"
    (layer,) = [l for l in result["layers"] if l["kind"] == "levels"]
    assert layer["blendMode"] == "luminosity"
    lv = layer["channels"]["composite"]
    assert lv["input"][0] > 30  # input black pulled up


def test_a_green_cast_is_neutralised_on_the_green_channel_only():
    result = colour.check(scene(grey=(0.5, 0.53, 0.5)))
    assert by_key(result)["tint"]["status"] == "warn"
    (layer,) = [l for l in result["layers"] if l["name"].startswith("Neutralise")]
    assert list(layer["channels"]) == ["green"]
    lv = layer["channels"]["green"]
    lv01 = {"input": [v / 255 for v in lv["input"]], "gamma": lv["gamma"], "output": [v / 255 for v in lv["output"]]}
    assert colour.apply_levels(0.53, lv01) == pytest.approx(0.5, abs=2 / 255)


def test_fit_levels_hits_its_points():
    for low, high, mid in [((0.15, 0.03), (0.9, 0.89), None), ((0.05, 0.0), (0.7, 0.8), (0.4, 0.5)), ((0.0, 0.1), (1.0, 0.9), (0.5, 0.45))]:
        lv = colour.fit_levels(low, high, mid)
        for x, y in [low, high] + ([mid] if mid else []):
            assert colour.apply_levels(x, lv) == pytest.approx(y, abs=0.01)


def test_matching_an_image_to_itself_changes_nothing():
    img = scene()
    result = colour.match(img, img)
    assert result["layers"] == []


def test_match_moves_levels_and_ranges_toward_the_reference():
    src = scene(leaves=(105, 0.45, 0.45))
    ref = scene(leaves=(95, 0.6, 0.45))
    ref = (ref.astype(np.float32) * 0.9).round().astype(np.uint8)  # darker overall
    result = colour.match(src, ref)
    kinds = [l["kind"] for l in result["layers"]]
    assert kinds[0] == "levels" and result["layers"][0]["blendMode"] == "luminosity"
    (hs,) = [l for l in result["layers"] if l["kind"] == "hueSat"]
    greens = [r for r in hs["ranges"] if r["slotName"] == "Greens"]
    assert greens and abs(greens[0]["hue"] + 10) <= 1 and greens[0]["saturation"] > 0


def test_match_limits_how_far_hues_move():
    result = colour.match(scene(leaves=(140, 0.5, 0.45)), scene(leaves=(100, 0.5, 0.45)))
    (hs,) = [l for l in result["layers"] if l["kind"] == "hueSat"]
    assert all(abs(r["hue"]) <= colour.MATCH_HUE for r in hs["ranges"])
