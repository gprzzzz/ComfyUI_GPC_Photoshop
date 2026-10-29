import pytest

torch = pytest.importorskip("torch")


@pytest.fixture
def td(pkg):
    from gpc_photoshop.nodes import tiled_diffusion

    return tiled_diffusion


def test_tiles_cover_the_axis_with_overlap(td):
    for length in (64, 128, 216, 376):
        for offset in (0, 8, 40, 88):
            starts = td.axis_starts(length, 128, 32, offset)
            if length <= 128:
                assert starts == [0]
                continue
            assert starts[0] == 0 and starts[-1] + 128 == length
            assert all(0 < b - a <= 128 - 32 for a, b in zip(starts, starts[1:]))
            assert all(s % 8 == 0 for s in starts)
    assert td.axis_starts(100, 128, 32) == [0]


def local_model(x, t, **c):
    """A stand-in for the UNet that only looks at each pixel and the ControlNet residual there,
    so tiling it must give exactly the untiled answer."""
    out = x * 2 + t.view(-1, 1, 1, 1)
    control = c.get("control")
    if control:
        res = control["output"][0]
        out = out + torch.nn.functional.interpolate(res[:, :4], size=x.shape[-2:], mode="nearest")
    return out


def test_tiling_a_local_model_changes_nothing(td):
    x = torch.randn(2, 4, 216, 376)
    t = torch.tensor([0.7, 0.7])
    control = {"output": [torch.randn(2, 8, 54, 94)], "middle": [None]}
    c = {"c_crossattn": torch.randn(2, 77, 2048), "control": control, "transformer_options": {}}
    wrapper = td.TiledWrapper(tile=128, overlap=32, shift=True)
    tiled = wrapper(local_model, {"input": x, "timestep": t, "c": c, "cond_or_uncond": [0, 1]})
    assert torch.allclose(tiled, local_model(x, t, **c), atol=1e-5)


def test_each_tile_gets_its_slice_of_the_controlnet(td):
    seen = []

    def model(x, t, **c):
        seen.append((x.shape[-2:], c["control"]["input"][0].shape[-2:], c["c_concat"].shape[-2:], c["c_crossattn"].shape))
        return x

    x = torch.zeros(1, 4, 256, 256)
    c = {"control": {"input": [torch.zeros(1, 320, 64, 64)]}, "c_concat": torch.zeros(1, 5, 256, 256), "c_crossattn": torch.zeros(1, 77, 2048)}
    td.TiledWrapper(tile=128, overlap=32, shift=False)(model, {"input": x, "timestep": torch.tensor([1.0]), "c": c, "cond_or_uncond": [0]})
    assert len(seen) == 9
    assert all(s == (torch.Size([128, 128]), torch.Size([32, 32]), torch.Size([128, 128]), torch.Size([1, 77, 2048])) for s in seen)


def test_small_images_run_untiled_and_the_grid_shifts_by_step(td):
    calls = []
    td.TiledWrapper(128, 32, True)(lambda x, t, **c: calls.append(x.shape) or x, {"input": torch.zeros(1, 4, 96, 120), "timestep": torch.tensor([0.5]), "c": {}, "cond_or_uncond": [0]})
    assert calls == [torch.Size([1, 4, 96, 120])]
    offsets = {td.step_offset(torch.tensor([s]), 96) for s in (14.6, 9.1, 5.3, 2.2, 0.9)}
    assert len(offsets) > 1 and all(o % 8 == 0 and 0 <= o < 96 for o in offsets)
    assert td.step_offset(torch.tensor([3.3]), 96) == td.step_offset(torch.tensor([3.3]), 96)


def test_odd_latent_sizes_are_refused_clearly(td):
    with pytest.raises(ValueError, match="multiples of 32 px"):
        td.TiledWrapper(128, 32, True)(local_model, {"input": torch.zeros(1, 4, 130, 300), "timestep": torch.tensor([1.0]), "c": {}, "cond_or_uncond": [0]})


class FakePatcher:
    def __init__(self):
        self.model_options = {"model_function_wrapper": "previous"}
        self.removed = []

    def clone(self):
        return self

    def remove_wrappers_with_key(self, kind, key):
        self.removed.append((kind, key))

    def set_model_unet_function_wrapper(self, w):
        self.model_options["model_function_wrapper"] = w


def test_patch_chains_the_previous_wrapper_and_drops_caches(td):
    node = td.GPCPSTiledDiffusion()
    model = FakePatcher()
    (out,) = node.patch(model, True, 1024, 256, True)
    w = out.model_options["model_function_wrapper"]
    assert (w.tile, w.overlap, w.previous) == (128, 32, "previous")
    assert ("diffusion_model", "easycache") in model.removed
    assert node.patch(model, False, 1024, 256, True)[0] is model
