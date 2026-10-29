const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { describe, build, cropRect, toBase64, packValues, restoreValues, isChanged, willTile } = require("../../photoshop/src/template.js");

const klein = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/flux2_klein_inpaint.json"), "utf8"));

test("describe finds the Klein template's markers", () => {
  const info = describe(klein);
  assert.strictEqual(info.canvas, "5");
  assert.deepStrictEqual(info.outputs, ["32"]);
  assert.deepStrictEqual(info.references.map((r) => r.slot), [1, 2]);
  assert.deepStrictEqual(info.seeds, [{ id: "47", value: 0 }]);
  const labels = info.controls.map((c) => c.label);
  assert.deepStrictEqual(labels, ["Mask grow", "Mask feather", "Blend shrink", "Blend feather", "Batch", "Steps", "Strength", "Prompt"]);
  const visible = info.controls.filter((c) => !c.advanced && c.kind !== "text").map((c) => c.label);
  assert.deepStrictEqual(visible, ["Batch", "Strength"]);
});

test("build fills markers and leaves the template untouched", () => {
  const prompt = build(klein, {
    values: { 50: "a potted grass", 44: 3.4, 46: 0.8 },
    seed: 42,
    canvas: { image: "IMG", mask: "MASK" },
    references: { 2: "REF2" },
  });
  assert.deepStrictEqual(prompt["5"].inputs, { image: "IMG", mask: "MASK" });
  assert.strictEqual(prompt["50"].inputs.text, "a potted grass");
  assert.strictEqual(prompt["44"].inputs.value, 3);
  assert.strictEqual(prompt["46"].inputs.value, 0.8);
  assert.strictEqual(prompt["47"].inputs.seed, 42);
  assert.strictEqual(prompt["18"].inputs.image, "");
  assert.strictEqual(prompt["19"].inputs.image, "REF2");
  assert.strictEqual(prompt["5"]._meta, undefined);
  assert.strictEqual(klein["5"].inputs.image, "");
  // links survive
  assert.deepStrictEqual(prompt["29"].inputs.width, ["5", 2]);
});

test("describe rejects templates without a canvas or output", () => {
  assert.throws(() => describe({ 1: { class_type: "GPC_PS_Output", inputs: {} } }), /PS Canvas/);
  assert.throws(() => describe({ 1: { class_type: "GPC_PS_Canvas", inputs: {} } }), /PS Output/);
});

test("cropRect pads by the selection's long side and clamps to the document", () => {
  const doc = { width: 1000, height: 800 };
  assert.deepStrictEqual(cropRect({ left: 400, top: 300, right: 500, bottom: 350 }, doc, 0.5), { left: 350, top: 250, right: 550, bottom: 400 });
  assert.deepStrictEqual(cropRect({ left: 10, top: 10, right: 990, bottom: 790 }, doc, 0.5), { left: 0, top: 0, right: 1000, bottom: 800 });
});

test("toBase64 matches Node's encoder", () => {
  for (const n of [0, 1, 2, 3, 4, 5, 255, 1000]) {
    const bytes = Uint8Array.from({ length: n }, (_, i) => (i * 37 + n) & 255);
    assert.strictEqual(toBase64(bytes.buffer), Buffer.from(bytes).toString("base64"));
  }
});

test("reference slots are numbered after the canvas, counting only filled ones", () => {
  const { imageNumbers } = require("../../photoshop/src/template.js");
  const info = describe(klein);
  assert.strictEqual(info.imageOffset, 1);
  assert.deepStrictEqual(imageNumbers(info, [1, 2]), { 1: "image 2", 2: "image 3" });
  assert.deepStrictEqual(imageNumbers(info, [2]), { 2: "image 2" });
});

test("<Reference N> in the prompt becomes the model's image number", () => {
  const prompt = build(klein, {
    values: { 50: "Add flowers like <reference 2> next to < Reference 2 >" },
    canvas: { image: "I" },
    references: { 2: "R" },
  });
  assert.strictEqual(prompt["50"].inputs.text, "Add flowers like image 2 next to image 2");
  assert.throws(
    () => build(klein, { values: { 50: "like <Reference 1>" }, canvas: { image: "I" }, references: { 2: "R" } }),
    /mentions <Reference 1>, but that reference slot is empty/
  );
});

test("the SDXL template: prompt and negative up top, suffixes under Advanced, strength and ControlNet in the main area", () => {
  const sdxl = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/sdxl_img2img.json"), "utf8"));
  const info = describe(sdxl);
  const texts = info.controls.filter((c) => c.kind === "text");
  assert.deepStrictEqual(texts.map((c) => [c.label, c.advanced]), [["Prompt", false], ["Negative", false], ["Prompt suffix", true], ["Default negative", true]]);
  assert.deepStrictEqual(info.controls.filter((c) => c.main).map((c) => c.label), ["Strength", "Tile ControlNet"]);
  assert.deepStrictEqual(describe(klein).controls.filter((c) => c.main).map((c) => c.label), ["Strength"]);
  const prompt = build(sdxl, { values: { 60: "a house", 50: false }, seed: 1, canvas: { image: "I" } });
  assert.strictEqual(prompt["60"].inputs.text, "a house");
  assert.strictEqual(prompt["50"].inputs.value, false);
  assert.deepStrictEqual(prompt["50"].inputs.on_number, ["51", 0]); // links survive
});

test("templates say how their results are placed", () => {
  const upscale = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/zimage_upscale.json"), "utf8"));
  assert.strictEqual(describe(upscale).placement, "upscaled");
  assert.strictEqual(describe(klein).placement, "over selection");
  assert.deepStrictEqual(describe(upscale).controls.filter((c) => c.main).map((c) => c.label), ["Scale", "Strength", "Faithfulness"]);
});

test("templates name their panel tab, older ones fall back on placement", () => {
  const sdxl = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/sdxl_img2img.json"), "utf8"));
  const upscale = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/zimage_upscale.json"), "utf8"));
  assert.deepStrictEqual([klein, sdxl, upscale].map((t) => describe(t).mode), ["edit", "refine", "upscale"]);
  const old = JSON.parse(JSON.stringify(upscale));
  delete old["23"].inputs.mode;
  assert.strictEqual(describe(old).mode, "upscale");
  old["23"].inputs.placement = "over selection";
  assert.strictEqual(describe(old).mode, "edit");
  assert.ok(describe(sdxl).controls.filter((c) => c.kind !== "text").every((c) => c.hint), "every bundled setting has a hint");
});

test("saved values come back only for the control they were saved for", () => {
  const sdxl = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/sdxl_img2img.json"), "utf8"));
  const info = describe(sdxl);
  const packed = packValues(info, { 47: 0.7, 60: "a house" });
  assert.deepStrictEqual(packed, { 47: { label: "Strength", value: 0.7 }, 60: { label: "Prompt", value: "a house" } });
  assert.deepStrictEqual(restoreValues(info, packed), { 47: 0.7, 60: "a house" });
  // 75 was "Tiled" before it became "Auto tile": its old value doesn't carry over
  assert.deepStrictEqual(restoreValues(info, { 75: { label: "Tiled", value: false } }), {});
  // older saves: bare values keep only text
  assert.deepStrictEqual(restoreValues(info, { 52: 0.8, 60: "a house" }), { 60: "a house" });
  // wrong types are dropped, numbers clamped
  assert.deepStrictEqual(restoreValues(info, { 47: { label: "Strength", value: 5 }, 50: { label: "Tile ControlNet", value: "yes" } }), { 47: 1 });
  const strength = info.controls.find((c) => c.label === "Strength");
  assert.strictEqual(isChanged(strength, 0.5), false);
  assert.strictEqual(isChanged(strength, 0.55), true);
  assert.strictEqual(isChanged(strength, undefined), false);
});

test("willTile follows PS Auto Tile: crop times resolution scale over 2 MP", () => {
  const sdxl = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/sdxl_img2img.json"), "utf8"));
  const square = (n) => ({ left: 0, top: 0, right: n, bottom: n });
  assert.strictEqual(willTile(sdxl, square(800)), false); // 1200 px at 1.5x: 1.4 MP
  assert.strictEqual(willTile(sdxl, square(1024)), true); // 1536 px: 2.25 MP
  assert.strictEqual(willTile(sdxl, square(1024), { 53: 1.0 }), false);
  assert.strictEqual(willTile(sdxl, square(2048), { 75: false }), false);
  assert.strictEqual(willTile(klein, square(4000)), false);
});

test("Nano Banana templates: Magnific tab, references numbered after the canvas", () => {
  const { imageNumbers, magnificNode } = require("../../photoshop/src/template.js");
  const banana = JSON.parse(fs.readFileSync(path.join(__dirname, "../../templates/nano_banana_2_1.json"), "utf8"));
  const info = describe(banana);
  assert.strictEqual(info.mode, "magnific");
  assert.deepStrictEqual(imageNumbers(info, [2]), { 2: "image 2" });
  assert.deepStrictEqual(imageNumbers(info, [1, 2]), { 1: "image 2", 2: "image 3" });
  assert.ok(info.controls.filter((c) => c.kind !== "text").every((c) => c.hint));
  assert.strictEqual(magnificNode(banana).ratios.length, 14);
  assert.strictEqual(magnificNode(klein), null);
});

test("fitRatio grows the crop to the nearest ratio inside the document", () => {
  const { fitRatio } = require("../../photoshop/src/template.js");
  const doc = { width: 4000, height: 3000 };
  const ratios = ["1:1", "4:3", "16:9"];
  // 1000 x 800 (1.25) -> 4:3 (1.33): wider, centered.
  assert.deepStrictEqual(fitRatio({ left: 1000, top: 1000, right: 2000, bottom: 1800 }, doc, ratios), { left: 967, top: 1000, right: 2034, bottom: 1800, ratio: "4:3" });
  // Against the document edge: shifted back inside.
  assert.deepStrictEqual(fitRatio({ left: 0, top: 0, right: 1000, bottom: 800 }, doc, ratios), { left: 0, top: 0, right: 1067, bottom: 800, ratio: "4:3" });
  // No room for any ratio: unchanged.
  const tall = { width: 500, height: 3000 };
  assert.deepStrictEqual(fitRatio({ left: 0, top: 0, right: 500, bottom: 3000 }, tall, ratios), { left: 0, top: 0, right: 500, bottom: 3000, ratio: null });
});

test("magnificResolution: 1K up to about a megapixel, else 2K; always 2K where that costs the same", () => {
  const { magnificResolution } = require("../../photoshop/src/template.js");
  const crop = (w, h) => ({ left: 0, top: 0, right: w, bottom: h });
  assert.strictEqual(magnificResolution(crop(1024, 1024), "auto", "Nano Banana 2.1"), "1K");
  assert.strictEqual(magnificResolution(crop(1400, 1000), "auto", "Nano Banana 2.1"), "2K");
  assert.strictEqual(magnificResolution(crop(400, 400), "auto", "Nano Banana Pro"), "2K", "Pro's 1K costs the same as 2K");
  assert.strictEqual(magnificResolution(crop(400, 400), "4K", "Nano Banana 2.1"), "4K");
});
