"""GPC Photoshop - ComfyUI nodes and template server for the GPC Photoshop panel."""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .nodes.templates import register_routes

try:
    register_routes()
except ImportError:  # outside a running ComfyUI (tests)
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
