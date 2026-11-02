"""DLSS5 Enhance: NVIDIA DLSS 5 neural rendering over still images.

The worker protocol, runtime checks and settings come from Blueforcer's
ComfyUI-DLSS5-Enhancer (MIT, in ``dlss5/``). This is one node with the settings
on it, for still images: each image in a batch is its own picture, so the
worker's temporal history is reset for every one and no motion is estimated.
"""

import logging

import numpy as np
import torch

from . import CATEGORY
from .dlss5.imaging import fit_frame, rgba_to_tensor, tensor_to_rgba
from .dlss5.paths import find_runtime
from .dlss5.session import DlssSession
from .dlss5.settings import DLSS_MODEL_PRESETS, NR_STYLES, UPSCALING_LABELS, DlssOptions, resolve_output_size

logger = logging.getLogger("GPC Photoshop")


def pad_even(rgba, minimum=64):
    """Pads an RGBA8 frame right and bottom (edge pixels repeated) to even sides of at
    least ``minimum``: DLSS sizes are even, and smaller frames are refused."""
    h, w = rgba.shape[:2]
    ph = max(minimum, h + h % 2) - h
    pw = max(minimum, w + w % 2) - w
    if not ph and not pw:
        return rgba
    return np.pad(rgba, ((0, ph), (0, pw), (0, 0)), mode="edge")


def output_crop(width, height, factor):
    """The part of an enhanced padded frame that holds the original image."""
    return round(width * factor), round(height * factor)


class GPCDLSS5Enhance:
    """Runs each image through DLSS 5 neural rendering on the native worker."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"images": ("IMAGE",)},
            # Optional, so the panel's Post button can send just the image.
            "optional": {
                "upscaling_mode": (UPSCALING_LABELS, {"default": UPSCALING_LABELS[0], "tooltip": "1x (DLAA) enhances at the image's size; the others also upscale."}),
                "nr_style": (list(NR_STYLES), {"default": "Default", "tooltip": "Natural stays closer to the source, Cinematic pushes contrast."}),
                "nr_intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Strength of the neural pass. Below 1 blends back towards the source."}),
                "local_tone_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01}),
                "local_structure_strength": ("FLOAT", {"default": 1.5, "min": 0.0, "max": 2.0, "step": 0.01, "tooltip": "Detail and structure reconstruction."}),
                "skin_structure_strength": ("FLOAT", {"default": 2.0, "min": -1.0, "max": 2.0, "step": 0.01, "tooltip": "Skin and pore reconstruction; needs automatic_mask. -1 leaves it to the model."}),
                "automatic_mask": ("BOOLEAN", {"default": True, "tooltip": "Let the model find skin. Also the gate for skin_structure_strength."}),
                "dlss_model_preset": (list(DLSS_MODEL_PRESETS), {"default": "M", "tooltip": "L and M reconstruct the most texture. Set Default if the worker reports a different preset."}),
                "runtime_dir": ("STRING", {"default": "", "tooltip": "The folder holding nvngx.dll. Empty: DLSS5_RUNTIME_DIR, user/gpc_photoshop/dlss5_runtime.txt, then known places."}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "enhance"
    CATEGORY = CATEGORY

    def enhance(self, images, upscaling_mode=UPSCALING_LABELS[0], nr_style="Default", nr_intensity=1.0, local_tone_strength=1.0, local_structure_strength=1.5, skin_structure_strength=2.0, automatic_mask=True, dlss_model_preset="M", runtime_dir=""):
        from comfy.model_management import throw_exception_if_processing_interrupted
        from comfy.utils import ProgressBar

        options = DlssOptions.create(
            upscaling_mode=upscaling_mode,
            nr_style=nr_style,
            dlss_model_preset=dlss_model_preset,
            nr_intensity=nr_intensity,
            local_tone_strength=local_tone_strength,
            local_structure_strength=local_structure_strength,
            skin_structure_strength=skin_structure_strength,
            automatic_mask=bool(automatic_mask),
            motion_mode="none",
        )
        count, height, width = images.shape[:3]
        frames = [pad_even(tensor_to_rgba(image[:, :, :3])) for image in images]
        padded_h, padded_w = frames[0].shape[:2]
        # Raises with a usable mode when the result would pass DLSS's 7680 x 4320.
        resolve_output_size(padded_w, padded_h, options.upscaling_factor)
        out_w, out_h = output_crop(width, height, options.upscaling_factor)

        layout = find_runtime(runtime_dir.strip() or None)
        result = torch.empty((count, out_h, out_w, 3), dtype=torch.float32)
        progress = ProgressBar(count)
        with DlssSession(layout, options, input_width=padded_w, input_height=padded_h, frame_count=count) as session:
            still = np.zeros((session.render_height, session.render_width, 2), dtype=np.float16)
            for index, frame in enumerate(frames):
                throw_exception_if_processing_interrupted()
                rgba = fit_frame(frame, session.render_width, session.render_height)
                # Every image starts a fresh history: they aren't frames of one video.
                enhanced, _ = session.submit(index=index, rgba=rgba, motion=still, reset=True, pts=index)
                result[index] = rgba_to_tensor(enhanced[:out_h, :out_w], keep_alpha=False)
                progress.update(1)

        # ReShade writes its log as the worker exits; without this check a run that
        # only upscaled would look like success.
        session.feature_report()
        logger.info("DLSS5: neural rendering verified for %d image(s).", session.frames_submitted)
        return (result,)


NODE_CLASS_MAPPINGS = {"GPC_DLSS5_Enhance": GPCDLSS5Enhance}
NODE_DISPLAY_NAME_MAPPINGS = {"GPC_DLSS5_Enhance": "DLSS5 Enhance (GPC)"}
