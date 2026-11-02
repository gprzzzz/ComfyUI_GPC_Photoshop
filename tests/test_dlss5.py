import numpy as np
import pytest


@pytest.fixture
def dlss(pkg):
    return pkg.nodes.dlss5_enhance


def test_odd_sizes_pad_to_even_with_edge_pixels(dlss):
    frame = np.arange(3 * 5 * 4, dtype=np.uint8).reshape(3, 5, 4)
    padded = dlss.pad_even(frame, minimum=2)
    assert padded.shape == (4, 6, 4)
    assert (padded[:3, :5] == frame).all()
    assert (padded[3, :5] == frame[2]).all() and (padded[:3, 5] == frame[:, 4]).all()


def test_small_frames_pad_up_to_the_minimum(dlss):
    assert dlss.pad_even(np.zeros((10, 100, 4), np.uint8)).shape == (64, 100, 4)
    even = np.zeros((64, 64, 4), np.uint8)
    assert dlss.pad_even(even) is even


def test_output_crop_scales_the_original_size(dlss):
    assert dlss.output_crop(1001, 667, 1.0) == (1001, 667)
    assert dlss.output_crop(1001, 667, 2.0) == (2002, 1334)


def test_runtime_is_found_from_the_user_file(pkg, tmp_path, monkeypatch):
    paths = pkg.nodes.dlss5.paths
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in paths.REQUIRED_RUNTIME_FILES:
        (runtime / name).write_bytes(b"")
    monkeypatch.delenv(paths.RUNTIME_ENV, raising=False)
    paths.write_runtime_file(runtime)
    assert paths.find_runtime().root == runtime.resolve()


def test_missing_runtime_says_how_to_install(pkg, tmp_path):
    paths = pkg.nodes.dlss5.paths
    with pytest.raises(paths.RuntimeMissing, match="install_dlss5_runtime"):
        paths.find_runtime(tmp_path / "nowhere")


def test_the_inputs_default_like_the_function(dlss):
    import inspect

    inputs = dlss.GPCDLSS5Enhance.INPUT_TYPES()["optional"]
    params = inspect.signature(dlss.GPCDLSS5Enhance.enhance).parameters
    for key, (_, options) in inputs.items():
        assert params[key].default == options["default"], key
