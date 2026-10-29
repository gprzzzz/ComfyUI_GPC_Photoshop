import base64
import io
import json
import os

import pytest

torch = pytest.importorskip("torch")
from PIL import Image  # noqa: E402


def png_b64(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def nodes(pkg):
    return pkg.NODE_CLASS_MAPPINGS


def test_canvas_decodes_image_and_mask(pkg):
    image = png_b64(Image.new("RGB", (40, 30), (255, 0, 0)))
    mask = Image.new("L", (40, 30), 0)
    mask.paste(255, (10, 10, 20, 20))
    pixels, m, w, h = nodes(pkg)["GPC_PS_Canvas"]().load(image, "data:image/png;base64," + png_b64(mask))
    assert pixels.shape == (1, 30, 40, 3) and (w, h) == (40, 30)
    assert pixels[0, 0, 0].tolist() == [1.0, 0.0, 0.0]
    assert m.shape == (1, 30, 40) and m[0, 15, 15] == 1 and m[0, 0, 0] == 0


def test_canvas_falls_back_to_test_inputs_and_full_mask(pkg):
    pixels, m, w, h = nodes(pkg)["GPC_PS_Canvas"]().load("", "", test_image=torch.rand(1, 8, 12, 3))
    assert (w, h) == (12, 8) and bool((m == 1).all())
    with pytest.raises(ValueError):
        nodes(pkg)["GPC_PS_Canvas"]().load("", "")


def test_reference_latent_appends_only_when_provided(pkg):
    class VAE:
        def encode(self, pixels):
            return torch.zeros(1, 16, pixels.shape[1] // 8, pixels.shape[2] // 8)

    cond = [[torch.zeros(1), {"reference_latents": [torch.ones(1)]}]]
    node = nodes(pkg)["GPC_PS_ReferenceLatent"]()
    (same,) = node.apply(cond, VAE(), 1, "Ref", "")
    assert same is cond
    (out,) = node.apply(cond, VAE(), 1, "Ref", png_b64(Image.new("RGB", (64, 32))))
    refs = out[0][1]["reference_latents"]
    assert len(refs) == 2 and refs[1].shape == (1, 16, 4, 8)
    assert len(cond[0][1]["reference_latents"]) == 1


def test_reference_image_reports_empty_slot(pkg):
    image, provided = nodes(pkg)["GPC_PS_ReferenceImage"]().load(1, "Ref", "")
    assert provided is False and image.shape == (1, 64, 64, 3)


def test_fit_resolution(pkg):
    image, mask, w, h = nodes(pkg)["GPC_PS_FitResolution"]().fit(torch.rand(1, 560, 544, 3), 0.6, 1.2, 16)
    assert image.shape == (1, h, w, 3) and mask.shape == (1, h, w)
    assert w % 16 == 0 and w > 544


def test_output_writes_rgba_pngs(pkg):
    images = torch.rand(2, 20, 30, 3)
    mask = torch.zeros(1, 10, 15)
    mask[:, :5] = 1
    result = nodes(pkg)["GPC_PS_Output"]().save(images, mask)
    files = result["ui"]["images"]
    assert len(files) == 2 and files[0]["type"] == "temp"
    path = os.path.join(pkg_temp(), files[0]["subfolder"], files[0]["filename"])
    img = Image.open(path)
    assert img.mode == "RGBA" and img.size == (30, 20)
    assert img.getpixel((0, 0))[3] == 255 and img.getpixel((0, 19))[3] == 0
    assert img.info.get("icc_profile")


def test_output_can_send_the_mask_on_its_own(pkg):
    images = torch.rand(2, 40, 60, 3)
    mask = torch.zeros(1, 20, 30)
    mask[:, :10] = 1
    ui = nodes(pkg)["GPC_PS_Output"]().save(images, mask, mask_as="layer mask")["ui"]
    folder = os.path.join(pkg_temp(), "gpc_photoshop")
    img = Image.open(os.path.join(folder, ui["images"][0]["filename"]))
    assert img.mode == "RGB" and img.size == (60, 40), "the whole result, no transparency"
    masks = [Image.open(os.path.join(folder, m["filename"])) for m in ui["gpc_masks"]]
    assert len(masks) == 2 and masks[1].mode == "L" and masks[1].size == (30, 20), "one per result, at the crop's size"
    assert masks[0].getpixel((0, 0)) == 255 and masks[0].getpixel((0, 19)) == 0


def pkg_temp():
    import folder_paths

    return folder_paths.get_temp_directory()


@pytest.mark.parametrize("name", ["flux2_klein_inpaint", "sdxl_img2img", "zimage_upscale"])
def test_templates_use_known_inputs(pkg, name):
    path = os.path.join(os.path.dirname(__file__), "..", "templates", name + ".json")
    template = json.load(open(path))
    for node_id, node in template.items():
        cls = nodes(pkg).get(node["class_type"])
        if cls is None:
            continue  # core / inpaint-nodes
        spec = cls.INPUT_TYPES()
        known = {**spec.get("required", {}), **spec.get("optional", {})}
        assert set(node["inputs"]) <= set(known), node_id
        assert set(spec["required"]) <= set(node["inputs"]), node_id
        for link in (v for v in node["inputs"].values() if isinstance(v, list)):
            assert link[0] in template, (node_id, link)


def test_templates_listing(pkg, tmp_path):
    from gpc_photoshop.nodes import templates

    user = tmp_path / "user" / "gpc_photoshop"
    user.mkdir(parents=True)
    (user / "mine.json").write_text("{}")
    found = templates.list_templates()
    assert "flux2_klein_inpaint" in found and "mine" in found
    assert templates.load_template("mine") == {}
    assert templates.load_template("../secrets") is None


def test_missing_nodes_name_the_pack_to_install(pkg):
    from gpc_photoshop.nodes import templates

    template = templates.load_template("flux2_klein_inpaint")
    core = {n["class_type"] for n in template.values()} - {"INPAINT_ExpandMask", "INPAINT_ShrinkMask", "INPAINT_ColorMatch"}

    assert templates.check_template("flux2_klein_inpaint", core | {"INPAINT_ExpandMask", "INPAINT_ShrinkMask", "INPAINT_ColorMatch"}) == {"missing": [], "models": [], "message": None}
    result = templates.check_template("flux2_klein_inpaint", core)
    assert result["missing"] == ["INPAINT_ColorMatch", "INPAINT_ExpandMask", "INPAINT_ShrinkMask"]
    assert "https://github.com/Acly/comfyui-inpaint-nodes" in result["message"]
    assert result["message"].count("Install ") == 1

    hint = templates.install_hint(["SomeOtherNode"])
    assert "SomeOtherNode" in hint and "ComfyUI-Manager" in hint
    assert templates.check_template("nope", core) is None


def test_startup_warning(pkg, caplog):
    from gpc_photoshop.nodes import templates

    messages = templates.warn_missing(set())
    assert any("flux2_klein_inpaint" in m and "comfyui-inpaint-nodes" in m for m in messages)
    assert any("comfyui-inpaint-nodes" in r.message for r in caplog.records)


def test_noise_mask_skipped_for_a_full_mask(pkg):
    node = nodes(pkg)["GPC_PS_NoiseMask"]()
    latent = {"samples": torch.zeros(1, 16, 8, 8), "noise_mask": torch.zeros(1, 1, 8, 8)}
    (full,) = node.apply(latent, torch.ones(1, 64, 64))
    assert "noise_mask" not in full and "noise_mask" in latent
    partial = torch.ones(1, 64, 64)
    partial[:, :2] = 0
    (out,) = node.apply(latent, partial)
    assert out["noise_mask"].shape == (1, 1, 64, 64)


def test_full_selection_switch_only_asks_for_the_branch_it_uses(pkg):
    node = nodes(pkg)["GPC_PS_FullSelectionSwitch"]()
    full = torch.ones(1, 8, 8)
    partial = full.clone()
    partial[:, 0] = 0
    assert node.check_lazy_status(full) == ["full"]
    assert node.check_lazy_status(partial) == ["partial"]
    a, b = torch.zeros(1, 8, 8, 3), torch.ones(1, 8, 8, 3)
    assert node.pick(full, partial=a, full=b)[0] is b
    assert node.pick(partial, partial=a, full=b)[0] is a


def test_join_text_skips_empty_parts(pkg):
    join = nodes(pkg)["GPC_PS_JoinText"]().join
    assert join("a house", "best quality", ", ") == ("a house, best quality",)
    assert join("", "drawing, painting", ", ") == ("drawing, painting",)
    assert join("blurry, ", " drawing", ", ") == ("blurry, drawing",)


def test_toggle_switches_a_number(pkg):
    get = nodes(pkg)["GPC_PS_Toggle"]().get
    assert get(True, on_number=0.7, off_number=0.0, label="x", advanced=False) == (True, 0.7)
    assert get(False, label="x", advanced=False) == (False, 0.0)


def test_fit_resolution_scale(pkg):
    image, mask, w, h = nodes(pkg)["GPC_PS_FitResolution"]().fit(torch.rand(1, 1168, 2000, 3), 1.0, 6.0, 8, scale=1.5)
    assert (w, h) == (3000, 1752)


def test_auto_tile_only_tiles_crops_too_big_for_one_piece(pkg):
    pick = nodes(pkg)["GPC_PS_AutoTile"]().pick
    small, big = torch.rand(1, 1024, 1024, 3), torch.rand(1, 2048, 2048, 3)
    assert pick(small, True, 1.0, 2.0, 6.0) == (False, 2.0)
    assert pick(small, True, 1.5, 2.0, 6.0) == (True, 6.0)  # 1536 px: 2.25 MP
    assert pick(big, True, 1.0, 2.0, 6.0) == (True, 6.0)
    assert pick(big, False, 1.0, 2.0, 6.0) == (False, 2.0)

def test_known_packs_match_prefixes_and_names(pkg):
    from gpc_photoshop.nodes import templates

    hint = templates.install_hint(["HintImageEnchance", "ETN_LoadImageBase64", "INPAINT_ColorMatch"])
    assert "comfyui_controlnet_aux" in hint and "comfyui-tooling-nodes" in hint and "comfyui-inpaint-nodes" in hint


def test_models_are_found_by_file_name_in_any_subfolder(pkg):
    from gpc_photoshop.nodes import templates

    installed = {
        "checkpoints": ["SDXL\\juggernautXL_ragnarokBy.safetensors", "other.safetensors"],
        "controlnet": ["xinsir-controlnet-union-sdxl-1.0-promax.safetensors"],
        "clip_vision": [],
        "ipadapter": ["a/ip-adapter-plus_sdxl_vit-h.safetensors", "b/ip-adapter-plus_sdxl_vit-h.safetensors"],
    }

    def files(folder):
        return installed[folder]

    template = templates.load_template("sdxl_img2img")
    missing = templates.resolve_models(template, files)
    loaded = {n["class_type"]: n["inputs"] for n in template.values()}
    assert loaded["CheckpointLoaderSimple"]["ckpt_name"] == "SDXL\\juggernautXL_ragnarokBy.safetensors"
    assert loaded["ControlNetLoader"]["control_net_name"] == "xinsir-controlnet-union-sdxl-1.0-promax.safetensors"
    assert sorted(missing) == [("clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"), ("ipadapter", "ip-adapter-plus_sdxl_vit-h.safetensors")], "missing, or found twice"
    check = templates.check_template("sdxl_img2img", set(), files)
    assert "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors (in models/clip_vision)" in check["message"]
    assert check["models"] == ["ip-adapter-plus_sdxl_vit-h.safetensors", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]
