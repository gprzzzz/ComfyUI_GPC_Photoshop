"""Run a template through ComfyUI over a grid of settings and build a comparison sheet.

No Photoshop needed: the image goes in as the PS Canvas, as the panel would send
a crop. Run it with ComfyUI's own Python (it needs Pillow, which ComfyUI has):

    python tools/sweep.py --template sdxl_img2img --image house.png \\
        --prompt "a cinematic photograph of a house" \\
        --sweep "Auto tile=off,on" --sweep "Tile ControlNet=off,on" --set "Strength=0.6"

Settings are the panel's labels (case doesn't matter). Results, timings and
sheet.png go to --out (default: sweep_out/<template>_<time>).
"""

import argparse
import base64
import io
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(os.path.dirname(HERE), "templates")

VALUE_NODES = {"GPC_PS_Int": "value", "GPC_PS_Float": "value", "GPC_PS_Toggle": "value", "GPC_PS_Text": "text"}
REFERENCE_NODES = ("GPC_PS_ReferenceImage", "GPC_PS_ReferenceLatent")
TRUE, FALSE = {"on", "true", "yes", "1"}, {"off", "false", "no", "0"}


def controls(template):
    """``{label (lower case): (node id, input name, class)}`` for the template's panel controls."""
    out = {}
    for node_id, node in template.items():
        key = VALUE_NODES.get(node.get("class_type"))
        if key:
            label = str(node["inputs"].get("label", "")).strip().lower()
            out[label] = (node_id, key, node["class_type"])
    return out


def parse_value(raw, cls):
    if cls == "GPC_PS_Toggle":
        low = raw.strip().lower()
        if low in TRUE | FALSE:
            return low in TRUE
        raise ValueError(f"'{raw}' isn't on/off")
    if cls == "GPC_PS_Int":
        return int(round(float(raw)))
    if cls == "GPC_PS_Float":
        return float(raw)
    return raw


def parse_assignment(text):
    """``"Label=value"`` -> ``(label, value)``; ``"Label=a,b"`` -> ``(label, [a, b])`` for sweeps."""
    if "=" not in text:
        raise ValueError(f"'{text}' should look like Label=value")
    label, value = text.split("=", 1)
    return label.strip().lower(), value


def fill(template, values, image_b64, mask_b64="", seed=0, references=None):
    """A queue-ready copy of ``template``: values by label, the canvas, seed and references."""
    prompt = json.loads(json.dumps(template))
    known = controls(prompt)
    for label, raw in values.items():
        if label not in known:
            raise KeyError(f"No setting '{label}'. This template has: {', '.join(sorted(known))}")
        node_id, key, cls = known[label]
        prompt[node_id]["inputs"][key] = parse_value(raw, cls) if isinstance(raw, str) else raw
    for node in prompt.values():
        node.pop("_meta", None)
        cls = node.get("class_type")
        if cls == "GPC_PS_Canvas":
            node["inputs"].update(image=image_b64, mask=mask_b64)
        elif cls == "GPC_PS_Seed":
            node["inputs"]["seed"] = seed
        elif cls in REFERENCE_NODES:
            node["inputs"]["image"] = (references or {}).get(int(node["inputs"].get("slot", 1)), "")
    return prompt


def combinations(sweeps):
    """Every combination of the swept values, as a list of ``{label: value}``."""
    labels = [label for label, _ in sweeps]
    choices = [[v.strip() for v in values.split(",")] for _, values in sweeps]
    return [dict(zip(labels, combo)) for combo in itertools.product(*choices)] or [{}]


# --- talking to ComfyUI (plain urllib: no browser headers, so no origin check) ---

def request(server, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} from ComfyUI: {e.read().decode(errors='replace')[:2000]}") from None


def run(server, prompt, timeout):
    """Queues ``prompt``; returns ``(list of PNG bytes, seconds)``."""
    client = "gpc-sweep-" + uuid.uuid4().hex[:8]
    started = time.time()
    prompt_id = json.loads(request(server, "/prompt", {"prompt": prompt, "client_id": client}))["prompt_id"]
    while True:
        if time.time() - started > timeout:
            raise TimeoutError(f"no result after {timeout}s")
        entry = json.loads(request(server, "/history/" + prompt_id)).get(prompt_id)
        status = (entry or {}).get("status", {})
        if status.get("status_str") == "error":
            messages = [m[1] for m in status.get("messages", []) if m[0] == "execution_error"]
            raise RuntimeError(messages[0].get("exception_message", "execution failed") if messages else "execution failed")
        if entry and status.get("completed", True):
            break
        time.sleep(1)
    seconds = time.time() - started
    images = []
    for node_id, out in entry["outputs"].items():
        if prompt.get(node_id, {}).get("class_type") != "GPC_PS_Output":
            continue
        for img in out.get("images", []):
            query = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "temp")})
            images.append(request(server, "/view?" + query))
    return images, seconds


# --- the comparison sheet ---

def sheet(cells, path, size=512):
    """``cells``: list of ``(PIL image, caption lines)``. Saves a labelled grid."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default()
    line, pad = 14, 6
    caption_h = pad * 2 + line * max(len(c[1]) for c in cells)
    cols = min(4, len(cells))
    rows = (len(cells) + cols - 1) // cols
    out = Image.new("RGB", (cols * size, rows * (size + caption_h)), (40, 40, 40))
    draw = ImageDraw.Draw(out)
    for i, (img, caption) in enumerate(cells):
        x, y = (i % cols) * size, (i // cols) * (size + caption_h)
        thumb = img.convert("RGBA")
        thumb.thumbnail((size, size))
        tile = Image.new("RGBA", (size, size), (40, 40, 40, 255))
        tile.alpha_composite(thumb, ((size - thumb.width) // 2, (size - thumb.height) // 2))
        out.paste(tile.convert("RGB"), (x, y))
        for j, text in enumerate(caption):
            draw.text((x + pad, y + size + pad + j * line), text, fill=(230, 230, 230), font=font)
    out.save(path)


def load_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://127.0.0.1:8188")
    p.add_argument("--template", required=True, help="name in templates/ (or a path to an API-format .json)")
    p.add_argument("--image", required=True, help="the image sent as the canvas")
    p.add_argument("--mask", default="", help="optional mask image (white = change); default: everything")
    p.add_argument("--reference", action="append", default=[], help="SLOT=path, e.g. 1=grasses.png")
    p.add_argument("--prompt", default=None, help="the Prompt text")
    p.add_argument("--set", action="append", default=[], help="Label=value, fixed for every run")
    p.add_argument("--sweep", action="append", default=[], help="Label=a,b,c: one run per value (combined across sweeps)")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--timeout", type=int, default=1800, help="seconds per run")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    from PIL import Image

    path = args.template if args.template.endswith(".json") else os.path.join(TEMPLATES, args.template + ".json")
    name = os.path.splitext(os.path.basename(path))[0]
    template = None
    if not args.template.endswith(".json"):
        # As the panel gets it: your own copy if there is one, models found in any subfolder.
        try:
            template = json.loads(request(args.server, "/gpc_ps/templates/" + urllib.parse.quote(name)))
        except (RuntimeError, OSError, ValueError):
            template = None
    if template is None:
        with open(path, encoding="utf-8") as f:
            template = json.load(f)
    out_dir = args.out or os.path.join("sweep_out", f"{name}_{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)

    fixed = dict(parse_assignment(s) for s in args.set)
    if args.prompt is not None:
        fixed["prompt"] = args.prompt
    sweeps = [parse_assignment(s) for s in args.sweep]
    references = {int(k): load_b64(v) for k, v in (r.split("=", 1) for r in args.reference)}
    image_b64, mask_b64 = load_b64(args.image), load_b64(args.mask) if args.mask else ""

    cells = [(Image.open(args.image), ["input", os.path.basename(args.image)])]
    summary = []
    runs = combinations(sweeps)
    for i, combo in enumerate(runs, 1):
        values = {**fixed, **combo}
        label = ", ".join(f"{k}={v}" for k, v in combo.items()) or "run"
        print(f"[{i}/{len(runs)}] {label} ...", flush=True)
        try:
            images, seconds = run(args.server, fill(template, values, image_b64, mask_b64, args.seed, references), args.timeout)
        except Exception as e:  # keep sweeping; the sheet shows what failed
            print(f"    failed: {e}", flush=True)
            summary.append({"settings": combo, "error": str(e)})
            cells.append((Image.new("RGB", (64, 64), (120, 30, 30)), [label, f"FAILED: {str(e)[:60]}"]))
            continue
        files = []
        for j, png in enumerate(images, 1):
            file = os.path.join(out_dir, f"{i:02d}_{j}.png")
            with open(file, "wb") as f:
                f.write(png)
            files.append(file)
            cells.append((Image.open(io.BytesIO(png)), [label, f"{seconds:.0f}s" + (f" · result {j}" if len(images) > 1 else "")]))
        print(f"    {seconds:.0f}s, {len(images)} image(s)", flush=True)
        summary.append({"settings": combo, "seconds": round(seconds, 1), "files": files})

    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump({"template": name, "seed": args.seed, "fixed": fixed, "runs": summary}, f, indent=2)
    sheet(cells, os.path.join(out_dir, "sheet.png"))
    print("Sheet:", os.path.join(out_dir, "sheet.png"))
    return 0 if all("error" not in r for r in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
