"""Node registry. Each module exports NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS."""

CATEGORY = "GPC Photoshop"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

from . import dlss5_enhance, magnific, markers, tiled_diffusion, tiles  # noqa: E402

for _module in (markers, tiles, tiled_diffusion, magnific, dlss5_enhance):
    NODE_CLASS_MAPPINGS.update(_module.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_module.NODE_DISPLAY_NAME_MAPPINGS)
