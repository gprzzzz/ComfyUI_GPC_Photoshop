"""Marker nodes: the contract between a workflow template and the Photoshop panel.

The panel finds these nodes by class name in an API-format template, builds its
controls from them and fills in their inputs before queueing. Everything else
in the graph is ordinary ComfyUI, so any model works as long as its graph reads
the canvas from ``GPC_PS_Canvas`` and ends in ``GPC_PS_Output``.

Image inputs arrive as base64 PNG strings. Each one also takes an optional
``test_*`` input, so a template can be run and tuned inside ComfyUI first.
"""

import base64
import io
import os
import uuid

import numpy as np
import torch
from PIL import Image

import folder_paths

from . import CATEGORY
from .sizing import fit_size, needs_tiles

OUTPUT_SUBFOLDER = "gpc_photoshop"
BIG = 2**31 - 1


def decode_png(data):
    """A base64 (or data-URL) image as a PIL image, or None when empty."""
    if not data:
        return None
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data)))


def image_tensor(img):
    """PIL image -> ``[1, H, W, 3]`` float."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(rgb)[None]


def mask_tensor(img):
    """PIL image -> ``[1, H, W]`` float, white = inpaint."""
    return torch.from_numpy(np.asarray(img.convert("L"), dtype=np.float32) / 255.0)[None]


def resize_image(image, width, height):
    import comfy.utils

    samples = image.movedim(-1, 1)
    return comfy.utils.common_upscale(samples, width, height, "lanczos", "disabled").movedim(1, -1)


def resize_mask(mask, width, height):
    out = torch.nn.functional.interpolate(mask[:, None], size=(height, width), mode="bilinear", align_corners=False)
    return out[:, 0].clamp(0, 1)


def _panel_input(tooltip):
    return ("STRING", {"default": "", "tooltip": tooltip})


_SRGB = []


def srgb_profile():
    """An sRGB ICC profile, so Photoshop converts results into the document's color space correctly."""
    if not _SRGB:
        try:
            from PIL import ImageCms

            _SRGB.append(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
        except (ImportError, OSError):
            _SRGB.append(None)
    return _SRGB[0]


class GPCPSCanvas:
    """The area to inpaint: the crop around the Photoshop selection, and its mask."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": _panel_input("Filled in by the Photoshop panel. Leave empty."),
                "mask": _panel_input("Filled in by the Photoshop panel. Leave empty."),
            },
            "optional": {
                "test_image": ("IMAGE", {"tooltip": "Used when running the template inside ComfyUI."}),
                "test_mask": ("MASK", {"tooltip": "Used when running the template inside ComfyUI."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT")
    RETURN_NAMES = ("image", "mask", "width", "height")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    def load(self, image, mask, test_image=None, test_mask=None):
        img = decode_png(image)
        if img is not None:
            pixels = image_tensor(img)
        elif test_image is not None:
            pixels = test_image[:1, :, :, :3]
        else:
            raise ValueError("PS Canvas has no image: queue it from Photoshop, or connect test_image.")
        h, w = pixels.shape[1:3]

        m = decode_png(mask)
        if m is not None:
            selection = mask_tensor(m)
        elif test_mask is not None:
            selection = test_mask[:1]
        else:
            selection = torch.ones((1, h, w))
        if selection.shape[1:] != (h, w):
            selection = resize_mask(selection, w, h)
        return pixels, selection, w, h


class GPCPSReferenceImage:
    """An extra image picked in the panel (a layer or a file). ``provided`` is False when the slot is empty."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "slot": ("INT", {"default": 1, "min": 1, "max": 16, "tooltip": "Panel slot number."}),
                "label": ("STRING", {"default": "Reference 1"}),
                "image": _panel_input("Filled in by the Photoshop panel. Leave empty."),
            },
            "optional": {"test_image": ("IMAGE",)},
        }

    RETURN_TYPES = ("IMAGE", "BOOLEAN")
    RETURN_NAMES = ("image", "provided")
    FUNCTION = "load"
    CATEGORY = CATEGORY

    def load(self, slot, label, image, test_image=None):
        img = decode_png(image)
        if img is not None:
            return image_tensor(img), True
        if test_image is not None:
            return test_image[:, :, :, :3], True
        return torch.zeros((1, 64, 64, 3)), False


class GPCPSReferenceLatent:
    """Adds a reference image to the conditioning, like core *Set Reference Latent*.

    For edit-style models that read ``reference_latents`` (Flux 2 / Klein,
    Kontext). An empty slot passes the conditioning through untouched, so a
    template can offer references without requiring them.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "vae": ("VAE",),
                "slot": ("INT", {"default": 1, "min": 1, "max": 16, "tooltip": "Panel slot number."}),
                "label": ("STRING", {"default": "Reference 1"}),
                "image": _panel_input("Filled in by the Photoshop panel. Leave empty."),
            },
            "optional": {"test_image": ("IMAGE",)},
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    FUNCTION = "apply"
    CATEGORY = CATEGORY

    def apply(self, conditioning, vae, slot, label, image, test_image=None):
        import node_helpers

        img = decode_png(image)
        pixels = image_tensor(img) if img is not None else test_image
        if pixels is None:
            return (conditioning,)
        latent = vae.encode(pixels[:, :, :, :3])
        return (node_helpers.conditioning_set_values(conditioning, {"reference_latents": [latent]}, append=True),)


class GPCPSText:
    """A text box in the panel (the prompt, or any other text a template wants)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "label": ("STRING", {"default": "Prompt"}),
                "text": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "advanced": ("BOOLEAN", {"default": False, "tooltip": "Show it under Advanced instead of in the main area."}),
                "hint": ("STRING", {"default": "", "tooltip": "One line the panel shows when hovering the control."}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "value"
    CATEGORY = CATEGORY

    def value(self, label, text, **_):
        return (text,)


def _number_inputs(kind, default, step):
    return {
        "required": {
            "label": ("STRING", {"default": "Value"}),
            "value": (kind, {"default": default, "min": -BIG, "max": BIG, "step": step}),
            "min": (kind, {"default": 0, "min": -BIG, "max": BIG, "step": step}),
            "max": (kind, {"default": 100, "min": -BIG, "max": BIG, "step": step}),
            "step": (kind, {"default": step, "min": 0, "max": BIG, "step": step}),
            "advanced": ("BOOLEAN", {"default": False, "tooltip": "List it after the others under Advanced."}),
        },
        "optional": {
            "main": ("BOOLEAN", {"default": False, "tooltip": "Show it in the panel's main area, next to the prompt."}),
            "hint": ("STRING", {"default": "", "tooltip": "One line the panel shows when hovering the control."}),
        },
    }


class GPCPSInt:
    """A whole-number control in the panel (steps, batch size, mask grow, ...)."""

    @classmethod
    def INPUT_TYPES(cls):
        return _number_inputs("INT", 1, 1)

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("value",)
    FUNCTION = "get"
    CATEGORY = CATEGORY

    def get(self, value, **_):
        return (value,)


class GPCPSFloat:
    """A decimal control in the panel (strength, CFG, ...)."""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = _number_inputs("FLOAT", 1.0, 0.01)
        inputs["required"]["max"] = ("FLOAT", {"default": 1.0, "min": -BIG, "max": BIG, "step": 0.01})
        return inputs

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("value",)
    FUNCTION = "get"
    CATEGORY = CATEGORY

    def get(self, value, **_):
        return (value,)


class GPCPSToggle:
    """An on/off switch in the panel.

    ``number`` is ``on_number`` or ``off_number``, for switching a strength:
    e.g. a ControlNet's strength, where 0 skips the ControlNet.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "label": ("STRING", {"default": "Option"}),
                "value": ("BOOLEAN", {"default": False}),
                "advanced": ("BOOLEAN", {"default": False, "tooltip": "List it after the others under Advanced."}),
            },
            "optional": {
                "main": ("BOOLEAN", {"default": False, "tooltip": "Show it in the panel's main area, next to the prompt."}),
                "on_number": ("FLOAT", {"default": 1.0, "min": -BIG, "max": BIG, "step": 0.01}),
                "off_number": ("FLOAT", {"default": 0.0, "min": -BIG, "max": BIG, "step": 0.01}),
                "hint": ("STRING", {"default": "", "tooltip": "One line the panel shows when hovering the control."}),
            },
        }

    RETURN_TYPES = ("BOOLEAN", "FLOAT")
    RETURN_NAMES = ("value", "number")
    FUNCTION = "get"
    CATEGORY = CATEGORY

    def get(self, value, on_number=1.0, off_number=0.0, **_):
        return (value, on_number if value else off_number)


class GPCPSSeed:
    """The seed. The panel randomizes it per run unless the seed is locked there."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF})}}

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("seed",)
    FUNCTION = "get"
    CATEGORY = CATEGORY

    def get(self, seed):
        return (seed,)


class GPCPSFitResolution:
    """Scales the canvas (and its mask) into the model's resolution range, snapped to a multiple.

    Small selections are scaled up so the model works at a size it is good at;
    scale the result back with the canvas ``width`` / ``height``.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "min_megapixels": ("FLOAT", {"default": 0.6, "min": 0.01, "max": 16.0, "step": 0.05}),
                "max_megapixels": ("FLOAT", {"default": 1.2, "min": 0.01, "max": 16.0, "step": 0.05}),
                "multiple": ("INT", {"default": 16, "min": 1, "max": 256}),
            },
            "optional": {
                "mask": ("MASK",),
                "scale": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 8.0, "step": 0.05, "tooltip": "Scale the crop by this first, then fit it into the range."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT")
    RETURN_NAMES = ("image", "mask", "width", "height")
    FUNCTION = "fit"
    CATEGORY = CATEGORY

    def fit(self, image, min_megapixels, max_megapixels, multiple, mask=None, scale=1.0):
        h, w = image.shape[1:3]
        nw, nh = fit_size(w * scale, h * scale, min_megapixels, max_megapixels, multiple)
        if mask is None:
            mask = torch.ones((1, h, w))
        return resize_image(image, nw, nh), resize_mask(mask, nw, nh), nw, nh


class GPCPSAutoTile:
    """Turns tiled sampling on when the crop is too big for one piece.

    Without tiles a big crop has to be shrunk to ``untiled_max_megapixels`` and
    stretched back, which loses detail. ``tiled`` drives the template's tiling
    switches; ``max_megapixels`` is the size cap to fit the crop into. With
    ``auto`` off, it never tiles (faster, softer on big selections).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "auto": ("BOOLEAN", {"default": True}),
                "scale": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 8.0, "step": 0.05}),
                "untiled_max_megapixels": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 16.0, "step": 0.05}),
                "tiled_max_megapixels": ("FLOAT", {"default": 6.0, "min": 0.1, "max": 64.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("BOOLEAN", "FLOAT")
    RETURN_NAMES = ("tiled", "max_megapixels")
    FUNCTION = "pick"
    CATEGORY = CATEGORY

    def pick(self, image, auto, scale, untiled_max_megapixels, tiled_max_megapixels):
        h, w = image.shape[1:3]
        tiled = bool(auto) and needs_tiles(w, h, scale, untiled_max_megapixels)
        return (tiled, tiled_max_megapixels if tiled else untiled_max_megapixels)


class GPCPSNoiseMask:
    """*Set Latent Noise Mask*, except when the mask covers everything.

    Then no noise mask is set and the whole latent is regenerated as a plain
    edit, the way Krita AI Diffusion handles a full selection.
    """

    FULL = 0.999

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"samples": ("LATENT",), "mask": ("MASK",)}}

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("samples",)
    FUNCTION = "apply"
    CATEGORY = CATEGORY

    def apply(self, samples, mask):
        out = samples.copy()
        out.pop("noise_mask", None)
        if float(mask.min()) < self.FULL:
            out["noise_mask"] = mask.reshape((-1, 1, mask.shape[-2], mask.shape[-1]))
        return (out,)


class GPCPSFullSelectionSwitch:
    """Passes ``partial`` through, or ``full`` when the mask covers everything.

    For steps that only make sense with unselected surroundings: Color Match
    (INPAINT_ColorMatch) returns black when nothing is left outside the mask.
    Only the branch that is used gets computed.
    """

    FULL = 0.999

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask": ("MASK",),
                "partial": ("IMAGE", {"lazy": True, "tooltip": "Used for a selection with surroundings."}),
                "full": ("IMAGE", {"lazy": True, "tooltip": "Used when the whole crop is selected."}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "pick"
    CATEGORY = CATEGORY

    def _full(self, mask):
        return float(mask.min()) >= self.FULL

    def check_lazy_status(self, mask, partial=None, full=None):
        return ["full"] if self._full(mask) else ["partial"]

    def pick(self, mask, partial=None, full=None):
        return (full if self._full(mask) else partial,)


class GPCPSJoinText:
    """Joins two texts with a separator, leaving out an empty one (so no stray ", ")."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "first": ("STRING", {"default": "", "multiline": True}),
                "second": ("STRING", {"default": "", "multiline": True}),
                "separator": ("STRING", {"default": ", "}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "join"
    CATEGORY = CATEGORY

    def join(self, first, second, separator):
        parts = [p.strip().strip(",").strip() for p in (first, second)]
        return (separator.join(p for p in parts if p),)


PLACEMENTS = ["over selection", "upscaled"]
MASK_AS = ["transparency", "layer mask"]
MODES = ["edit", "refine", "upscale", "magnific"]


class GPCPSOutput:
    """Sends results back to Photoshop as PNGs. With ``mask``, it becomes the result's transparency.

    ``placement`` tells the panel what the results are: "over selection" places
    them 1:1 over the crop; "upscaled" results are larger than what was sent,
    and open as a new document (whole image) or go over the selection as a smart
    object holding the full-size pixels. ``mode`` is the panel tab the template
    is listed under. ``mask_as`` "layer mask" sends the mask on its own, for the
    panel to put on the placed layer, so the whole frame stays in the result and
    the blend can be painted afterwards.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"images": ("IMAGE",)},
            "optional": {
                "mask": ("MASK",),
                "placement": (PLACEMENTS, {"default": PLACEMENTS[0]}),
                "mode": (MODES, {"default": MODES[0], "tooltip": "The panel tab: Edit (inpaint with an edit model), Refine (img2img), Upscale or Magnific (paid, online)."}),
                "mask_as": (MASK_AS, {"default": MASK_AS[0], "tooltip": "transparency: cut the result out with the mask. layer mask: keep the whole result and add the mask to its layer."}),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = CATEGORY

    def save(self, images, mask=None, placement=None, mode=None, mask_as=None):
        folder = os.path.join(folder_paths.get_temp_directory(), OUTPUT_SUBFOLDER)
        os.makedirs(folder, exist_ok=True)
        if mask is not None and mask_as == "layer mask":
            # One grayscale mask per image, at the mask's own size (the crop's): the
            # panel scales it onto the placed layer.
            masks = [mask[min(i, len(mask) - 1)] for i in range(len(images))]
            return {"ui": {"images": _write_pngs(folder, images[:, :, :, :3]), "gpc_masks": _write_pngs(folder, masks)}}
        h, w = images.shape[1:3]
        if mask is not None and mask.shape[1:] != (h, w):
            mask = resize_mask(mask, w, h)
        pixels = []
        for i, image in enumerate(images):
            if mask is not None:
                pixels.append(torch.cat([image[:, :, :3], mask[min(i, len(mask) - 1)][:, :, None]], dim=-1))
            else:
                pixels.append(image if image.shape[-1] == 4 else image[:, :, :3])
        return {"ui": {"images": _write_pngs(folder, pixels)}}


def _write_pngs(folder, images):
    """Saves ``[H, W, C]`` (or ``[H, W]`` grayscale) tensors as PNGs; returns ComfyUI image refs."""
    results = []
    for image in images:
        array = (image.clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
        name = f"ps_{uuid.uuid4().hex[:12]}.png"
        profile = srgb_profile() if array.ndim == 3 else None
        Image.fromarray(array).save(os.path.join(folder, name), compress_level=1, icc_profile=profile)
        results.append({"filename": name, "subfolder": OUTPUT_SUBFOLDER, "type": "temp"})
    return results


NODE_CLASS_MAPPINGS = {
    "GPC_PS_Canvas": GPCPSCanvas,
    "GPC_PS_ReferenceImage": GPCPSReferenceImage,
    "GPC_PS_ReferenceLatent": GPCPSReferenceLatent,
    "GPC_PS_Text": GPCPSText,
    "GPC_PS_Int": GPCPSInt,
    "GPC_PS_Float": GPCPSFloat,
    "GPC_PS_Toggle": GPCPSToggle,
    "GPC_PS_Seed": GPCPSSeed,
    "GPC_PS_FitResolution": GPCPSFitResolution,
    "GPC_PS_AutoTile": GPCPSAutoTile,
    "GPC_PS_NoiseMask": GPCPSNoiseMask,
    "GPC_PS_FullSelectionSwitch": GPCPSFullSelectionSwitch,
    "GPC_PS_JoinText": GPCPSJoinText,
    "GPC_PS_Output": GPCPSOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GPC_PS_Canvas": "PS Canvas (GPC)",
    "GPC_PS_ReferenceImage": "PS Reference Image (GPC)",
    "GPC_PS_ReferenceLatent": "PS Reference Latent (GPC)",
    "GPC_PS_Text": "PS Text (GPC)",
    "GPC_PS_Int": "PS Int (GPC)",
    "GPC_PS_Float": "PS Float (GPC)",
    "GPC_PS_Toggle": "PS Toggle (GPC)",
    "GPC_PS_Seed": "PS Seed (GPC)",
    "GPC_PS_FitResolution": "PS Fit Resolution (GPC)",
    "GPC_PS_AutoTile": "PS Auto Tile (GPC)",
    "GPC_PS_NoiseMask": "PS Noise Mask (GPC)",
    "GPC_PS_FullSelectionSwitch": "PS Full Selection Switch (GPC)",
    "GPC_PS_JoinText": "PS Join Text (GPC)",
    "GPC_PS_Output": "PS Output (GPC)",
}
