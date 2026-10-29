// Reads a template's marker nodes and fills them in. Pure JS: no Photoshop or
// CEP APIs, so it runs (and is tested) under Node too.

const MARKERS = {
  canvas: "GPC_PS_Canvas",
  output: "GPC_PS_Output",
  seed: "GPC_PS_Seed",
  text: "GPC_PS_Text",
  int: "GPC_PS_Int",
  float: "GPC_PS_Float",
  toggle: "GPC_PS_Toggle",
  references: ["GPC_PS_ReferenceImage", "GPC_PS_ReferenceLatent"],
  referenceLatent: "GPC_PS_ReferenceLatent",
  coreReferenceLatent: "ReferenceLatent",
  magnific: "GPC_Magnific_NanoBanana",
};

const byId = (a, b) => Number(a.id) - Number(b.id) || String(a.id).localeCompare(String(b.id));

// What the panel needs to show for a template. Throws when it can't be used.
function describe(template) {
  const nodes = Object.entries(template).map(([id, node]) => ({ id, ...node }));
  const of = (cls) => nodes.filter((n) => n.class_type === cls).sort(byId);
  const plain = (v) => (Array.isArray(v) ? null : v); // a linked input has no value of its own

  const canvas = of(MARKERS.canvas);
  const outputs = of(MARKERS.output);
  if (canvas.length !== 1) throw new Error(`A template needs exactly one PS Canvas node (found ${canvas.length}).`);
  if (!outputs.length) throw new Error("A template needs a PS Output node.");

  const controls = [];
  const hint = (n) => plain(n.inputs.hint) || "";
  for (const n of of(MARKERS.text)) {
    controls.push({ id: n.id, kind: "text", label: n.inputs.label || "Prompt", value: plain(n.inputs.text) ?? "", advanced: !!n.inputs.advanced, hint: hint(n) });
  }
  for (const kind of ["int", "float"]) {
    for (const n of of(MARKERS[kind])) {
      const i = n.inputs;
      controls.push({ id: n.id, kind, label: i.label, value: plain(i.value), min: i.min, max: i.max, step: i.step, advanced: !!i.advanced, main: !!i.main, hint: hint(n) });
    }
  }
  for (const n of of(MARKERS.toggle)) {
    controls.push({ id: n.id, kind: "toggle", label: n.inputs.label, value: !!plain(n.inputs.value), advanced: !!n.inputs.advanced, main: !!n.inputs.main, hint: hint(n) });
  }
  controls.sort(byId);

  const seeds = of(MARKERS.seed).map((n) => ({ id: n.id, value: plain(n.inputs.seed) ?? 0 }));
  // Nano Banana takes the canvas as image 1 and the slots after it.
  const magnific = of(MARKERS.magnific);
  const references = nodes
    .filter((n) => MARKERS.references.includes(n.class_type))
    .map((n) => ({
      id: n.id,
      slot: n.inputs.slot,
      label: n.inputs.label || `Reference ${n.inputs.slot}`,
      numbered: n.class_type === MARKERS.referenceLatent || magnific.length > 0,
    }))
    .sort((a, b) => a.slot - b.slot);

  // Edit models number their images in chain order: core reference latents
  // (the canvas, in the bundled templates) first, then the panel's slots.
  const imageOffset = of(MARKERS.coreReferenceLatent).length + magnific.length;
  // "over selection" (1:1 over the crop) or "upscaled" (larger than what was sent).
  const placement = plain(outputs[0].inputs.placement) || "over selection";
  // The panel tab it's listed under; templates from before tabs go by placement.
  const declared = plain(outputs[0].inputs.mode);
  const mode = MODES.some((m) => m.id === declared) ? declared : placement === "upscaled" ? "upscale" : "edit";
  return { canvas: canvas[0].id, outputs: outputs.map((n) => n.id), controls, seeds, references, imageOffset, placement, mode };
}

// The panel's tabs, in order.
const MODES = [
  { id: "edit", label: "Edit" },
  { id: "refine", label: "Refine" },
  { id: "upscale", label: "Upscale" },
  { id: "magnific", label: "Magnific" },
];

// Aspect ratios Nano Banana makes (nodes/magnific.py has the same lists).
const RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"];
const WIDE_RATIOS = RATIOS.concat(["1:4", "4:1", "1:8", "8:1"]);

// The Nano Banana node's settings in a template, or null: { model, ratios, resolution }.
function magnificNode(template) {
  const node = Object.values(template).find((n) => n.class_type === MARKERS.magnific);
  if (!node) return null;
  const model = node.inputs.model;
  return { model, ratios: model === "Nano Banana 2.1" ? WIDE_RATIOS : RATIOS, resolution: node.inputs.resolution || "auto" };
}

// The crop grown to the listed ratio nearest its own, centered and kept inside
// the document. When the document has no room for one, the crop stays as it is.
function fitRatio(crop, doc, ratios) {
  const w = crop.right - crop.left;
  const h = crop.bottom - crop.top;
  const value = (r) => r.split(":").reduce((a, b) => a / b);
  const byCloseness = ratios.slice().sort((a, b) => Math.abs(Math.log(value(a) / (w / h))) - Math.abs(Math.log(value(b) / (w / h))));
  for (const ratio of byCloseness) {
    const r = value(ratio);
    const nw = Math.max(w, Math.round(h * r));
    const nh = Math.max(h, Math.round(nw / r));
    if (nw > doc.width || nh > doc.height) continue;
    const place = (start, size, grown, limit) => Math.min(limit - grown, Math.max(0, Math.round(start - (grown - size) / 2)));
    const left = place(crop.left, w, nw, doc.width);
    const top = place(crop.top, h, nh, doc.height);
    return { left, top, right: left + nw, bottom: top + nh, ratio };
  }
  return { ...crop, ratio: null };
}

// Models whose 1K costs the same as 2K: "auto" always takes 2K for them.
const FLAT_PRICE = ["Nano Banana Pro", "Nano Banana Pro Flash"];

// 1K or 2K, as the Nano Banana node picks it for "auto": 2K where it costs the
// same, else 1K up to about 1 MP.
function magnificResolution(crop, setting, model) {
  if (setting && setting !== "auto") return setting;
  if (FLAT_PRICE.includes(model)) return "2K";
  return (crop.right - crop.left) * (crop.bottom - crop.top) <= 1024 * 1024 * 1.05 ? "1K" : "2K";
}

// Saved values are stored with their control's label: { [id]: { label, value } }.
function packValues(info, values) {
  const out = {};
  for (const c of info.controls) if (c.id in values) out[c.id] = { label: c.label, value: values[c.id] };
  return out;
}

// The saved values that still fit the template: same label and kind, numbers
// clamped to the range. A control that was renamed or reused starts from its
// default. Older saves (bare values, no label) keep only their text.
function restoreValues(info, saved) {
  const out = {};
  for (const c of info.controls) {
    const entry = saved && saved[c.id];
    if (entry === undefined || entry === null) continue;
    const labelled = typeof entry === "object";
    if (labelled && entry.label !== c.label) continue;
    if (!labelled && c.kind !== "text") continue;
    const v = labelled ? entry.value : entry;
    if (c.kind === "text" && typeof v === "string") out[c.id] = v;
    else if (c.kind === "toggle" && typeof v === "boolean") out[c.id] = v;
    else if ((c.kind === "int" || c.kind === "float") && typeof v === "number" && Number.isFinite(v)) {
      out[c.id] = Math.min(c.max ?? v, Math.max(c.min ?? v, v));
    }
  }
  return out;
}

// Whether a value differs from the template's default.
function isChanged(control, value) {
  if (value === undefined) return false;
  if (control.kind === "int" || control.kind === "float") return Math.abs(Number(value) - Number(control.value)) > 1e-9;
  return value !== control.value;
}

// Whether a run on `crop` will be sampled in tiles (PS Auto Tile decides; it
// reads the same panel values). False for templates without it.
function willTile(template, crop, values = {}) {
  const auto = Object.values(template).find((n) => n.class_type === "GPC_PS_AutoTile");
  if (!auto) return false;
  const read = (v) => {
    if (!Array.isArray(v)) return v;
    const id = String(v[0]);
    const node = template[id];
    if (!node) return undefined;
    if (id in values) return values[id];
    return node.class_type === MARKERS.text ? node.inputs.text : node.inputs.value;
  };
  const scale = Number(read(auto.inputs.scale) ?? 1);
  const limit = Number(read(auto.inputs.untiled_max_megapixels) ?? 2) * 1024 * 1024;
  const pixels = (crop.right - crop.left) * (crop.bottom - crop.top);
  return !!read(auto.inputs.auto) && pixels * scale * scale > limit;
}

// "image N" for each filled reference slot that the model numbers: { [slot]: N }.
function imageNumbers(info, filledSlots) {
  const numbers = {};
  let n = info.imageOffset;
  for (const ref of info.references) {
    if (ref.numbered && filledSlots.includes(ref.slot)) numbers[ref.slot] = "image " + ++n;
  }
  return numbers;
}

// Replaces <Reference 1>-style mentions of slot labels with what the model calls them.
function nameReferences(text, info, filledSlots) {
  const numbers = imageNumbers(info, filledSlots);
  return info.references.reduce((out, ref) => {
    const token = new RegExp("<\\s*" + ref.label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*>", "gi");
    return out.replace(token, (match) => {
      if (!numbers[ref.slot]) throw new Error(`The prompt mentions ${match}, but that reference slot is empty.`);
      return numbers[ref.slot];
    });
  }, text);
}

// A copy of the template ready to queue.
// values: { [controlId]: value }, seed: number, canvas: { image, mask } (base64),
// references: { [slot]: base64 }
function build(template, { values = {}, seed, canvas, references = {} }) {
  const prompt = JSON.parse(JSON.stringify(template));
  const info = describe(prompt);
  for (const node of Object.values(prompt)) delete node._meta;

  Object.assign(prompt[info.canvas].inputs, { image: canvas.image, mask: canvas.mask || "" });
  for (const ref of info.references) prompt[ref.id].inputs.image = references[ref.slot] || "";
  for (const c of info.controls) {
    if (!(c.id in values)) continue;
    const key = c.kind === "text" ? "text" : "value";
    prompt[c.id].inputs[key] = c.kind === "int" ? Math.round(values[c.id]) : values[c.id];
  }
  const filled = Object.keys(references).filter((slot) => references[slot]).map(Number);
  for (const c of info.controls) {
    if (c.kind === "text") prompt[c.id].inputs.text = nameReferences(String(prompt[c.id].inputs.text), info, filled);
  }
  if (seed !== undefined) for (const s of info.seeds) prompt[s.id].inputs.seed = seed;
  return prompt;
}

// The area sent to the model: the selection plus context padding, inside the document.
function cropRect(selection, doc, padding) {
  const w = selection.right - selection.left;
  const h = selection.bottom - selection.top;
  const pad = Math.round(Math.max(w, h) * padding);
  return {
    left: Math.max(0, selection.left - pad),
    top: Math.max(0, selection.top - pad),
    right: Math.min(doc.width, selection.right + pad),
    bottom: Math.min(doc.height, selection.bottom + pad),
  };
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const out = [];
  let i = 0;
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
    out.push(B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63]);
  }
  if (i < bytes.length) {
    const n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8);
    out.push(B64[n >> 18] + B64[(n >> 12) & 63] + (i + 1 < bytes.length ? B64[(n >> 6) & 63] : "=") + "=");
  }
  return out.join("");
}

module.exports = { MARKERS, MODES, describe, build, imageNumbers, cropRect, toBase64, packValues, restoreValues, isChanged, willTile, magnificNode, fitRatio, magnificResolution };
