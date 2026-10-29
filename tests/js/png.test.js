const test = require("node:test");
const assert = require("node:assert");
const zlib = require("node:zlib");
const { setResolution, chunks, crc32 } = require("../../photoshop/src/png.js");

// A valid 1x1 RGBA PNG.
function tinyPng(extra = []) {
  const chunk = (type, data) => {
    const head = Buffer.alloc(8);
    head.writeUInt32BE(data.length, 0);
    head.write(type, 4, "ascii");
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(Buffer.concat([head.subarray(4), data])), 0);
    return Buffer.concat([head, data, crc]);
  };
  const ihdr = Buffer.from([0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0]);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    ...extra.map(([t, d]) => chunk(t, d)),
    chunk("IDAT", zlib.deflateSync(Buffer.from([0, 1, 2, 3, 4]))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

test("crc32 matches zlib", () => {
  for (const s of ["", "IEND", "pHYs\u0000\u0000"]) assert.strictEqual(crc32(Buffer.from(s)), zlib.crc32(Buffer.from(s)));
});

test("setResolution adds one valid pHYs after IHDR, replacing any old one", () => {
  const old = Buffer.alloc(9);
  const out = setResolution(tinyPng([["pHYs", old]]), 300);
  const list = chunks(out);
  assert.deepStrictEqual(list.map((c) => c.type), ["IHDR", "pHYs", "IDAT", "IEND"]);
  const phys = out.subarray(list[1].start, list[1].end);
  assert.strictEqual(phys.readUInt32BE(8), 11811); // 300 ppi in pixels per meter
  assert.strictEqual(phys[16], 1);
  assert.strictEqual(phys.readUInt32BE(17), zlib.crc32(phys.subarray(4, 17)));
});

test("visibleBounds matches PIL's alpha bounding box", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const { visibleBounds } = require("../../photoshop/src/png.js");
  const dir = path.join(__dirname, "fixtures");
  const expected = JSON.parse(fs.readFileSync(path.join(dir, "visible_bounds.json"), "utf8"));
  for (const [name, [left, top, right, bottom]] of Object.entries(expected)) {
    assert.deepStrictEqual(visibleBounds(fs.readFileSync(path.join(dir, name + ".png"))), { left, top, right, bottom }, name);
  }
});
