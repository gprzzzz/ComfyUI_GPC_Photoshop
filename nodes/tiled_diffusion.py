"""Tiled diffusion: sample an image larger than the model likes, without seams.

Written from the published methods, not from other implementations:
MultiDiffusion (Bar-Tal et al., 2023) and Mixture of Diffusers (Jiménez, 2023)
denoise overlapping tiles at every step and blend their predictions, Mixture of
Diffusers with Gaussian weights; SpotDiffusion (Frolov et al., 2024) moves the
tile grid between steps so no seam stays in one place. This node does all three:
Gaussian-weighted overlapping tiles on a grid that shifts each step.

Because tiles are blended at every step, none of them is ever finished alone,
which is what leaves seams in tile-by-tile upscalers. ControlNets are computed
by ComfyUI for the whole image before the model runs; each tile gets its slice.
"""

import random

import torch

from . import CATEGORY

ALIGN = 8  # latent px; keeps tile edges on whole pixels of every UNet level (SDXL downsamples 4x)

# Speed-ups that reuse a previous model output: across tiles they'd reuse another tile's.
CACHE_WRAPPERS = (("outer_sample", "easycache"), ("calc_cond_batch", "easycache"), ("diffusion_model", "easycache"),
                  ("outer_sample", "lazycache"), ("predict_noise", "lazycache"))


def _align(v):
    return max(ALIGN, int(round(v / ALIGN)) * ALIGN)


def axis_starts(length, tile, overlap, offset=0):
    """Tile start positions covering ``[0, length)`` with tiles of ``tile``, at least
    ``overlap`` apart, the grid shifted left by ``offset``. All in latent px."""
    if length <= tile:
        return [0]
    stride = tile - overlap
    starts = []
    s = -offset
    while True:
        clamped = min(max(s, 0), length - tile)
        if not starts or clamped != starts[-1]:
            starts.append(clamped)
        if clamped >= length - tile:
            return starts
        s += stride


def gaussian(size, device):
    """Mixture of Diffusers' weights: highest in the middle of a tile, never zero."""
    pos = torch.arange(size, dtype=torch.float32, device=device)
    sigma = 0.3 * size
    return torch.exp(-0.5 * ((pos - (size - 1) / 2) / sigma) ** 2)


def step_offset(timestep, stride):
    """A grid shift for this step, the same every run (seeded by the timestep)."""
    if stride <= ALIGN:
        return 0
    rng = random.Random(round(float(timestep.flatten()[0]), 5))
    return rng.randrange(0, stride // ALIGN) * ALIGN


def crop_conditioning(c, y0, y1, x0, x1, h, w):
    """The model kwargs for one tile: spatial tensors (and ControlNet residuals) cropped."""
    def crop(t):
        if not isinstance(t, torch.Tensor) or t.ndim < 4:
            return t
        th, tw = t.shape[-2:]
        if (th, tw) == (h, w):
            return t[..., y0:y1, x0:x1]
        fy, fx = h / th, w / tw  # a downsampled level, e.g. a ControlNet residual
        if fy >= 1 and fx >= 1 and float(fy).is_integer() and float(fx).is_integer():
            fy, fx = int(fy), int(fx)
            return t[..., y0 // fy:y1 // fy, x0 // fx:x1 // fx]
        return t

    out = dict(c)
    for k, v in c.items():
        if k == "control" and isinstance(v, dict):
            out[k] = {level: [crop(t) if t is not None else None for t in ts] for level, ts in v.items()}
        elif k != "transformer_options":
            out[k] = crop(v)
    return out


class TiledWrapper:
    def __init__(self, tile, overlap, shift, previous=None):
        self.tile, self.overlap, self.shift, self.previous = tile, overlap, shift, previous

    def call(self, apply_model, x, t, c, cond_or_uncond):
        if self.previous is not None:
            return self.previous(apply_model, {"input": x, "timestep": t, "c": c, "cond_or_uncond": cond_or_uncond})
        return apply_model(x, t, **c)

    def __call__(self, apply_model, args):
        x, t, c = args["input"], args["timestep"], args["c"]
        h, w = x.shape[-2:]
        tile_h, tile_w = min(self.tile, h), min(self.tile, w)
        if tile_h == h and tile_w == w:
            return self.call(apply_model, x, t, c, args["cond_or_uncond"])
        if h % 4 or w % 4:
            raise ValueError(f"PS Tiled Diffusion needs the image size in multiples of 32 px (latent {w}x{h}).")

        stride = self.tile - self.overlap
        offset = step_offset(t, stride) if self.shift else 0
        out = torch.zeros_like(x)
        total = torch.zeros((1, 1, h, w), device=x.device, dtype=x.dtype)
        for y0 in axis_starts(h, tile_h, self.overlap, offset):
            for x0 in axis_starts(w, tile_w, self.overlap, offset):
                y1, x1 = y0 + tile_h, x0 + tile_w
                pred = self.call(apply_model, x[..., y0:y1, x0:x1], t, crop_conditioning(c, y0, y1, x0, x1, h, w), args["cond_or_uncond"])
                weight = (gaussian(tile_h, x.device)[:, None] * gaussian(tile_w, x.device)[None, :]).to(x.dtype)
                out[..., y0:y1, x0:x1] += pred * weight
                total[..., y0:y1, x0:x1] += weight
        return out / total


class GPCPSTiledDiffusion:
    """Samples images larger than the model's native size in overlapping tiles,
    blended at every step so there are no seams. Off (``enabled`` false), the model
    passes through unchanged."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "enabled": ("BOOLEAN", {"default": True}),
                "tile_size": ("INT", {"default": 1024, "min": 256, "max": 4096, "step": 64, "tooltip": "In pixels: the model's native size."}),
                "overlap": ("INT", {"default": 256, "min": 64, "max": 2048, "step": 64, "tooltip": "In pixels: how far tiles overlap."}),
                "shift_each_step": ("BOOLEAN", {"default": True, "tooltip": "Move the tile grid between steps, so no seam stays in place."}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "patch"
    CATEGORY = CATEGORY

    def patch(self, model, enabled, tile_size, overlap, shift_each_step):
        if not enabled:
            return (model,)
        tile = _align(tile_size / 8)
        overlap = min(_align(overlap / 8), tile - ALIGN)
        patched = model.clone()
        for wrapper_type, key in CACHE_WRAPPERS:
            try:
                patched.remove_wrappers_with_key(wrapper_type, key)
            except (AttributeError, KeyError):
                pass
        previous = patched.model_options.get("model_function_wrapper")
        patched.set_model_unet_function_wrapper(TiledWrapper(tile, overlap, shift_each_step, previous))
        return (patched,)


NODE_CLASS_MAPPINGS = {"GPC_PS_TiledDiffusion": GPCPSTiledDiffusion}
NODE_DISPLAY_NAME_MAPPINGS = {"GPC_PS_TiledDiffusion": "PS Tiled Diffusion (GPC)"}

