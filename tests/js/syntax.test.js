// Every panel script must at least parse: one stray character and the panel
// loads blank in Photoshop, with nothing to say why.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const panel = path.join(__dirname, "../../photoshop");
const scripts = ["index.js", ...fs.readdirSync(path.join(panel, "src")).filter((f) => f.endsWith(".js")).map((f) => "src/" + f)];

for (const file of scripts) {
  test(`${file} parses`, () => {
    const source = fs.readFileSync(path.join(panel, file), "utf8");
    assert.doesNotThrow(() => new vm.Script(`(function () {\n${source}\n})`, { filename: file }));
  });
}
