"""Make the package importable outside a running ComfyUI by stubbing ComfyUI's modules."""

import importlib.util
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_paths = types.ModuleType("folder_paths")
_paths.base = None
_paths.get_temp_directory = lambda: os.path.join(_paths.base, "temp")
_paths.get_user_directory = lambda: os.path.join(_paths.base, "user")
sys.modules.setdefault("folder_paths", _paths)


def _common_upscale(samples, width, height, method, crop):
    import torch

    return torch.nn.functional.interpolate(samples, size=(height, width), mode="bilinear", align_corners=False)


_comfy = types.ModuleType("comfy")
_utils = types.ModuleType("comfy.utils")
_utils.common_upscale = _common_upscale
_comfy.utils = _utils
sys.modules.setdefault("comfy", _comfy)
sys.modules.setdefault("comfy.utils", _utils)


def _conditioning_set_values(conditioning, values={}, append=False):
    out = []
    for t in conditioning:
        n = [t[0], t[1].copy()]
        for k, val in values.items():
            if append and n[1].get(k) is not None:
                val = n[1][k] + val
            n[1][k] = val
        out.append(n)
    return out


_helpers = types.ModuleType("node_helpers")
_helpers.conditioning_set_values = _conditioning_set_values
sys.modules.setdefault("node_helpers", _helpers)

PACKAGE = "gpc_photoshop"


def _load_package():
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PACKAGE, os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT])
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = module
        spec.loader.exec_module(module)
    return sys.modules[PACKAGE]


@pytest.fixture
def pkg(tmp_path):
    sys.modules["folder_paths"].base = str(tmp_path)
    return _load_package()
