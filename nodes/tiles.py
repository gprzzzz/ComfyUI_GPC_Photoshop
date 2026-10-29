"""Tiled refine: the upscale templates' sampler, for images of any size.

Krita AI Diffusion builds one set of nodes per tile, which a fixed template
can't. This node lays out the tiles itself and samples them one after another,
each blended into the result over its overlap with the tiles before it.
"""

import torch

from . import CATEGORY


def axis_tiles(length, tile, padding):
    """``(start, end, core_start, core_end)`` per tile along one axis.

    Cores split the axis evenly into tiles of at least ``tile`` pixels (one
    tile when it's shorter); each tile adds ``padding`` of context on either
    side, inside the image.
    """
    count = max(1, length // tile)
    edges = [round(i * length / count) for i in range(count + 1)]
    return [(max(0, a - padding), min(length, b + padding), a, b) for a, b in zip(edges, edges[1:])]


def layout(width, height, tile, padding):
    """Tiles in sampling order (rows top to bottom, left to right), as dicts of pixel ranges."""
    return [
        {"x": x, "y": y, "row": r, "col": c}
        for r, y in enumerate(axis_tiles(height, tile, padding))
        for c, x in enumerate(axis_tiles(width, tile, padding))
    ]


def _ramp(size, start, core_start, blending, before):
    """Weights along one axis of a tile: a crossfade of ``blending`` px centered on
    the core's leading edge when a tile was sampled ``before`` on that side, else 1."""
    w = torch.ones(size)
    if before and blending > 0:
        pos = torch.arange(size, dtype=torch.float32) + start + 0.5
        w = ((pos - (core_start - blending / 2)) / blending).clamp(0, 1)
    return w


def tile_weight(t, blending):
    """How much of tile ``t`` replaces what's already there: [H, W] in 0-1.

    Later tiles fade in over earlier ones (above and to the left) and fully
    cover the rest, so no original pixels show through between tiles.
    """
    x0, x1, cx0, _ = t["x"]
    y0, y1, cy0, _ = t["y"]
    wx = _ramp(x1 - x0, x0, cx0, blending, t["col"] > 0)
    wy = _ramp(y1 - y0, y0, cy0, blending, t["row"] > 0)
    return wy[:, None] * wx[None, :]


def pad_to_multiple(image, multiple):
    """Pads [B, H, W, C] at the bottom/right by edge repeat. Returns (padded, (H, W))."""
    h, w = image.shape[1:3]
    ph, pw = (-h) % multiple, (-w) % multiple
    if ph or pw:
        image = torch.nn.functional.pad(image.movedim(-1, 1), (0, pw, 0, ph), mode="replicate").movedim(1, -1)
    return image, (h, w)


class GPCPSTiledRefine:
    """Refines a (typically just upscaled) image tile by tile with img2img sampling.

    With ``model_patch`` (a Z-Image / Qwen Image Fun ControlNet from *Load Model
    Patch*), each tile is sampled with that ControlNet guided by the same tile
    of ``control_image`` (default: the image itself), like a tile ControlNet.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "image": ("IMAGE",),
                "noise": ("NOISE",),
                "sampler": ("SAMPLER",),
                "sigmas": ("SIGMAS",),
                "cfg": ("FLOAT", {"default": 1.5, "min": 0.0, "max": 30.0, "step": 0.1}),
                "tile_size": ("INT", {"default": 896, "min": 256, "max": 4096, "step": 16, "tooltip": "Smallest tile; tiles split the image evenly."}),
                "padding": ("INT", {"default": 48, "min": 0, "max": 512, "tooltip": "Context added around each tile."}),
                "blending": ("INT", {"default": 24, "min": 0, "max": 512, "tooltip": "Width of the crossfade between tiles."}),
                "multiple": ("INT", {"default": 16, "min": 1, "max": 128, "tooltip": "The model's size multiple; tiles are padded to it."}),
            },
            "optional": {
                "model_patch": ("MODEL_PATCH",),
                "control_strength": ("FLOAT", {"default": 0.5, "min": -10.0, "max": 10.0, "step": 0.01}),
                "control_image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "refine"
    CATEGORY = CATEGORY

    def refine(self, model, positive, negative, vae, image, noise, sampler, sigmas, cfg, tile_size, padding, blending, multiple,
               model_patch=None, control_strength=0.5, control_image=None):
        control = image if control_image is None else control_image
        if control.shape[1:3] != image.shape[1:3]:
            from .markers import resize_image

            control = resize_image(control, image.shape[2], image.shape[1])
        out = image[:, :, :, :3].clone()
        h, w = out.shape[1:3]
        for t in layout(w, h, tile_size, padding):
            (x0, x1, _, _), (y0, y1, _, _) = t["x"], t["y"]
            weight = tile_weight(t, blending).to(out.device)
            tile = out[:, y0:y1, x0:x1]
            hint = control[:, y0:y1, x0:x1, :3]
            refined = self.sample_tile(model, positive, negative, vae, tile, hint, weight, noise, sampler, sigmas, cfg, multiple,
                                       model_patch, control_strength)
            out[:, y0:y1, x0:x1] = tile * (1 - weight[None, :, :, None]) + refined * weight[None, :, :, None]
        return (out.clamp(0, 1),)

    def sample_tile(self, model, positive, negative, vae, tile, hint, weight, noise, sampler, sigmas, cfg, multiple,
                    model_patch, control_strength):
        """One tile through img2img sampling, as SamplerCustomAdvanced with a CFG guider would."""
        import comfy.samplers
        import latent_preview

        padded, (th, tw) = pad_to_multiple(tile, multiple)
        hint, _ = pad_to_multiple(hint, multiple)
        mask, _ = pad_to_multiple(weight[None, :, :, None], multiple)
        if model_patch is not None and control_strength != 0:
            from comfy_extras.nodes_model_patch import ZImageFunControlnet

            model = ZImageFunControlnet().diffsynth_controlnet(model, model_patch, vae, image=hint, strength=control_strength)[0]

        latent = vae.encode(padded[:, :, :, :3])
        guider = comfy.samplers.CFGGuider(model)
        guider.set_conds(positive, negative)
        guider.set_cfg(cfg)
        callback = latent_preview.prepare_callback(guider.model_patcher, sigmas.shape[-1] - 1, {})
        samples = guider.sample(noise.generate_noise({"samples": latent}), latent, sampler, sigmas,
                                denoise_mask=mask.movedim(-1, 1), callback=callback, seed=noise.seed)
        decoded = vae.decode(samples)
        if decoded.ndim == 5:  # video VAEs return [B, T, H, W, C]
            decoded = decoded.reshape(-1, *decoded.shape[-3:])
        return decoded[:, :th, :tw, :3].to(tile.device)


NODE_CLASS_MAPPINGS = {"GPC_PS_TiledRefine": GPCPSTiledRefine}
NODE_DISPLAY_NAME_MAPPINGS = {"GPC_PS_TiledRefine": "PS Tiled Refine (GPC)"}
