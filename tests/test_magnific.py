import base64
import io
import json
import os
import sys
import types

import pytest

torch = pytest.importorskip("torch")
from PIL import Image  # noqa: E402

TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


def magnific(pkg):
    return sys.modules[pkg.__name__ + ".nodes.magnific"]


def png(size, color=(0, 128, 255)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def test_ratio_and_resolution(pkg):
    m = magnific(pkg)
    assert m.nearest_ratio(1000, 1000, m.RATIOS) == "1:1"
    assert m.nearest_ratio(1920, 1080, m.RATIOS) == "16:9"
    assert m.nearest_ratio(400, 1600, m.RATIOS) == "9:16"
    assert m.nearest_ratio(400, 1600, m.WIDE_RATIOS) == "1:4"
    assert m.pick_resolution(1024, 1024, "auto", "Nano Banana 2.1") == "1K"
    assert m.pick_resolution(1400, 1000, "auto", "Nano Banana 2.1") == "2K"
    assert m.pick_resolution(3000, 3000, "auto", "Nano Banana 2.1") == "2K"
    assert m.pick_resolution(500, 500, "auto", "Nano Banana Pro Flash") == "2K", "1K costs the same there"
    assert m.pick_resolution(500, 500, "4K", "Nano Banana 2.1") == "4K"


def test_request_bodies_follow_each_model(pkg):
    m = magnific(pkg)
    body = m.request_body("Nano Banana 2.1", "make it red", ["AAA", "BBB"], 1600, 900, "auto", "high")
    assert body == {
        "prompt": "make it red",
        "reference_images": [{"image": "AAA", "mime_type": "image/png"}, {"image": "BBB", "mime_type": "image/png"}],
        "aspect_ratio": "16:9",
        "resolution": "2K",
        "thinking_level": "high",
    }
    # Off the list: 2.1 follows the image itself, Pro gets the nearest ratio.
    assert m.request_body("Nano Banana 2.1", "x x", ["A"], 1000, 1300, "auto", "default")["aspect_ratio"] == "auto"
    pro = m.request_body("Nano Banana Pro", "x x", ["A"], 1000, 1300, "auto", "high")
    assert pro["aspect_ratio"] == "3:4" and "thinking_level" not in pro and pro["resolution"] == "2K"


def test_key_from_the_user_folder(pkg, monkeypatch, tmp_path):
    m = magnific(pkg)
    monkeypatch.delenv("MAGNIFIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="magnific_api_key.txt"):
        m.api_key()
    folder = tmp_path / "user" / "gpc_photoshop"
    folder.mkdir(parents=True)
    (folder / m.KEY_FILE).write_text(" secret\n")
    assert m.api_key() == "secret"
    monkeypatch.setenv("MAGNIFIC_API_KEY", "from-env")
    assert m.api_key() == "from-env"


def test_generate_queues_a_task_per_result_and_shapes_them_like_the_canvas(pkg, monkeypatch, tmp_path):
    m = magnific(pkg)
    monkeypatch.setenv("MAGNIFIC_API_KEY", "k")
    monkeypatch.setattr(m, "POLL_SECONDS", 0)
    management = types.ModuleType("comfy.model_management")
    management.throw_exception_if_processing_interrupted = lambda: None
    monkeypatch.setitem(sys.modules, "comfy.model_management", management)
    sys.modules["comfy"].model_management = management
    sys.modules["comfy.utils"].ProgressBar = lambda total: types.SimpleNamespace(update=lambda n: None)

    sent = []
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(last_prompt_id="p1", client_id="c1", send_sync=lambda event, data, sid: sent.append((event, data, sid))))
    monkeypatch.setitem(sys.modules, "server", server)
    calls = []
    polls = {}

    def fake(method, url, key=None, body=None, headers=None, data=None, timeout=60, raw=False):
        calls.append((method, url, body))
        if method == "POST":
            return {"data": {"task_id": f"t{len([c for c in calls if c[0] == 'POST'])}", "status": "CREATED", "generated": []}}
        if url.startswith("https://img/"):
            return png((2048, 1144))  # covers the 1600x900 canvas scaled to 2048x1152, 4 px trimmed top and bottom
        task = url.rsplit("/", 1)[1]
        polls[task] = polls.get(task, 0) + 1
        done = polls[task] > (3 if task == "t1" else 1)  # the second task finishes first
        return {"data": {"task_id": task, "status": "COMPLETED" if done else "IN_PROGRESS", "generated": [f"https://img/{task}.png"] if done else []}}

    monkeypatch.setattr(m, "_request", fake)
    canvas = torch.rand((1, 900, 1600, 3))
    ref = torch.rand((1, 64, 64, 3))
    (out,) = m.GPCMagnificNanoBanana().generate(canvas, "make the doors white", "Nano Banana 2.1", "auto", 2, "default", reference_1=ref, use_reference_1=True, reference_2=ref, use_reference_2=False)

    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 2 and all(c[1].endswith("/nano-banana-2-1") for c in posts)
    refs = posts[0][2]["reference_images"]
    assert len(refs) == 2, "the canvas plus the one reference that's in use"
    assert Image.open(io.BytesIO(base64.b64decode(refs[0]["image"]))).size == (1600, 900)
    assert out.shape == (2, 1152, 2048, 3), "the trimmed rows come back, so the result covers the canvas"
    assert [(e, d["prompt_id"], d["index"], d["total"], sid) for e, d, sid in sent] == [("gpc_ps.result", "p1", 0, 2, "c1"), ("gpc_ps.result", "p1", 1, 2, "c1")]
    assert all(os.path.isfile(os.path.join(str(tmp_path), "temp", d["image"]["subfolder"], d["image"]["filename"])) for _, d, _ in sent)
    assert torch.allclose(out[0, 4, 0], torch.tensor([0.0, 128 / 255, 1.0]), atol=1e-3), "the result sits in the middle"


def test_fit_result_puts_a_trimmed_result_back_over_the_whole_canvas(pkg):
    m = magnific(pkg)
    canvas = Image.new("RGB", (1200, 800), (255, 0, 0))
    result = Image.new("RGB", (1264, 848), (0, 0, 255))
    out = m.fit_result(result, canvas)
    assert out.size == (1272, 848)
    assert out.getpixel((2, 400)) == (255, 0, 0), "the trimmed strip comes from the canvas"
    assert out.getpixel((4, 400)) == (0, 0, 255) and out.getpixel((1267, 400)) == (0, 0, 255)
    assert m.fit_result(Image.new("RGB", (1500, 1000)), canvas).size == (1500, 1000), "an untrimmed result is kept as is"


def test_generate_needs_a_prompt(pkg):
    with pytest.raises(ValueError, match="prompt"):
        magnific(pkg).GPCMagnificNanoBanana().generate(torch.rand((1, 8, 8, 3)), " ", "Nano Banana 2.1", "auto", 1, "default")


def test_templates_use_their_model_and_the_magnific_tab(pkg):
    m = magnific(pkg)
    seen = set()
    for name in ("nano_banana_2_1", "nano_banana_pro", "nano_banana_pro_flash"):
        with open(os.path.join(TEMPLATES, name + ".json"), encoding="utf-8") as f:
            t = json.load(f)
        node = next(n for n in t.values() if n["class_type"] == "GPC_Magnific_NanoBanana")
        assert node["inputs"]["model"] in m.MODELS
        seen.add(node["inputs"]["model"])
        assert next(n for n in t.values() if n["class_type"] == "GPC_PS_Output")["inputs"]["mode"] == "magnific"
    assert seen == set(m.MODELS)


def _live_stubs(m, monkeypatch, refuse_after, refusals=99):
    """Stand-ins for ComfyUI and Magnific: after `refuse_after` tasks, the next
    `refusals` POSTs are refused (then they go through again)."""
    monkeypatch.setenv("MAGNIFIC_API_KEY", "k")
    for name in ("POLL_SECONDS", "START_GAP_SECONDS"):
        monkeypatch.setattr(m, name, 0)
    monkeypatch.setattr(m, "RETRY_SECONDS", (0, 0))
    management = types.ModuleType("comfy.model_management")
    management.throw_exception_if_processing_interrupted = lambda: None
    monkeypatch.setitem(sys.modules, "comfy.model_management", management)
    sys.modules["comfy"].model_management = management
    sys.modules["comfy.utils"].ProgressBar = lambda total: types.SimpleNamespace(update=lambda n: None)
    sent = []
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(last_prompt_id="p1", client_id="c1", send_sync=lambda event, data, sid: sent.append((event, data))))
    monkeypatch.setitem(sys.modules, "server", server)
    posts = []
    refused = []

    def fake(method, url, key=None, body=None, headers=None, data=None, timeout=60, raw=False):
        if method == "POST":
            if len(posts) >= refuse_after and len(refused) < refusals:
                refused.append(url)
                raise m.MagnificError("Magnific: Error consuming credits", 400)
            posts.append(url)
            return {"data": {"task_id": f"t{len(posts)}"}}
        if url.startswith("https://img/"):
            return png((64, 64))
        return {"data": {"status": "COMPLETED", "generated": ["https://img/x.png"]}}

    monkeypatch.setattr(m, "_request", fake)
    return sent


def test_a_batch_cut_short_by_credits_keeps_the_results_already_paid_for(pkg, monkeypatch, tmp_path):
    m = magnific(pkg)
    sent = _live_stubs(m, monkeypatch, refuse_after=3)
    (out,) = m.GPCMagnificNanoBanana().generate(torch.rand((1, 64, 64, 3)), "make it red", "Nano Banana 2.1", "auto", 4, "default")
    assert out.shape[0] == 3
    notices = [d["text"] for e, d in sent if e == "gpc_ps.notice"]
    assert notices == ["Only 3 of 4 results were started. Magnific: Error consuming credits"]


def test_a_refused_start_is_tried_again(pkg, monkeypatch, tmp_path):
    m = magnific(pkg)
    sent = _live_stubs(m, monkeypatch, refuse_after=3, refusals=2)
    (out,) = m.GPCMagnificNanoBanana().generate(torch.rand((1, 64, 64, 3)), "make it red", "Nano Banana 2.1", "auto", 4, "default")
    assert out.shape[0] == 4 and not [e for e, d in sent if e == "gpc_ps.notice"]


def test_errors_on_our_side_are_not_retried(pkg):
    m = magnific(pkg)
    assert not m.MagnificError("Magnific: prompt: too short", 400).retryable
    assert not m.MagnificError("Magnific: Invalid API key. Check the API key.", 401).retryable
    assert m.MagnificError("Magnific: HTTP 503", 503).retryable


def test_a_first_start_refused_even_after_retries_is_an_error(pkg, monkeypatch, tmp_path):
    m = magnific(pkg)
    _live_stubs(m, monkeypatch, refuse_after=0)
    with pytest.raises(RuntimeError, match="consuming credits"):
        m.GPCMagnificNanoBanana().generate(torch.rand((1, 64, 64, 3)), "make it red", "Nano Banana 2.1", "auto", 2, "default")
