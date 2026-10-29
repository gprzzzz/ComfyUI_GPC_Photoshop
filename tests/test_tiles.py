import pytest

torch = pytest.importorskip("torch")


@pytest.fixture
def tiles(pkg):
    from gpc_photoshop.nodes import tiles

    return tiles


def test_layout_matches_krita_for_a_1080p_upscale(tiles):
    # Krita's ETN_TileLayout made two tiles for 1920x1088 at 896 / 48.
    t = tiles.layout(1920, 1088, 896, 48)
    assert [(i["x"], i["y"]) for i in t] == [
        ((0, 1008, 0, 960), (0, 1088, 0, 1088)),
        ((912, 1920, 960, 1920), (0, 1088, 0, 1088)),
    ]
    assert len(tiles.layout(800, 600, 896, 48)) == 1
    assert len(tiles.layout(4000, 3000, 896, 48)) == 4 * 3


def test_weights_fade_in_over_earlier_tiles_only(tiles):
    first, second = tiles.layout(1920, 1088, 896, 48)
    assert bool((tiles.tile_weight(first, 24) == 1).all())
    w = tiles.tile_weight(second, 24)[0]  # one row, x from 912
    edge = 960 - 912
    assert w[0] == 0 and w[edge - 13] == 0
    assert 0.4 < w[edge] < 0.6
    assert w[edge + 12] == 1 and bool((w[edge + 12:] == 1).all())
    assert bool((w[1:] >= w[:-1]).all())


class FakeRefine:
    """Stands in for sampling: returns a constant per tile, records the tiles it saw."""

    def __init__(self, node, values):
        self.values = list(values)
        self.seen = []
        node.sample_tile = self

    def __call__(self, model, positive, negative, vae, tile, hint, weight, *rest):
        self.seen.append((tile.shape, hint.shape, weight.shape))
        return torch.full_like(tile[:, :, :, :3], self.values[len(self.seen) - 1])


def refine(tiles, image, values, **kw):
    node = tiles.GPCPSTiledRefine()
    fake = FakeRefine(node, values)
    args = dict(model=None, positive=None, negative=None, vae=None, image=image, noise=None, sampler=None, sigmas=None, cfg=1.5,
                tile_size=896, padding=48, blending=24, multiple=16)
    args.update(kw)
    return node.refine(**args)[0], fake


def test_every_pixel_comes_from_a_refined_tile(tiles):
    out, fake = refine(tiles, torch.zeros(1, 1088, 1920, 3), [0.3, 0.7])
    assert len(fake.seen) == 2
    assert torch.allclose(out[0, :, :900], torch.tensor(0.3))  # first tile, before the crossfade
    assert torch.allclose(out[0, :, 980:], torch.tensor(0.7))
    seam = out[0, 0, 940:980, 0]
    assert bool((seam[1:] >= seam[:-1] - 1e-6).all()) and seam[0] < 0.31 and seam[-1] > 0.69


def test_control_image_tiles_follow_the_image(tiles):
    out, fake = refine(tiles, torch.zeros(1, 600, 900, 3), [0.5], control_image=torch.zeros(1, 300, 450, 3))
    (tile_shape, hint_shape, weight_shape), = fake.seen
    assert tile_shape == hint_shape == (1, 600, 900, 3) and weight_shape == (600, 900)


def test_pad_to_multiple(tiles):
    padded, size = tiles.pad_to_multiple(torch.rand(1, 1080, 1913, 3), 16)
    assert padded.shape == (1, 1088, 1920, 3) and size == (1080, 1913)
    assert torch.equal(padded[:, 1080:, :1913], padded[:, 1079:1080, :1913].expand(1, 8, 1913, 3))
