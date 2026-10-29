// The panel: connects to ComfyUI, builds controls from the chosen template,
// exports the selection, queues the template and previews the results.

// CEP resolves require() from Photoshop's folder, so load modules by full path.
const EXTENSION = window.__adobe_cep__.getSystemPath("extension").replace(/^file:\/*/, "/").replace(/^\/([A-Za-z]:)/, "$1");
const local = (file) => require(decodeURI(EXTENSION) + "/src/" + file);
const { ComfyClient } = local("comfy.js");
const { MODES, describe, build, cropRect, toBase64, packValues, restoreValues, isChanged, willTile, magnificNode, fitRatio, magnificResolution } = local("template.js");
const ps = local("photoshop.js");

const $ = (id) => document.getElementById(id);

const PREVIEW_NAME = "GPC preview";
const PLACEHOLDERS = {
  edit: "Describe the change inside the selection",
  refine: "Describe the image",
  upscale: "Optional: describe the image",
  magnific: "Describe the change, e.g. make the garage doors white",
};
// Context % per tab, unless changed. Nano Banana redraws the whole crop, so it gets less.
const CONTEXT = { magnific: 10 };
const ICONS = {
  x: '<svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6"></path></svg>',
  star: '<svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true"><path d="M7 1.5l1.7 3.5 3.8.5-2.8 2.6.7 3.8L7 10.1 3.6 11.9l.7-3.8L1.5 5.5l3.8-.5z"></path></svg>',
};

// tab: the open tab; templates: the template last used in each tab.
const settings = load("settings", { server: "http://127.0.0.1:8188", template: "", tab: "edit", templates: {}, padding: 50, contexts: {}, autoPreview: true });
// Magnific's API doesn't report the balance; this page does.
const MAGNIFIC_CREDITS = "https://www.magnific.com/user/api-keys";
// catalog: { [mode]: [{ name, template, info }] }, from every template on the server.
const state = { client: null, catalog: {}, template: null, info: null, references: {}, values: {}, controlNodes: {}, hasSelection: true, jobs: [], preview: null, busy: false };

// Photoshop calls run one at a time, so quick clicks can't interleave previews.
let psQueue = Promise.resolve();
function inPhotoshop(fn) {
  const run = psQueue.then(fn);
  psQueue = run.catch(() => {});
  return run;
}

function load(key, fallback) {
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem("gpc." + key) || "{}") };
  } catch (_) {
    return fallback;
  }
}

function save() {
  try {
    localStorage.setItem("gpc.settings", JSON.stringify(settings));
  } catch (_) {
    // settings are a convenience
  }
}

function rememberValues() {
  try {
    localStorage.setItem("gpc.values." + settings.template, JSON.stringify(packValues(state.info, state.values)));
  } catch (_) {
    // values are a convenience
  }
}

function savedValues(name) {
  try {
    return JSON.parse(localStorage.getItem("gpc.values." + name) || "{}");
  } catch (_) {
    return {};
  }
}

function message(text, isError = false) {
  $("message").textContent = text || "";
  $("message").className = "message" + (isError ? " error" : "");
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

const show = (node, visible) => node.classList.toggle("hidden", !visible);

// --- theme: follow Photoshop's interface brightness ---

function applyTheme() {
  try {
    const skin = JSON.parse(window.__adobe_cep__.getHostEnvironment()).appSkinInfo;
    const c = skin.panelBackgroundColor.color;
    document.documentElement.classList.toggle("light", c.red > 128);
    document.documentElement.style.setProperty("--bg", `rgb(${Math.round(c.red)}, ${Math.round(c.green)}, ${Math.round(c.blue)})`);
  } catch (_) {
    // keep the stylesheet's dark colors
  }
}

// --- connection and templates ---

function connectionStatus(ok, text) {
  $("status").textContent = text;
  $("dot").className = "dot " + (ok ? "ok" : "bad");
  $("statusButton").title = text;
}

function showConnection(open) {
  show($("connection"), open);
  $("statusButton").setAttribute("aria-expanded", String(open));
}

async function connect() {
  settings.server = $("server").value.trim() || "http://127.0.0.1:8188";
  save();
  connectionStatus(false, "Connecting…");
  try {
    if (state.client) state.client.close();
    state.client = new ComfyClient(settings.server);
    const names = await state.client.check();
    state.client.connect();
    connectionStatus(true, `Connected to ${settings.server}`);
    showConnection(false);
    message("");
    await loadCatalog(names);
  } catch (e) {
    state.client = null;
    connectionStatus(false, "Not connected: " + e.message);
    showConnection(true);
    message(`Not connected to ComfyUI. ${e.message}`, true);
  }
}

// Reads every template and sorts them into the tabs.
async function loadCatalog(names) {
  const catalog = {};
  const broken = [];
  for (const name of names) {
    try {
      const template = await state.client.template(name);
      const info = describe(template);
      (catalog[info.mode] = catalog[info.mode] || []).push({ name, template, info });
    } catch (e) {
      broken.push(`${name}: ${e.message}`);
    }
  }
  state.catalog = catalog;
  renderTabs();
  if (!names.length) return message("No templates on the server. Add one to ComfyUI/user/gpc_photoshop/.", true);
  const open = catalog[settings.tab] ? settings.tab : MODES.map((m) => m.id).find((id) => catalog[id]);
  if (open) selectTab(open);
  if (broken.length) message("Skipped templates that can't be used:\n" + broken.join("\n"), true);
}

// One tab per kind of job that has templates.
function renderTabs() {
  const list = $("tabs");
  list.innerHTML = "";
  for (const mode of MODES) {
    if (!state.catalog[mode.id]) continue;
    const tab = el("button", { class: "tab", role: "tab", text: mode.label, "aria-selected": String(mode.id === settings.tab) });
    tab.addEventListener("click", () => selectTab(mode.id));
    list.appendChild(tab);
  }
}

function selectTab(mode) {
  settings.tab = mode;
  save();
  renderContext();
  const label = MODES.find((m) => m.id === mode).label;
  for (const tab of $("tabs").children) tab.setAttribute("aria-selected", String(tab.textContent === label));
  const entries = state.catalog[mode] || [];
  const select = $("template");
  select.innerHTML = "";
  for (const { name } of entries) select.appendChild(el("option", { value: name, text: name }));
  show($("templateRow"), entries.length > 1);
  const names = entries.map((e) => e.name);
  const last = settings.templates[mode];
  select.value = names.includes(last) ? last : names[0];
  chooseTemplate(select.value);
}

async function chooseTemplate(name) {
  const entry = (state.catalog[settings.tab] || []).find((e) => e.name === name);
  if (!entry) return;
  settings.template = name;
  settings.templates[settings.tab] = name;
  save();
  $("templateName").textContent = name;
  state.template = entry.template;
  state.info = entry.info;
  state.values = restoreValues(state.info, savedValues(name));
  renderControls();
  if (!state.busy) setBusy(false);
  try {
    const check = await state.client.checkTemplate(name);
    state.missing = check && check.message;
    message(state.missing || "", !!state.missing);
  } catch (e) {
    message(`Template "${name}": ${e.message}`, true);
  }
}

// Back to the template's own settings. Prompts in the main area stay.
function resetValues() {
  const keep = {};
  for (const c of state.info.controls) if (c.kind === "text" && !c.advanced && c.id in state.values) keep[c.id] = state.values[c.id];
  state.values = keep;
  rememberValues();
  renderControls();
}

// Context % around the selection, remembered per tab.
const contextFor = (tab) => settings.contexts[tab] ?? CONTEXT[tab] ?? settings.padding;

function renderContext() {
  const box = $("canvasSettings");
  box.innerHTML = "";
  box.appendChild(
    numberSetting("Context %", { value: contextFor(settings.tab), min: 0, max: 300, step: 5 }, (v) => {
      settings.contexts[settings.tab] = v;
      save();
    })
  );
}

// --- controls built from the template's marker nodes ---

function setValue(id, value) {
  state.values[id] = value;
  rememberValues();
  markChanged();
}

// Dots the settings that differ from the template's defaults.
function markChanged() {
  let count = 0;
  for (const c of state.info.controls) {
    const node = state.controlNodes[c.id];
    const changed = isChanged(c, state.values[c.id]);
    if (node) node.classList.toggle("changed", changed);
    if (changed && c.kind !== "text") count++;
  }
  $("changedNote").textContent = count ? `${count} setting${count === 1 ? "" : "s"} changed from the template` : "Template settings";
  $("reset").disabled = count === 0;
}

// A slider with a number box beside it, for an int/float control.
function numberSetting(label, { value, min, max, step }, onChange, format = String) {
  const id = "c" + Math.random().toString(36).slice(2, 8);
  const range = el("input", { type: "range", id, min, max, step });
  const box = el("input", { type: "number", min, max, step, "aria-label": label });
  range.value = value;
  box.value = format(Number(value));
  const clamp = (v) => Math.min(Number.isFinite(max) ? max : v, Math.max(Number.isFinite(min) ? min : v, v));
  range.addEventListener("input", () => {
    box.value = format(Number(range.value));
    onChange(Number(range.value));
  });
  box.addEventListener("change", () => {
    const v = clamp(Number(box.value));
    box.value = format(v);
    range.value = v;
    onChange(v);
  });
  return el("div", { class: "setting" }, [el("label", { for: id, text: label }), range, box]);
}

function renderControls() {
  const boxes = ["prompts", "extraPrompts", "mainSettings", "advPrompts", "settings", "finetune"].map($);
  const [prompts, extraPrompts, mainSettings, advPrompts, general, fine] = boxes;
  for (const box of boxes) box.innerHTML = "";
  state.controlNodes = {};
  const current = (c) => (c.id in state.values ? state.values[c.id] : c.value);

  const textArea = (c, attrs) => {
    const area = el("textarea", attrs);
    area.value = current(c);
    area.addEventListener("input", () => setValue(c.id, area.value));
    area.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") generate();
    });
    return area;
  };
  // The first main text box is the prompt; others (e.g. a negative) are smaller, with a label.
  state.info.controls
    .filter((c) => c.kind === "text" && !c.advanced)
    .forEach((c, i) => {
      const placeholder = PLACEHOLDERS[state.info.mode];
      if (i === 0) return prompts.appendChild(textArea(c, { id: "prompt", placeholder }));
      extraPrompts.appendChild(el("span", { class: "prompt-label", text: c.label }));
      extraPrompts.appendChild(textArea(c, { class: "secondary", "aria-label": c.label, placeholder: "Optional" }));
    });
  for (const c of state.info.controls.filter((c) => c.kind === "text" && c.advanced)) {
    advPrompts.appendChild(el("span", { class: "prompt-label", text: c.label, ...(c.hint ? { title: c.hint } : {}) }));
    advPrompts.appendChild(textArea(c, { class: "secondary", "aria-label": c.label }));
  }

  for (const c of state.info.controls) {
    if (c.kind === "text") continue;
    const target = c.main ? mainSettings : c.advanced ? fine : general;
    let node;
    if (c.kind === "toggle") {
      const box = el("input", { type: "checkbox" });
      box.checked = !!current(c);
      box.addEventListener("change", () => setValue(c.id, box.checked));
      node = el("label", { class: "check" }, [box, document.createTextNode(c.label)]);
      if (c.hint) node.title = c.hint;
    } else {
      const format = c.kind === "float" ? (v) => String(Math.round(v * 1000) / 1000) : String;
      node = numberSetting(c.label, { ...c, value: current(c) }, (v) => setValue(c.id, v), format);
      if (c.hint) node.querySelector("label").title = c.hint;
    }
    state.controlNodes[c.id] = node;
    target.appendChild(node);
  }
  markChanged();
  show(extraPrompts, extraPrompts.children.length > 0);
  show($("mainBlock"), mainSettings.children.length > 0);
  show($("advPromptsGroup"), advPrompts.children.length > 0);
  show($("settingsGroup"), true);
  show(document.querySelector(".seed-row"), state.info.seeds.length > 0);
  show($("credits"), state.info.mode === "magnific");
  show($("finetuneGroup"), fine.children.length > 0);
  renderReferences();
}

function renderMentions() {
  const box = $("mentions");
  box.innerHTML = "";
  const refs = state.info ? state.info.references.filter((r) => r.numbered) : [];
  show(box, refs.length > 0);
  if (!refs.length) return;
  box.appendChild(el("span", { class: "muted small", text: "Mention" }));
  for (const ref of refs) {
    const chip = el("button", { class: "chip", text: ref.label, title: "Insert <" + ref.label + "> into the prompt" });
    chip.disabled = !state.references[ref.slot];
    chip.addEventListener("click", () => {
      const area = $("prompt");
      if (!area) return;
      const token = "<" + ref.label + ">";
      const start = area.selectionStart ?? area.value.length;
      const end = area.selectionEnd ?? start;
      const before = area.value.slice(0, start);
      const pad = before && !/\s$/.test(before) ? " " : "";
      area.value = before + pad + token + area.value.slice(end);
      area.dispatchEvent(new Event("input"));
      area.focus();
    });
    box.appendChild(chip);
  }
}

async function renderReferences() {
  const refs = state.info ? state.info.references : [];
  show($("referenceBlock"), refs.length > 0);
  const layers = refs.length ? await ps.layerList() : [];
  const box = $("references");
  box.innerHTML = "";
  for (const ref of refs) {
    const chosen = state.references[ref.slot];
    const select = el("select", { "aria-label": ref.label });
    select.appendChild(el("option", { value: "", text: "None" }));
    select.appendChild(el("option", { value: "file", text: "Image file…" }));
    if (chosen && chosen.kind === "file") select.appendChild(el("option", { value: "picked", text: chosen.file.name }));
    for (const layer of layers) select.appendChild(el("option", { value: "layer:" + layer.id, text: layer.name }));
    select.value = !chosen ? "" : chosen.kind === "file" ? "picked" : "layer:" + chosen.id;
    select.addEventListener("change", async () => {
      if (select.value === "file") {
        const file = await ps.pickImageFile();
        if (file) state.references[ref.slot] = { kind: "file", file };
      } else if (select.value.startsWith("layer:")) {
        state.references[ref.slot] = { kind: "layer", id: Number(select.value.slice(6)) };
      } else if (select.value === "") {
        delete state.references[ref.slot];
      }
      renderReferences();
    });

    const top = el("div", { class: "ref-top" }, [el("span", { class: "strong", text: ref.label })]);
    if (chosen) {
      top.appendChild(el("button", {
        class: "clear-ref ghost",
        html: ICONS.x,
        "aria-label": "Remove " + ref.label,
        title: "Remove",
        onclick: () => {
          delete state.references[ref.slot];
          renderReferences();
        },
      }));
    }
    box.appendChild(el("div", { class: "ref" + (chosen ? "" : " empty-slot") }, [top, select]));
  }
  renderMentions();
}

// --- generating ---

// "Edit selection", "Refine image", ...: what the button will do, given the selection.
function idleLabel() {
  const mode = state.info ? state.info.mode : settings.tab;
  const verb = mode === "magnific" ? "Edit" : MODES.find((m) => m.id === mode).label;
  return mode === "edit" ? "Edit selection" : `${verb} ${state.hasSelection ? "selection" : "image"}`;
}

// The selection decides between "selection" and "image" on the button.
async function refreshSelection() {
  try {
    const selection = await ps.selectionBounds();
    const doc = selection && (await ps.activeDocument());
    state.hasSelection = !!selection && !(selection.left <= 0 && selection.top <= 0 && selection.right >= doc.width && selection.bottom >= doc.height);
  } catch (_) {
    state.hasSelection = true;
  }
  if (!state.busy) setBusy(false);
}

function setBusy(busy, fraction = 0, text = "") {
  state.busy = busy;
  $("generate").classList.toggle("busy", busy);
  show($("cancel"), busy);
  $("bar").style.width = busy ? Math.round(fraction * 100) + "%" : "0";
  if (busy) $("generateLabel").textContent = text;
  else $("generateLabel").innerHTML = `${idleLabel()} <span class="kbd">Ctrl+Enter</span>`;
}

async function generate() {
  if (state.busy) return;
  if (!state.client || !state.template) return message("Not connected to ComfyUI: click the dot at the top right.", true);
  if (state.missing) return message(state.missing + " Then reload templates (the dot at the top right).", true);
  setBusy(true, 0, "Exporting…");
  message("");
  try {
    const doc = await ps.activeDocument();
    const selection = await ps.selectionBounds();
    const upscale = state.info.placement === "upscaled";
    const wholeDoc = { left: 0, top: 0, right: doc.width, bottom: doc.height };
    const whole = !selection || (selection.left <= 0 && selection.top <= 0 && selection.right >= doc.width && selection.bottom >= doc.height);
    if (!selection && state.info.mode === "edit") throw new Error("Make a selection around the area to edit.");

    // Remove the preview first, so it isn't exported as part of the image.
    await clearPreview();
    // An upscale takes the whole image, or exactly the selection; an edit or refine adds
    // context around the selection (a refine without one takes the whole image).
    let crop = upscale ? (whole ? wholeDoc : selection) : selection ? cropRect(selection, doc, contextFor(settings.tab) / 100) : wholeDoc;
    // Nano Banana makes a few aspect ratios: grow the crop to one, so the result fits it.
    const banana = magnificNode(state.template);
    if (banana) crop = fitRatio(crop, doc, banana.ratios);
    const tiled = willTile(state.template, crop, state.values);
    const canvas = await ps.exportCanvas(crop);
    const references = {};
    for (const [slot, ref] of Object.entries(state.references)) {
      if (!ref) continue;
      const bytes = ref.kind === "file" ? await ps.readFile(ref.file) : await ps.exportLayer(ref.id);
      references[slot] = toBase64(bytes);
    }

    const locked = $("lockSeed").getAttribute("aria-pressed") === "true";
    const seed = locked ? Number($("seed").value) : Math.floor(Math.random() * 2 ** 32);
    $("seed").value = seed;
    const prompt = build(state.template, {
      values: state.values,
      seed,
      canvas: { image: toBase64(canvas.image), mask: toBase64(canvas.mask) },
      references,
    });

    // Tiled runs take about a minute; say so, so a slow bar doesn't look stuck.
    // Magnific runs say which size they're paying for.
    const size = banana ? magnificResolution(crop, banana.resolution, banana.model) : "";
    const doing = tiled ? "Generating · tiled" : banana ? `Waiting for Magnific${size ? " · " + size : ""}` : "Generating";
    setBusy(true, 0, tiled ? "Queued · tiled, about a minute" : banana ? doing + "…" : "Queued…");
    const id = await state.client.queue(prompt);
    // Nano Banana results are larger than the crop: keep them as smart objects.
    const job = addJob(doc, crop, seed, banana ? "smart object" : !upscale ? "inpaint" : whole ? "new document" : "smart object");
    const progress = (value, max) => (banana ? `${doing} · ${value} of ${max} done` : `${doing} · step ${value} of ${max}`);
    // Nano Banana results show up one by one, before the run ends; until then they
    // preview with the plain selection as their mask.
    job.earlyMask = canvas.mask;
    const early = async (index, total, ref) => {
      try {
        addThumb(job, await state.client.view(ref));
        if (job.images.length === 1 && settings.autoPreview) preview(job, 0);
      } catch (_) {
        // the full set still comes at the end
      }
    };
    const notices = [];
    const entry = await state.client.wait(id, (f, value, max) => setBusy(true, f, max ? progress(value, max) : doing + "…"), early, (text) => notices.push(text));
    const images = await state.client.outputImages(entry, state.info.outputs);
    job.masks = await state.client.outputImages(entry, state.info.outputs, "gpc_masks");
    setBusy(false);
    if (!images.length) message("The template finished without output images.", true);
    else if (notices.length) message(notices.join("\n"), true);
    // Nano Banana batches go into Photoshop as one smart object holding every result.
    const previewing = !!state.preview && state.preview.job === job;
    const shown = previewing ? state.preview.index : 0;
    showResults(job, images);
    job.stacked = !!banana && images.length > 1;
    if (images.length && (settings.autoPreview || previewing)) await preview(job, Math.min(shown, images.length - 1), { refresh: true });
  } catch (e) {
    setBusy(false);
    message(e.message, true);
  }
}

// --- results ---

function updateEmpty() {
  show($("empty"), state.jobs.length === 0);
}

// mode: "inpaint" (preview over the crop), "smart object" (an upscaled part, kept as a
// smart object) or "new document" (an upscaled whole image, opened as its own document).
function addJob(doc, crop, seed, mode) {
  const prompt = state.info.controls.find((c) => c.kind === "text");
  const text = prompt ? String(state.values[prompt.id] ?? prompt.value) : settings.template;
  const n = state.jobs.length ? state.jobs[0].n + 1 : 1;
  // Templates without a seed (Nano Banana has none) don't show one.
  const seeded = state.info.seeds.length > 0;
  const job = { n, mode, docId: doc.id, docTitle: doc.title, resolution: doc.resolution, crop, name: `GPC ${n}: ${text.slice(0, 40)}${seeded ? ` (${seed})` : ""}`, images: [], masks: [], thumbs: [] };
  const tab = MODES.find((m) => m.id === state.info.mode).label;
  job.meta = el("span", { class: "muted small", text: `${tab} · ${seeded ? `Seed ${seed} · ` : ""}${doc.title} · generating…`, title: settings.template });
  job.strip = el("div", { class: "thumbs" });
  const title = el("div", { class: "job-title", text: text || "Untitled", title: text });
  job.box = el("div", { class: "job" }, [el("div", {}, [title, job.meta]), job.strip]);
  state.jobs.unshift(job);
  $("results").insertBefore(job.box, $("results").firstChild);
  updateEmpty();
  return job;
}

// The final results. Early ones (same order, same pixels) keep their thumbnails.
function showResults(job, images) {
  if (images.length !== job.thumbs.length) {
    job.strip.innerHTML = "";
    job.thumbs = [];
    job.images = [];
    images.forEach((buffer) => addThumb(job, buffer));
  }
  job.images = images;
  job.meta.textContent = job.meta.textContent.replace("generating…", images.length + (images.length === 1 ? " result" : " results"));
}

function addThumb(job, buffer) {
  const i = job.images.length;
  job.images.push(buffer);
  const img = el("img", { src: "data:image/png;base64," + toBase64(buffer), alt: "Result " + (i + 1), title: job.mode === "new document" ? "Open as a new document" : "Preview in the document" });
  img.addEventListener("click", () => preview(job, i));
  const keepButton = el("button", { class: "keep", html: ICONS.star, "aria-label": "Keep result " + (i + 1) + " as a layer", title: "Keep as a layer" });
  keepButton.addEventListener("click", () => keep(job, i));
  const discardButton = el("button", { html: ICONS.x, "aria-label": "Discard result " + (i + 1), title: "Discard" });
  discardButton.addEventListener("click", () => discard(job, i));
  const thumb = el("div", { class: "thumb" }, [
    el("div", { class: "frame" }, [img]),
    el("span", { class: "tag", text: "Preview" }),
    el("div", { class: "acts" }, [keepButton, discardButton]),
  ]);
  job.thumbs.push(thumb);
  job.strip.appendChild(thumb);
}

// The mask a result previews with: its own, or before the run ends the selection.
const maskFor = (job, index) => job.masks[index] || job.earlyMask || null;

const isPreviewed = (job, index) => !!state.preview && state.preview.job === job && state.preview.index === index;
const finalName = (job, index) => `${job.name} #${index + 1}`;

function markPreview() {
  for (const job of state.jobs) job.thumbs.forEach((t, i) => t.classList.toggle("previewing", isPreviewed(job, i)));
}

// Opens an upscaled whole image as its own document.
function openResult(job, index) {
  return inPhotoshop(async () => {
    try {
      const base = job.docTitle.replace(/\.[^.]+$/, "");
      await ps.openAsDocument(job.images[index], `${base} upscaled ${job.n}-${index + 1}`, job.resolution);
      job.thumbs[index].classList.add("kept");
    } catch (e) {
      message(e.message, true);
    }
  });
}

// Places a stacked job: one smart object holding every result, `index` showing.
async function placeStack(job, index, name, replaceId = 0) {
  const placed = await ps.place(job.images[0], { docId: job.docId, crop: job.crop, resolution: job.resolution, name, replaceId });
  return ps.stack(job.docId, placed, job.images.slice(1), index, { crop: job.crop, resolution: job.resolution, mask: maskFor(job, 0) });
}

// Shows a result as the temporary preview layer, replacing the previous one.
// Clicking the result already previewed hides it again. A stacked job's preview
// is its smart object: clicking a result shows that one inside it. `refresh`
// places it again (the run ended: final masks, and the stack).
function preview(job, index, { refresh = false } = {}) {
  if (job.mode === "new document") return openResult(job, index);
  return inPhotoshop(async () => {
    try {
      const current = state.preview;
      const own = !!current && current.job === job;
      if (!refresh && own && current.stack) {
        if (current.index === index) {
          state.preview = null;
          await ps.removeLayer(current.docId, current.layerId);
        } else {
          await ps.stackShow(job.docId, current.layerId, index);
          current.index = index;
        }
      } else if (!refresh && isPreviewed(job, index)) {
        state.preview = null;
        await ps.removeLayer(current.docId, current.layerId);
      } else {
        const replaceId = current && current.docId === job.docId ? current.layerId : 0;
        if (current && !replaceId) await ps.removeLayer(current.docId, current.layerId);
        state.preview = null;
        const layerId = job.stacked
          ? await placeStack(job, index, PREVIEW_NAME, replaceId)
          : await ps.place(job.images[index], { docId: job.docId, crop: job.crop, resolution: job.resolution, name: PREVIEW_NAME, replaceId, mask: maskFor(job, index) });
        state.preview = { job, index, layerId, docId: job.docId, stack: !!job.stacked };
      }
    } catch (e) {
      message(e.message, true);
    }
    markPreview();
  });
}

// Keeps a result as an ordinary layer (an upscaled part stays a smart object):
// the preview itself when it's showing, else a new one. A stacked job is kept
// whole, showing the result whose ★ was clicked.
function keep(job, index) {
  if (job.mode === "new document") return openResult(job, index);
  if (job.stacked) return keepStack(job, index);
  return inPhotoshop(async () => {
    try {
      let layerId;
      if (isPreviewed(job, index)) {
        layerId = state.preview.layerId;
        state.preview = null;
      } else {
        layerId = await ps.place(job.images[index], { docId: job.docId, crop: job.crop, resolution: job.resolution, name: finalName(job, index), mask: maskFor(job, index) });
      }
      await ps.bake(job.docId, layerId, finalName(job, index), job.mode === "smart object");
      job.thumbs[index].classList.add("kept");
    } catch (e) {
      message(e.message, true);
    }
    markPreview();
  });
}

function keepStack(job, index) {
  return inPhotoshop(async () => {
    try {
      let layerId;
      const current = state.preview;
      if (current && current.job === job && current.stack) {
        layerId = current.layerId;
        state.preview = null;
        if (current.index !== index) await ps.stackShow(job.docId, layerId, index);
      } else {
        layerId = await placeStack(job, index, job.name);
      }
      await ps.bake(job.docId, layerId, job.name, true);
      job.thumbs.forEach((t) => t.classList.add("kept"));
    } catch (e) {
      message(e.message, true);
    }
    markPreview();
  });
}

// Drops one result from the panel (and its preview, if showing).
// A stack keeps every result inside; discarding one only hides its thumbnail.
async function discard(job, index) {
  if (isPreviewed(job, index) && !job.stacked) await clearPreview();
  job.thumbs[index].classList.add("hidden");
  if (job.thumbs.every((t) => t.classList.contains("hidden"))) {
    job.box.remove();
    state.jobs = state.jobs.filter((j) => j !== job);
    updateEmpty();
  }
}

function clearPreview() {
  return inPhotoshop(async () => {
    const current = state.preview;
    state.preview = null;
    if (current) await ps.removeLayer(current.docId, current.layerId).catch(() => {});
    markPreview();
  });
}

// Forgets all results (kept layers stay in the document).
async function clearResults() {
  await clearPreview();
  state.jobs = [];
  $("results").innerHTML = "";
  updateEmpty();
}

// --- wiring ---

applyTheme();
try {
  window.__adobe_cep__.addEventListener("com.adobe.csxs.events.ThemeColorChanged", applyTheme);
} catch (_) {
  // older hosts: the theme is read once
}

$("server").value = settings.server;
$("autoPreview").checked = settings.autoPreview;
renderContext();
$("creditsLink").addEventListener("click", () => window.cep.util.openURLInDefaultBrowser(MAGNIFIC_CREDITS));
$("connect").addEventListener("click", connect);
$("statusButton").addEventListener("click", () => showConnection($("connection").classList.contains("hidden")));
$("reload").addEventListener("click", async () => {
  if (!state.client) return connect();
  try {
    await loadCatalog(await state.client.templates());
  } catch (e) {
    message("Reloading templates failed: " + e.message, true);
  }
});
$("template").addEventListener("change", () => chooseTemplate($("template").value));
$("reset").addEventListener("click", () => state.info && resetValues());
$("generate").addEventListener("click", generate);
$("cancel").addEventListener("click", () => state.client && state.client.interrupt().catch(() => {}));
$("lockSeed").addEventListener("click", () => {
  const on = $("lockSeed").getAttribute("aria-pressed") !== "true";
  $("lockSeed").setAttribute("aria-pressed", String(on));
});
$("autoPreview").addEventListener("change", () => {
  settings.autoPreview = $("autoPreview").checked;
  save();
});
$("clear").addEventListener("click", clearResults);
$("toggleAdvanced").addEventListener("click", () => {
  const open = $("advanced").classList.contains("hidden");
  show($("advanced"), open);
  $("toggleAdvanced").setAttribute("aria-expanded", String(open));
});
// Layer pickers go stale when the document changes; refresh them on focus.
// So does the button's "selection" / "image".
document.body.addEventListener("mouseenter", () => {
  if (state.info) renderReferences();
  refreshSelection();
});

updateEmpty();
connect();
