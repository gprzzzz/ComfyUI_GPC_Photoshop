"""Workflow templates for the panel, served from ComfyUI.

Templates are API-format workflows ("Export (API)" in ComfyUI). They are read
from this pack's ``templates/`` folder and from ``ComfyUI/user/gpc_photoshop/``,
where your own go; a user template with the same name wins.
"""

import json
import logging
import os

import folder_paths

PACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

# Node packs our templates use, by class-name prefix, so a missing node can say what to install.
# A key ending in "_" matches a class-name prefix, any other key one class name.
KNOWN_PACKS = {
    "INPAINT_": ("comfyui-inpaint-nodes", "https://github.com/Acly/comfyui-inpaint-nodes"),
    "ETN_": ("comfyui-tooling-nodes", "https://github.com/Acly/comfyui-tooling-nodes"),
    "HintImageEnchance": ("comfyui_controlnet_aux", "https://github.com/Fannovel16/comfyui_controlnet_aux"),
    "IPAdapterModelLoader": ("ComfyUI_IPAdapter_plus", "https://github.com/cubiq/ComfyUI_IPAdapter_plus"),
    "IPAdapterAdvanced": ("ComfyUI_IPAdapter_plus", "https://github.com/cubiq/ComfyUI_IPAdapter_plus"),
}


def _pack_for(cls):
    for key, pack in KNOWN_PACKS.items():
        if cls == key or (key.endswith("_") and cls.startswith(key)):
            return pack
    return None


def template_dirs():
    return [PACK_DIR, os.path.join(folder_paths.get_user_directory(), "gpc_photoshop")]


def list_templates():
    """``{name: path}`` for every ``*.json`` template, later folders overriding earlier ones."""
    found = {}
    for folder in template_dirs():
        if os.path.isdir(folder):
            for file in sorted(os.listdir(folder)):
                if file.lower().endswith(".json"):
                    found[file[:-5]] = os.path.join(folder, file)
    return found


def load_template(name):
    path = list_templates().get(name)
    if path is None:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Loader inputs that name a model file, and the models folder each one reads.
MODEL_INPUTS = {
    ("CheckpointLoaderSimple", "ckpt_name"): "checkpoints",
    ("UNETLoader", "unet_name"): "diffusion_models",
    ("CLIPLoader", "clip_name"): "text_encoders",
    ("VAELoader", "vae_name"): "vae",
    ("ControlNetLoader", "control_net_name"): "controlnet",
    ("CLIPVisionLoader", "clip_name"): "clip_vision",
    ("IPAdapterModelLoader", "ipadapter_file"): "ipadapter",
    ("ModelPatchLoader", "name"): "model_patches",
    ("LoraLoader", "lora_name"): "loras",
}


def _file_name(name):
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def model_refs(template):
    """``[(node id, input, folder, file name)]`` for each model a template loads."""
    refs = []
    for node_id, node in template.items():
        if not isinstance(node, dict):
            continue
        for key, value in node.get("inputs", {}).items():
            folder = MODEL_INPUTS.get((node.get("class_type"), key))
            if folder and isinstance(value, str):
                refs.append((node_id, key, folder, value))
    return refs


def resolve_models(template, files):
    """Points each model at the installed file of the same name, in any subfolder.

    Templates name models by file name only; ComfyUI wants the exact path inside
    the models folder (``SDXL/model.safetensors``). ``files(folder)`` lists the
    installed ones. Returns the names that aren't installed: ``[(folder, name)]``.
    """
    missing = []
    for node_id, key, folder, name in model_refs(template):
        try:
            installed = files(folder)
        except Exception:  # an unknown folder (an older ComfyUI): leave it to ComfyUI
            continue
        if name in installed:
            continue
        same = [f for f in installed if _file_name(f).lower() == _file_name(name).lower()]
        if len(same) == 1:
            template[node_id]["inputs"][key] = same[0]
        else:
            missing.append((folder, name))
    return missing


def missing_nodes(template, available):
    """Class names a template uses that aren't installed, sorted."""
    return sorted({n["class_type"] for n in template.values() if isinstance(n, dict) and n.get("class_type") not in available})


def install_hint(missing):
    """What to do about ``missing`` nodes, as one message, or None when nothing is missing."""
    if not missing:
        return None
    packs, unknown = {}, []
    for cls in missing:
        pack = _pack_for(cls)
        if pack:
            packs[pack] = True
        else:
            unknown.append(cls)
    parts = [f"Missing nodes: {', '.join(missing)}."]
    for name, url in packs:
        parts.append(f"Install {name} ({url}) into ComfyUI/custom_nodes and restart ComfyUI.")
    if unknown:
        parts.append(f"Find the pack for {', '.join(unknown)} with ComfyUI-Manager, or check the template's notes.")
    return " ".join(parts)


def check_template(name, available, files=None):
    """``{"missing": [...], "models": [...], "message": str | None}`` for a template, or None
    when it doesn't exist. ``files(folder)`` lists installed models, to check those too."""
    template = load_template(name)
    if template is None:
        return None
    missing = missing_nodes(template, available)
    models = resolve_models(template, files) if files else []
    parts = [m for m in (install_hint(missing), models_hint(models)) if m]
    return {"missing": missing, "models": [name for _, name in models], "message": " ".join(parts) or None}


def models_hint(models):
    """What to download, as one message, or None."""
    if not models:
        return None
    return "Missing models: " + ", ".join(f"{_file_name(name)} (in models/{folder})" for folder, name in models) + ". Download them, then reload templates."


def _model_files(folder):
    import folder_paths

    return folder_paths.get_filename_list(folder)


def _installed_nodes():
    import nodes  # ComfyUI's registry, with every loaded custom node

    return nodes.NODE_CLASS_MAPPINGS


def warn_missing(available, files=None):
    """Logs each template whose nodes or models aren't all installed. Returns the messages."""
    messages = []
    for name in list_templates():
        try:
            result = check_template(name, available, files)
        except (OSError, ValueError) as e:
            messages.append(f"[GPC Photoshop] Template '{name}' can't be read: {e}")
            continue
        if result and result["message"]:
            messages.append(f"[GPC Photoshop] Template '{name}' won't run yet. {result['message']}")
    for m in messages:
        logging.warning(m)
    return messages


def register_routes():
    from aiohttp import web
    from server import PromptServer

    routes = PromptServer.instance.routes

    @routes.get("/gpc_ps/templates")
    async def _list(request):
        return web.json_response(sorted(list_templates()))

    @routes.get("/gpc_ps/templates/{name}")
    async def _get(request):
        template = load_template(request.match_info["name"])
        if template is None:
            return web.json_response({"error": "No such template"}, status=404)
        resolve_models(template, _model_files)
        return web.json_response(template)

    @routes.get("/gpc_ps/check/{name}")
    async def _check(request):
        result = check_template(request.match_info["name"], _installed_nodes(), _model_files)
        if result is None:
            return web.json_response({"error": "No such template"}, status=404)
        return web.json_response(result)

    # Runs once the server starts, after every custom node has loaded.
    async def _startup_check(app):
        try:
            warn_missing(_installed_nodes(), _model_files)
        except Exception as e:  # a failing startup hook would stop ComfyUI's server
            logging.warning(f"[GPC Photoshop] Couldn't check templates for missing nodes: {e}")

    try:
        PromptServer.instance.app.on_startup.append(_startup_check)
    except RuntimeError:  # app already frozen: the panel still checks per template
        pass
