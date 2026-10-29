import importlib.util
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("sweep", os.path.join(ROOT, "tools", "sweep.py"))
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)

SDXL = json.load(open(os.path.join(ROOT, "templates", "sdxl_img2img.json")))


def test_fill_sets_values_by_label():
    prompt = sweep.fill(SDXL, {"auto tile": "off", "strength": "0.45", "prompt": "a house", "steps": "20.0"}, "IMG", "", 7)
    assert prompt["75"]["inputs"]["value"] is False
    assert prompt["47"]["inputs"]["value"] == 0.45
    assert prompt["46"]["inputs"]["value"] == 20
    assert prompt["60"]["inputs"]["text"] == "a house"
    assert prompt["48"]["inputs"]["seed"] == 7
    assert prompt["4"]["inputs"] == {"image": "IMG", "mask": ""}
    assert all("_meta" not in n for n in prompt.values())
    with pytest.raises(KeyError, match="has: .*strength"):
        sweep.fill(SDXL, {"strenght": "1"}, "IMG")
    with pytest.raises(ValueError):
        sweep.fill(SDXL, {"auto tile": "maybe"}, "IMG")


def test_combinations():
    combos = sweep.combinations([("tiled", "off,on"), ("strength", "0.4, 0.6")])
    assert combos == [{"tiled": "off", "strength": "0.4"}, {"tiled": "off", "strength": "0.6"},
                      {"tiled": "on", "strength": "0.4"}, {"tiled": "on", "strength": "0.6"}]
    assert sweep.combinations([]) == [{}]


def png(color):
    b = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(b, "PNG")
    return b.getvalue()


class FakeComfy(BaseHTTPRequestHandler):
    queued = []

    def log_message(self, *a):
        pass

    def send(self, body, kind="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

    def do_POST(self):
        prompt = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["prompt"]
        if prompt["47"]["inputs"]["value"] > 0.9:
            return self.send({"error": {"message": "too strong"}}, code=400)
        FakeComfy.queued.append(prompt)
        self.send({"prompt_id": str(len(FakeComfy.queued))})

    def do_GET(self):
        if self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[1]
            return self.send({pid: {"status": {"completed": True, "status_str": "success"},
                                    "outputs": {"31": {"images": [{"filename": f"r{pid}.png", "subfolder": "gpc_photoshop", "type": "temp"}]},
                                                "99": {"images": [{"filename": "ignored.png"}]}}}})
        if self.path.startswith("/view?"):
            return self.send(png((200, 50, 50)), "image/png")
        self.send({}, code=404)


def test_sweep_end_to_end(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    image = tmp_path / "in.png"
    image.write_bytes(png((0, 0, 255)))
    out = tmp_path / "out"
    try:
        code = sweep.main(["--server", f"http://127.0.0.1:{server.server_port}", "--template", "sdxl_img2img", "--image", str(image),
                           "--prompt", "a house", "--sweep", "Auto tile=off,on", "--sweep", "Strength=0.5,1.0", "--out", str(out)])
    finally:
        server.shutdown()
    assert code == 1  # the two strength=1.0 runs fail on purpose
    summary = json.loads((out / "summary.json").read_text())
    assert [("error" in r) for r in summary["runs"]] == [False, True, False, True]
    assert "too strong" in summary["runs"][1]["error"]
    assert [q["75"]["inputs"]["value"] for q in FakeComfy.queued] == [False, True]
    assert all(q["60"]["inputs"]["text"] == "a house" for q in FakeComfy.queued)
    assert len(summary["runs"][0]["files"]) == 1  # only the PS Output node's image
    sheet = Image.open(out / "sheet.png")
    assert sheet.width == 4 * 512 and sheet.height > 512
