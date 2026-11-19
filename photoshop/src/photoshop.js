// Panel side of everything that touches the document. The work happens in
// host/photoshop.jsx (ExtendScript); pixels go back and forth as temporary PNG
// files, which this side reads and writes with Node.

const fs = require("fs");
const os = require("os");
const path = require("path");
const { setResolution, visibleBounds } = require("./png.js");

const TEMP = path.join(os.tmpdir(), "gpc_photoshop");
fs.mkdirSync(TEMP, { recursive: true });

// Calls a host function with JSON-encodable arguments. Resolves to its parsed result.
function host(fn, ...args) {
  const call = `${fn}(${args.map((a) => JSON.stringify(a)).join(",")})`;
  return new Promise((resolve, reject) => {
    window.__adobe_cep__.evalScript(call, (result) => {
      if (typeof result !== "string" || result === "EvalScript error.") {
        reject(new Error(`Photoshop script failed: ${fn}. Is host/photoshop.jsx loaded?`));
      } else if (result.startsWith("ERROR: ")) {
        reject(new Error(result.slice(7)));
      } else {
        resolve(JSON.parse(result));
      }
    });
  });
}

const temp = (name) => path.join(TEMP, name);

function activeDocument() {
  return host("gpcDocInfo");
}

function selectionBounds() {
  return host("gpcSelectionBounds");
}

function layerList() {
  return host("gpcLayers").catch(() => []);
}

// The visible image inside `crop` and the selection as a mask. Resolves to { image, mask } Buffers.
async function exportCanvas(crop) {
  const image = temp("canvas.png");
  const mask = temp("mask.png");
  await host("gpcExportCanvas", crop.left, crop.top, crop.right, crop.bottom, image, mask);
  return { image: fs.readFileSync(image), mask: fs.readFileSync(mask) };
}

async function exportLayer(layerId, maxPixels = 1024 * 1024) {
  const file = temp("reference.png");
  await host("gpcExportLayer", layerId, file, maxPixels);
  return fs.readFileSync(file);
}

let resultCount = 0;

// Places a result PNG in document `docId` over `crop`, as a smart object,
// without opening it as a document. A result larger than the crop (an upscale)
// is scaled to fit it, keeping its full-size pixels inside the smart object.
// Removes layer `replaceId` first (the previous preview). With `mask` (a grayscale
// PNG), it becomes the layer's mask over the crop. Resolves to the new layer's id.
async function place(buffer, { docId, crop, resolution, name, replaceId = 0, mask = null }) {
  const width = Buffer.from(buffer).readUInt32BE(16);
  const scale = (crop.right - crop.left) / width; // 1 for an inpaint result
  // A higher resolution makes Place land the image at the crop's size.
  const png = setResolution(Buffer.from(buffer), (resolution || 72) / scale);
  const v = visibleBounds(png);
  const file = temp(`result_${++resultCount}.png`);
  fs.writeFileSync(file, png);
  const maskFile = mask ? temp(`result_${resultCount}_mask.png`) : null;
  if (mask) fs.writeFileSync(maskFile, Buffer.from(mask));
  try {
    const vis = [v.left, v.top, v.right, v.bottom].map((n) => n * scale);
    const maskArgs = mask ? [maskFile, crop.right - crop.left, crop.bottom - crop.top] : [];
    return await host("gpcPlace", file, docId, crop.left, crop.top, vis, name, replaceId, ...maskArgs);
  } finally {
    fs.unlink(file, () => {});
    if (maskFile) fs.unlink(maskFile, () => {});
  }
}

// Turns placed result `layerId` (placed without its mask) into one smart object
// holding it and `buffers` (results the same size), result `show` (0 = the placed
// one) visible, then adds `mask` over `crop`. Resolves to the stack's layer id.
async function stack(docId, layerId, buffers, show, { crop, resolution, mask = null }) {
  const files = buffers.map((buffer, i) => {
    const width = Buffer.from(buffer).readUInt32BE(16);
    const scale = (crop.right - crop.left) / width;
    const file = temp(`stack_${++resultCount}_${i}.png`);
    // Same as place(): Place lands it at the crop's size, keeping its pixels.
    fs.writeFileSync(file, setResolution(Buffer.from(buffer), (resolution || 72) / scale));
    return file;
  });
  const maskFile = mask ? temp(`stack_${resultCount}_mask.png`) : null;
  if (mask) fs.writeFileSync(maskFile, Buffer.from(mask));
  try {
    const maskArgs = mask ? [maskFile, crop.left, crop.top, crop.right - crop.left, crop.bottom - crop.top] : [];
    return await host("gpcStack", docId, layerId, files, show, ...maskArgs);
  } finally {
    for (const file of [...files, maskFile]) if (file) fs.unlink(file, () => {});
  }
}

// Shows result `index` inside a stacked smart object, hiding the others.
function stackShow(docId, layerId, index) {
  return host("gpcStackShow", docId, layerId, index);
}

// Keeps a placed result under its final name: rasterized, or as a smart object with `keepSmart`.
function bake(docId, layerId, name, keepSmart = false) {
  return host("gpcBake", docId, layerId, name, keepSmart);
}

// Opens a result as a new document. Resolves to its id.
async function openAsDocument(buffer, name, resolution) {
  const file = temp(`result_${++resultCount}.png`);
  fs.writeFileSync(file, Buffer.from(buffer));
  try {
    return await host("gpcOpenAsDocument", file, name, resolution || 72);
  } finally {
    fs.unlink(file, () => {});
  }
}

function removeLayer(docId, layerId) {
  return host("gpcRemoveLayer", docId, layerId);
}

function readFile(file) {
  return fs.promises.readFile(file.path);
}

// Resolves to { name, path }, or null when cancelled.
async function pickImageFile() {
  const result = window.cep.fs.showOpenDialogEx(false, false, "Choose a reference image", null, ["png", "jpg", "jpeg", "webp"]);
  const picked = result && result.data && result.data[0];
  return picked ? { name: path.basename(picked), path: picked } : null;
}

module.exports = {
  activeDocument,
  selectionBounds,
  layerList,
  exportCanvas,
  exportLayer,
  place,
  stack,
  stackShow,
  bake,
  openAsDocument,
  removeLayer,
  readFile,
  pickImageFile,
};
