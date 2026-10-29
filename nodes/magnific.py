"""Nano Banana through Magnific's API, so a template can edit the canvas with it.

The request goes out from ComfyUI, not Photoshop, so it works with Photoshop
blocked from the internet. Each result costs Magnific credits; the API key comes
from ``MAGNIFIC_API_KEY`` or ``ComfyUI/user/gpc_photoshop/magnific_api_key.txt``.
"""

import base64
import io
import json
import logging
import os
import time
import urllib.error
import urllib.request

import numpy as np
import torch
from PIL import Image

from . import CATEGORY
from .sizing import MEGAPIXEL

API = "https://api.magnific.com"
KEY_FILE = "magnific_api_key.txt"

RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
WIDE_RATIOS = RATIOS + ["1:4", "4:1", "1:8", "8:1"]

# Images go in as base64 for every model (Pro's docs only list URLs, but it takes
# base64 too). path: create endpoint (status is path/<task id>); any_ratio: "auto"
# keeps ratios outside the list; flat_price: 1K costs the same as 2K, so "auto"
# always takes 2K. (Credits per result, 2026-10-29: 2.1 50 / 65 / 145 at 1K / 2K /
# 4K; Pro and Pro Flash 75 / 75 / 150.) The original Nano Banana (2.5) is left out:
# it has no resolution setting.
MODELS = {
    "Nano Banana 2.1": {"path": "/v1/ai/text-to-image/nano-banana-2-1", "ratios": WIDE_RATIOS, "thinking": True, "any_ratio": True},
    "Nano Banana Pro": {"path": "/v1/ai/text-to-image/nano-banana-pro", "ratios": RATIOS, "flat_price": True},
    "Nano Banana Pro Flash": {"path": "/v1/ai/text-to-image/nano-banana-pro-flash", "ratios": RATIOS, "flat_price": True},
}
RESOLUTIONS = ["auto", "1K", "2K", "4K"]
THINKING = ["default", "minimal", "medium", "high"]
REFERENCES = 3
POLL_SECONDS = 2.0
# Starting a batch's requests back to back once got "Error consuming credits" for
# the last one with credits to spare (2026-10-29); nothing was made or charged.
# So requests are spaced a little, and a refused one is tried again.
START_GAP_SECONDS = 1.0
RETRY_SECONDS = (3.0, 8.0)
TIMEOUT_SECONDS = 1800


def nearest_ratio(width, height, ratios):
    """The listed ratio ("w:h") closest to ``width / height``, compared on a log scale."""
    import math

    target = math.log(width / height)
    return min(ratios, key=lambda r: abs(math.log(_ratio(r)) - target))


def _ratio(text):
    w, h = text.split(":")
    return int(w) / int(h)


def pick_resolution(width, height, setting, model):
    """``setting``, or for "auto": 2K where it costs the same as 1K; otherwise 1K when
    the crop fits in a 1K result (about 1 MP), else 2K, so a bigger selection isn't
    upscaled. 4K is only used when asked for.
    """
    if setting != "auto":
        return setting
    if MODELS[model].get("flat_price"):
        return "2K"
    return "1K" if width * height <= MEGAPIXEL * 1.05 else "2K"


def api_key():
    key = os.environ.get("MAGNIFIC_API_KEY", "").strip()
    if key:
        return key
    try:
        import folder_paths

        with open(os.path.join(folder_paths.get_user_directory(), "gpc_photoshop", KEY_FILE), encoding="utf-8") as f:
            key = f.read().strip()
    except (ImportError, OSError):
        key = ""
    if not key:
        raise ValueError(f"No Magnific API key: set MAGNIFIC_API_KEY, or put the key in ComfyUI/user/gpc_photoshop/{KEY_FILE}, then run again.")
    return key


class MagnificError(RuntimeError):
    """An error reply. ``retryable``: Magnific's side, worth trying again."""

    def __init__(self, text, code=None):
        super().__init__(text)
        self.retryable = code is not None and (code >= 500 or code == 429 or "consuming credits" in text.lower())


def _request(method, url, key=None, body=None, headers=None, data=None, timeout=60, raw=False):
    """JSON from the API, or the response bytes with ``raw``."""
    headers = dict(headers or {})
    if key:
        headers["x-magnific-api-key"] = key
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            reply = res.read()
    except urllib.error.HTTPError as e:
        raise MagnificError(f"Magnific: {_error_text(e)}", e.code) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Magnific can't be reached: {e.reason}") from None
    return reply if raw else json.loads(reply)


def _error_text(error):
    try:
        info = json.loads(error.read())
    except (ValueError, OSError):
        return f"HTTP {error.code}"
    text = (info.get("message") or info.get("detail") or f"HTTP {error.code}").strip()
    problems = info.get("invalid_params") or (info.get("problem") or {}).get("invalid_params") or []
    if problems:
        text += " (" + "; ".join(f"{p.get('name')}: {p.get('reason')}" for p in problems) + ")"
    if error.code == 401:
        text += ". Check the API key."
    return text


def start_task(path, key, body):
    """Starts one generation; returns its task id. Retries what Magnific refused on its side."""
    for wait in RETRY_SECONDS + (None,):
        try:
            return _request("POST", API + path, key, body)["data"]["task_id"]
        except MagnificError as e:
            if wait is None or not e.retryable:
                raise
            logging.warning(f"[GPC Photoshop] {e}; trying again in {wait:.0f} s")
            time.sleep(wait)


def png_bytes(image):
    """``[H, W, C]`` float tensor -> PNG bytes."""
    array = (image[:, :, :3].clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
    out = io.BytesIO()
    Image.fromarray(array).save(out, format="PNG", compress_level=1)
    return out.getvalue()


def request_body(model, prompt, images, width, height, resolution, thinking):
    """The JSON for one generation: ``images`` (canvas first) as base64 strings."""
    spec = MODELS[model]
    body = {"prompt": prompt, "reference_images": [{"image": image, "mime_type": "image/png"} for image in images]}
    # The panel grows the crop to a listed ratio; when the document has no room
    # for that, models that follow the image's own ratio get "auto".
    ratio = nearest_ratio(width, height, spec["ratios"])
    off = abs(_ratio(ratio) / (width / height) - 1) > 0.01
    body["aspect_ratio"] = "auto" if off and spec.get("any_ratio") else ratio
    body["resolution"] = pick_resolution(width, height, resolution, model)
    if spec.get("thinking") and thinking != "default":
        body["thinking_level"] = thinking
    return body


def fit_result(image, canvas):
    """The result as the whole crop, at the result's scale, so it places 1:1 over the crop.

    Nano Banana scales its input to cover its own frame and trims the overflow
    (1200x800 at 1K 3:2 -> 1272x848, 4 px trimmed off each side of 1264x848).
    Stretching the result back made it narrower than the crop; instead it goes
    back where it came from, and the trimmed strips are filled from the canvas.
    """
    image = image.convert("RGB")
    scale = max(image.width / canvas.width, image.height / canvas.height)
    full = (round(canvas.width * scale), round(canvas.height * scale))
    if full == image.size:
        return image
    out = canvas.resize(full, Image.LANCZOS)
    out.paste(image, ((full[0] - image.width) // 2, (full[1] - image.height) // 2))
    return out


def _server():
    try:
        from server import PromptServer
    except ImportError:  # outside a running ComfyUI (tests)
        return None
    return PromptServer.instance


def notify(text):
    """A note for the panel that queued the run, shown when it ends."""
    logging.warning(f"[GPC Photoshop] {text}")
    server = _server()
    if server:
        server.send_sync("gpc_ps.notice", {"prompt_id": server.last_prompt_id, "text": text}, server.client_id)


def announce(image, index, total):
    """Sends one finished result to the panel that queued the run, before the rest
    are back (Magnific makes them one by one, often minutes apart)."""
    server = _server()
    if not server:
        return
    import folder_paths

    from .markers import OUTPUT_SUBFOLDER, _write_pngs

    folder = os.path.join(folder_paths.get_temp_directory(), OUTPUT_SUBFOLDER)
    os.makedirs(folder, exist_ok=True)
    pixels = torch.from_numpy(np.asarray(image, dtype=np.float32) / 255.0)
    ref = _write_pngs(folder, [pixels])[0]
    server.send_sync("gpc_ps.result", {"prompt_id": server.last_prompt_id, "index": index, "total": total, "image": ref}, server.client_id)


class GPCMagnificNanoBanana:
    """Edits the canvas with Nano Banana on Magnific. Costs credits for every result.

    The canvas goes in as the first image, filled reference slots after it, so
    the prompt can call them "image 2", "image 3". Results come back at the
    model's size (1K / 2K), covering exactly the canvas, in the order they were
    finished; each is also sent to the panel as soon as it's back.
    """

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for n in range(1, REFERENCES + 1):
            optional[f"reference_{n}"] = ("IMAGE",)
            optional[f"use_reference_{n}"] = ("BOOLEAN", {"default": True, "forceInput": True})
        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "model": (list(MODELS), {"default": "Nano Banana 2.1"}),
                "resolution": (RESOLUTIONS, {"default": "auto", "tooltip": "auto: 2K where it costs the same as 1K (Pro, Pro Flash); else 1K for a crop up to about 1 MP, and 2K above."}),
                "batch": ("INT", {"default": 1, "min": 1, "max": 4, "tooltip": "Results per run; each one costs credits."}),
                "thinking": (THINKING, {"default": "default", "tooltip": "Nano Banana 2.1 only: more thinking for complex prompts, same price."}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, image, prompt, model, resolution, batch, thinking, **refs):
        if len(prompt.strip()) < 2:
            raise ValueError("Write a prompt first: Nano Banana edits by instruction.")
        import comfy.model_management
        import comfy.utils

        spec = MODELS[model]
        key = api_key()
        height, width = image.shape[1:3]
        pngs = [png_bytes(image[0])]
        for n in range(1, REFERENCES + 1):
            ref = refs.get(f"reference_{n}")
            if ref is not None and refs.get(f"use_reference_{n}", True):
                pngs.append(png_bytes(ref[0]))
        images = [base64.b64encode(p).decode() for p in pngs]
        body = request_body(model, prompt, images, width, height, resolution, thinking)

        # Every request makes one image: queue them all, then wait for all. When a
        # later one is refused (e.g. out of credits), the ones already started are
        # paid for, so they're still waited for.
        tasks = []
        for n in range(batch):
            if n:
                time.sleep(START_GAP_SECONDS)
            try:
                tasks.append(start_task(spec["path"], key, body))
            except RuntimeError as e:
                if not tasks:
                    raise
                notify(f"Only {len(tasks)} of {batch} results were started. {e}")
                break
        progress = comfy.utils.ProgressBar(len(tasks))
        source = Image.open(io.BytesIO(pngs[0]))
        results = {}
        done = []
        start = time.monotonic()
        while len(results) < len(tasks):
            comfy.model_management.throw_exception_if_processing_interrupted()
            if time.monotonic() - start > TIMEOUT_SECONDS:
                raise RuntimeError("Magnific took more than 30 minutes; the results may still appear in your Magnific history.")
            time.sleep(POLL_SECONDS)
            for task in tasks:
                if task in results:
                    continue
                data = _request("GET", f"{API}{spec['path']}/{task}", key)["data"]
                if data["status"] == "FAILED":
                    raise RuntimeError("Magnific: the generation failed (often the safety filter, or a prompt it can't do).")
                if data["status"] == "COMPLETED" and data.get("generated"):
                    results[task] = fit_result(Image.open(io.BytesIO(_request("GET", data["generated"][0], timeout=120, raw=True))), source)
                    done.append(task)
                    logging.info(f"[GPC Photoshop] {model} {body['resolution']}: result {len(done)} of {len(tasks)} after {time.monotonic() - start:.0f} s")
                    announce(results[task], len(done) - 1, len(tasks))
                    progress.update(1)

        out = [results[t] for t in done]
        size = out[0].size
        tensors = [torch.from_numpy(np.asarray(im.resize(size, Image.LANCZOS) if im.size != size else im, dtype=np.float32) / 255.0) for im in out]
        return (torch.stack(tensors),)


NODE_CLASS_MAPPINGS = {"GPC_Magnific_NanoBanana": GPCMagnificNanoBanana}
NODE_DISPLAY_NAME_MAPPINGS = {"GPC_Magnific_NanoBanana": "Magnific Nano Banana (GPC)"}
