// Small PNG edits done before handing a result to Photoshop.

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, crc]);
}

// The PNG's chunks as { type, start, end } byte ranges.
function chunks(png) {
  if (!png.subarray(0, 8).equals(SIGNATURE)) throw new Error("Not a PNG");
  const out = [];
  for (let at = 8; at + 8 <= png.length; ) {
    const length = png.readUInt32BE(at);
    const type = png.toString("ascii", at + 4, at + 8);
    out.push({ type, start: at, end: at + 12 + length });
    at += 12 + length;
  }
  return out;
}

// Sets the PNG's resolution, so Photoshop's Place keeps it at 1 image pixel per document pixel.
function setResolution(buffer, ppi) {
  const png = Buffer.from(buffer);
  const data = Buffer.alloc(9);
  const ppm = Math.round(ppi / 0.0254);
  data.writeUInt32BE(ppm, 0);
  data.writeUInt32BE(ppm, 4);
  data[8] = 1; // meters
  const parts = [SIGNATURE];
  for (const c of chunks(png)) {
    if (c.type === "pHYs") continue;
    parts.push(png.subarray(c.start, c.end));
    if (c.type === "IHDR") parts.push(chunk("pHYs", data));
  }
  return Buffer.concat(parts);
}

const CHANNELS = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }; // by PNG color type

// The box of pixels that aren't fully transparent, as Photoshop measures a
// layer: { left, top, right, bottom } in image pixels. The whole image when it
// has no alpha channel (or nothing is visible).
function visibleBounds(buffer) {
  const png = Buffer.from(buffer);
  const list = chunks(png);
  const ihdr = list.find((c) => c.type === "IHDR");
  const width = png.readUInt32BE(ihdr.start + 8);
  const height = png.readUInt32BE(ihdr.start + 12);
  const depth = png[ihdr.start + 16];
  const colorType = png[ihdr.start + 17];
  const interlaced = png[ihdr.start + 20] !== 0;
  const whole = { left: 0, top: 0, right: width, bottom: height };
  if ((colorType !== 4 && colorType !== 6) || interlaced) return whole;

  const zlib = require("zlib");
  const data = zlib.inflateSync(Buffer.concat(list.filter((c) => c.type === "IDAT").map((c) => png.subarray(c.start + 8, c.end - 4))));
  const bytes = depth / 8;
  const bpp = CHANNELS[colorType] * bytes; // bytes per pixel
  const stride = width * bpp;
  const alphaAt = bpp - bytes; // first byte of the alpha sample
  let prev = Buffer.alloc(stride);
  let left = width, top = height, right = 0, bottom = 0;
  for (let y = 0; y < height; y++) {
    const filter = data[y * (stride + 1)];
    const row = Buffer.from(data.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)));
    unfilter(filter, row, prev, bpp);
    for (let x = 0; x < width; x++) {
      if (row[x * bpp + alphaAt] || (bytes === 2 && row[x * bpp + alphaAt + 1])) {
        if (x < left) left = x;
        if (x >= right) right = x + 1;
        if (y < top) top = y;
        bottom = y + 1;
      }
    }
    prev = row;
  }
  return right > left ? { left, top, right, bottom } : whole;
}

function unfilter(filter, row, prev, bpp) {
  for (let i = 0; i < row.length; i++) {
    const a = i >= bpp ? row[i - bpp] : 0;
    const b = prev[i];
    const c = i >= bpp ? prev[i - bpp] : 0;
    let add = 0;
    if (filter === 1) add = a;
    else if (filter === 2) add = b;
    else if (filter === 3) add = (a + b) >> 1;
    else if (filter === 4) {
      const p = a + b - c;
      const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      add = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
    }
    row[i] = (row[i] + add) & 0xff;
  }
}

module.exports = { setResolution, visibleBounds, chunks, crc32 };
