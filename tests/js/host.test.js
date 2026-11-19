// The ExtendScript host and the panel's bridge to it, against a fake Photoshop.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const jsx = fs.readFileSync(path.join(__dirname, "../../photoshop/host/photoshop.jsx"), "utf8");

const px = (v) => ({ as: () => v });

function fakePhotoshop({ selection = null } = {}) {
  const layers = [
    { id: 3, name: 'Say "hi"', typename: "ArtLayer" },
    { id: 4, name: "Group", typename: "LayerSet", layers: [{ id: 5, name: "Inner", typename: "ArtLayer" }] },
  ];
  const doc = {
    id: 7, name: "render.psd", width: px(1200), height: px(800), resolution: 300, layers,
    selection: { get bounds() { if (!selection) throw new Error("no selection"); return selection.map(px); } },
  };
  const sandbox = {
    app: { documents: [doc], activeDocument: doc, preferences: { rulerUnits: "in" }, displayDialogs: "all" },
    Units: { PIXELS: "px" },
    DialogModes: { NO: "no" },
  };
  vm.createContext(sandbox);
  vm.runInContext(jsx, sandbox);
  return sandbox;
}

test("host functions return JSON the panel can parse", () => {
  const ps = fakePhotoshop({ selection: [10.4, 20, 110, 220.6] });
  assert.deepStrictEqual(JSON.parse(ps.gpcDocInfo()), { id: 7, width: 1200, height: 800, resolution: 300, title: "render.psd" });
  assert.deepStrictEqual(JSON.parse(ps.gpcSelectionBounds()), { left: 10, top: 20, right: 110, bottom: 221 });
  assert.deepStrictEqual(JSON.parse(ps.gpcLayers()), [
    { id: 3, name: 'Say "hi"' },
    { id: 5, name: "Group / Inner" },
  ]);
  // settings are put back
  assert.strictEqual(ps.app.preferences.rulerUnits, "in");
  assert.strictEqual(ps.app.displayDialogs, "all");
});

test("no selection is null, and errors come back as ERROR strings", () => {
  const ps = fakePhotoshop();
  assert.strictEqual(ps.gpcSelectionBounds(), "null");
  ps.app.documents = [];
  assert.strictEqual(ps.gpcDocInfo(), "ERROR: Open a document first.");
  assert.match(ps.gpcPlace("x.png", 1, 0, 0, [0, 0, 10, 10], "n", 0), /^ERROR: The document this was generated for is closed/);
  assert.match(ps.gpcBake(1, 2, "n"), /^ERROR: The document this was generated for is closed/);
});

test("gpcQuote escapes quotes, backslashes and control characters", () => {
  const ps = fakePhotoshop();
  const s = 'C:\\Users\\Someone "S"\n\ttab';
  assert.strictEqual(JSON.parse(ps.gpcQuote(s)), s);
});

test("the panel bridge passes arguments as script literals and reads results", async () => {
  const calls = [];
  global.window = {
    __adobe_cep__: {
      evalScript(script, done) {
        calls.push(script);
        const ps = fakePhotoshop({ selection: [0, 0, 5, 5] });
        done(String(vm.runInContext(script, ps)));
      },
    },
  };
  const bridge = require("../../photoshop/src/photoshop.js");
  assert.deepStrictEqual(await bridge.selectionBounds(), { left: 0, top: 0, right: 5, bottom: 5 });
  const png = fs.readFileSync(path.join(__dirname, "fixtures", "rgba_margin_c1.png")); // 53x37, visible 7,5 to 41,30
  await assert.rejects(bridge.place(png, { docId: 99, crop: { left: 1, top: 2, right: 54, bottom: 39 }, resolution: 300, name: 'a "b" \\ c' }), /document this was generated for is closed/);
  assert.match(calls[1], /^gpcPlace\(".*result_1\.png",99,1,2,\[7,5,41,30\],"a \\"b\\" \\\\ c",0\)$/);
  await assert.rejects(bridge.bake(99, 5, "n"), /document this was generated for is closed/);
  assert.strictEqual(JSON.parse(await new Promise((r) => window.__adobe_cep__.evalScript("gpcRemoveLayer(99, 5)", r))), "ok");
  delete global.window;
});

// Place puts the image's center at the canvas center (optionally scaled, as
// "Resize Image During Place" does); Photoshop then reports the layer's bounds
// as its visible pixels only. gpcPlace must still land the image's own top-left
// on (left, top).
test("gpcPlace lands the image's corner on the crop, despite transparent margins and scaling", () => {
  // [how Place sized it, the size wanted]: 1:1 inpaints, a stray resize, a 2x upscale fit into its crop
  for (const [scale, want] of [[1, 1], [1.25, 1], [0.5, 0.5], [0.8, 0.5]]) {
    const ps = fakePhotoshop();
    const doc = ps.app.activeDocument;
    const image = { width: 53, height: 37, vis: [7, 5, 41, 30] };
    let layer;
    Object.assign(ps, {
      ActionDescriptor: class { putPath() {} putEnumerated() {} putUnitDouble() {} putObject() {} },
      charIDToTypeID: (s) => s,
      File: class {},
      AnchorPosition: { TOPLEFT: "tl" },
      executeAction() {
        // image origin and scale on the canvas
        const s = scale;
        const origin = [600 - (image.width * s) / 2, 400 - (image.height * s) / 2];
        layer = {
          id: 42,
          origin, s,
          get bounds() {
            const [l, t, r, b] = image.vis;
            return [l, t, r, b].map((v, i) => px(this.origin[i % 2] + v * this.s));
          },
          resize(px_, py_, anchor) {
            assert.strictEqual(anchor, "tl");
            const [l, t] = image.vis;
            const before = [this.origin[0] + l * this.s, this.origin[1] + t * this.s];
            this.s *= px_ / 100;
            this.origin = [before[0] - l * this.s, before[1] - t * this.s];
          },
          translate(dx, dy) {
            this.origin = [this.origin[0] + dx, this.origin[1] + dy];
          },
        };
        doc.activeLayer = layer;
      },
    });
    doc.suspendHistory = (title, code) => vm.runInContext(code, ps);
    ps.$ = { global: ps };
    ps.gpcFindLayer = () => null;
    const id = ps.gpcPlace("r.png", 7, 300, 200, image.vis.map((v) => v * want), "GPC preview", 0);
    assert.strictEqual(id, "42");
    assert.ok(Math.abs(layer.s - want) < 1e-9, `scale ${layer.s}`);
    assert.deepStrictEqual(layer.origin.map((v) => Math.round(v * 1000) / 1000), [300, 200]);
  }
});

test("an upscaled result is placed to fit the crop, keeping its pixels", async () => {
  const calls = [];
  global.window = { __adobe_cep__: { evalScript: (script, done) => (calls.push(script), done("7")) } };
  const bridge = require("../../photoshop/src/photoshop.js");
  const png = fs.readFileSync(path.join(__dirname, "fixtures", "rgba_margin_c1.png")); // 53x37, visible 7,5 to 41,30
  // The crop is half the image's size, as after a 2x upscale.
  const crop = { left: 10, top: 20, right: 10 + 26.5, bottom: 20 + 18.5 };
  assert.strictEqual(await bridge.place(png, { docId: 1, crop, resolution: 72, name: "u" }), 7);
  assert.match(calls[0], /^gpcPlace\(".*",1,10,20,\[3\.5,2\.5,20\.5,15\],"u",0\)$/);
  delete global.window;
});

test("gpcPlace with a mask: the mask's layer lands on the crop, becomes the layer mask, and the selection stays", () => {
  const ps = fakePhotoshop({ selection: [1, 2, 3, 4] });
  const doc = ps.app.activeDocument;
  const events = [];
  const placed = { id: 42, bounds: [300, 200, 400, 300].map(px), translate() {} };
  // The mask's visible pixels start at (10, 6) inside the mask; the copy lands somewhere else.
  const carrier = {
    id: 77, at: [500, 500],
    get bounds() { return [this.at[0], this.at[1], this.at[0] + 50, this.at[1] + 40].map(px); },
    translate(dx, dy) { this.at = [this.at[0] + dx, this.at[1] + dy]; },
    remove() { events.push("remove carrier"); },
  };
  const maskDoc = {
    channels: ["Gray"],
    artLayers: { add: () => ({ bounds: [10, 6, 60, 46].map(px), duplicate: (to) => (assert.strictEqual(to, doc), carrier) }) },
    selection: { load: (c) => events.push("load " + c), fill: () => events.push("fill"), deselect() {} },
    resizeImage: (w, h) => events.push(`resize ${w.v}x${h.v}`),
    close: () => events.push("close mask"),
  };
  doc.channels = { add: () => ({ remove: () => events.push("drop kept"), set name(n) {} }) };
  doc.selection.store = () => events.push("store selection");
  doc.selection.load = () => events.push("restore selection");
  Object.assign(ps, {
    ActionDescriptor: class { putPath() {} putEnumerated() {} putUnitDouble() {} putObject() {} putReference() {} putClass() {} },
    ActionReference: class { putProperty() {} putEnumerated() {} putIdentifier(_, id) { events.push("from layer " + id); } },
    charIDToTypeID: (s) => s,
    File: class {},
    UnitValue: (v) => ({ v }),
    ResampleMethod: { BICUBIC: "bicubic" },
    ElementPlacement: { PLACEATBEGINNING: "top" },
    SaveOptions: { DONOTSAVECHANGES: "no" },
    SolidColor: class { constructor() { this.rgb = {}; } },
    executeAction(id) {
      events.push("action " + id);
      if (id === "Plc ") doc.activeLayer = placed;
    },
  });
  ps.app.open = () => maskDoc;
  doc.suspendHistory = (title, code) => vm.runInContext(code, ps);
  ps.$ = { global: ps };
  ps.gpcFindLayer = () => null;
  assert.strictEqual(ps.gpcPlace("r.png", 7, 300, 200, [0, 0, 100, 100], "GPC preview", 0, "m.png", 100, 100), "42");
  assert.deepStrictEqual(carrier.at, [310, 206], "the mask's top-left is on the crop's");
  assert.deepStrictEqual(events, [
    "resize 100x100", "load Gray", "fill", "close mask",
    "action Plc ", "store selection", "from layer 77", "action setd", "remove carrier", "action Mk  ",
    "restore selection", "drop kept",
  ]);
  assert.strictEqual(doc.activeLayer, placed, "the mask goes on the placed layer");
});

test("the bridge sends a mask file and the crop's size only when there is a mask", async () => {
  const calls = [];
  global.window = { __adobe_cep__: { evalScript: (script, done) => (calls.push(script), done("7")) } };
  const bridge = require("../../photoshop/src/photoshop.js");
  const png = fs.readFileSync(path.join(__dirname, "fixtures", "rgba_margin_c1.png"));
  const crop = { left: 10, top: 20, right: 63, bottom: 57 };
  await bridge.place(png, { docId: 1, crop, resolution: 72, name: "m", mask: png });
  assert.match(calls[0], /^gpcPlace\(".*result_\d+\.png",1,10,20,\[.*\],"m",0,".*result_\d+_mask\.png",53,37\)$/);
  delete global.window;
});

test("gpcStack wraps the result in a PSB smart object, places the others inside, and shows one", () => {
  const ps = fakePhotoshop();
  const doc = ps.app.activeDocument;
  const placed = { id: 42, name: "GPC preview" };
  const wrapper = { id: 50, name: "Layer 1" };
  doc.layers.push(placed);
  const events = [];
  // Inside: the wrapped result, then each Place lands centered (here 2 px off) and is put back on 0,0.
  const inner = { width: px(1200), height: px(800), layers: [{ name: "GPC preview", visible: true }], save() { events.push("save"); }, close() { events.push("close"); } };
  const placedInside = (n) => ({
    name: "", visible: true, at: [2, 2],
    get bounds() { return [this.at[0], this.at[1], this.at[0] + 1200, this.at[1] + 800].map(px); },
    resize() { throw new Error("Place sized it right"); },
    translate(dx, dy) { this.at = [this.at[0] + dx, this.at[1] + dy]; },
  });
  Object.assign(ps, {
    ActionDescriptor: class { putPath() {} putEnumerated() {} putUnitDouble() {} putObject() {} },
    charIDToTypeID: (s) => s,
    stringIDToTypeID: (s) => s,
    File: class {},
    AnchorPosition: { TOPLEFT: "tl" },
    SaveOptions: { DONOTSAVECHANGES: "no" },
    executeAction(id) {
      events.push(id);
      if (id === "newPlacedLayer") {
        assert.strictEqual(doc.activeLayer, placed);
        doc.activeLayer = wrapper;
        doc.layers.push(wrapper);
      } else if (id === "placedLayerEditContents") {
        assert.strictEqual(doc.activeLayer, wrapper, "the contents opened are the wrapper's (a PSB)");
        ps.app.activeDocument = inner;
      } else if (id === "Plc ") {
        const l = placedInside();
        inner.layers.unshift(l);
        inner.activeLayer = l;
      }
    },
  });
  assert.strictEqual(ps.gpcStack(7, 42, ["a.png", "b.png", "c.png"], 2), "50");
  assert.strictEqual(wrapper.name, "GPC preview");
  assert.deepStrictEqual(events, ["newPlacedLayer", "placedLayerEditContents", "Plc ", "Plc ", "Plc ", "save", "close"]);
  assert.deepStrictEqual(inner.layers.map((l) => [l.name, l.visible]), [["Result 4", false], ["Result 3", true], ["Result 2", false], ["Result 1", false]]);
  assert.ok(inner.layers.slice(0, 3).every((l) => l.at[0] === 0 && l.at[1] === 0), "every result back on the corner");
  assert.strictEqual(ps.app.activeDocument, doc);
  ps.app.activeDocument = doc;
  assert.strictEqual(JSON.parse(ps.gpcStackShow(7, 50, 0)), "ok");
  assert.deepStrictEqual(inner.layers.map((l) => l.visible), [false, false, false, true]);
});

test("the bridge writes stacked results at the crop's scale and passes the mask's box", async () => {
  const calls = [];
  global.window = { __adobe_cep__: { evalScript: (script, done) => (calls.push(script), done("50")) } };
  const bridge = require("../../photoshop/src/photoshop.js");
  const png = fs.readFileSync(path.join(__dirname, "fixtures", "rgba_margin_c1.png")); // 53 px wide
  const crop = { left: 10, top: 20, right: 36.5, bottom: 38.5 };
  assert.strictEqual(await bridge.stack(1, 42, [png], 1, { crop, resolution: 72, mask: png }), 50);
  assert.match(calls[0], /^gpcStack\(1,42,\[".*stack_\d+_0\.png"\],1,".*stack_\d+_mask\.png",10,20,26\.5,18\.5\)$/);
  delete global.window;
});
