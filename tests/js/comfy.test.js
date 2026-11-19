const test = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const { ComfyClient, formatError } = require("../../photoshop/src/comfy.js");

// A fake ComfyUI: one prompt that finishes on the second history poll.
function fakeServer() {
  let polls = 0;
  let queued = null;
  const server = http.createServer((req, res) => {
    const send = (code, body, type = "application/json") => {
      res.writeHead(code, { "Content-Type": type });
      res.end(type === "application/json" ? JSON.stringify(body) : body);
    };
    if (req.url === "/system_stats") return send(200, {});
    if (req.url === "/gpc_ps/templates") return send(200, ["a"]);
    if (req.url === "/gpc_ps/check/a") return send(200, { missing: ["INPAINT_ColorMatch"], message: "Install it" });
    if (req.url === "/prompt") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        queued = JSON.parse(body);
        if (queued.prompt.missingPack) return send(400, { error: { type: "missing_node_type", message: "Node 'GPC_PS_Canvas' not found. The custom node may not be installed." }, node_errors: {} });
        if (queued.prompt.bad) return send(400, { error: { message: "Prompt outputs failed validation" }, node_errors: { 7: { class_type: "X", errors: [{ details: "bad input" }] } } });
        send(200, { prompt_id: "p1" });
      });
      return;
    }
    if (req.url === "/history/p1") {
      polls++;
      if (polls < 2) return send(200, {});
      return send(200, { p1: { status: { completed: true, status_str: "success" }, outputs: { 9: { images: [{ filename: "r.png", subfolder: "gpc_photoshop", type: "temp" }] } } } });
    }
    if (req.url === "/view?filename=r.png&subfolder=gpc_photoshop&type=temp") return send(200, Buffer.from([1, 2, 3]), "image/png");
    send(404, { error: "nope" });
  });
  return new Promise((resolve) => server.listen(0, () => resolve({ server, url: `http://127.0.0.1:${server.address().port}/`, queued: () => queued })));
}

test("queue, wait and fetch output images", async () => {
  const { server, url, queued } = await fakeServer();
  try {
    const client = new ComfyClient(url);
    assert.deepStrictEqual(await client.check(), ["a"]);
    assert.deepStrictEqual(await client.checkTemplate("a"), { missing: ["INPAINT_ColorMatch"], message: "Install it" });
    assert.strictEqual(await client.checkTemplate("old-server"), null); // 404: no check route
    const id = await client.queue({ 1: {} });
    assert.strictEqual(id, "p1");
    assert.strictEqual(queued().client_id, client.clientId);
    const entry = await client.wait(id);
    const images = await client.outputImages(entry, ["9"]);
    assert.deepStrictEqual([...new Uint8Array(images[0])], [1, 2, 3]);
  } finally {
    server.close();
  }
});

test("validation errors are readable", async () => {
  const { server, url } = await fakeServer();
  try {
    await assert.rejects(new ComfyClient(url).queue({ bad: true }), /400 Prompt outputs failed validation\nX #7: bad input/);
  } finally {
    server.close();
  }
});

test("a server without this pack says how to install it", async () => {
  const { server, url } = await fakeServer();
  try {
    await assert.rejects(new ComfyClient(url).queue({ missingPack: true }), /Clone https:\/\/github\.com\/gprzzzz\/ComfyUI_GPC_Photoshop/);
  } finally {
    server.close();
  }
});

test("formatError tolerates missing fields", () => {
  assert.strictEqual(formatError({}), "");
  assert.strictEqual(formatError({ error: "plain" }), "plain");
});

test("check() says why templates couldn't be listed", async () => {
  const statusFor = { "/gpc_ps/templates": 404 };
  const server = http.createServer((req, res) => {
    res.writeHead(req.url === "/system_stats" ? 200 : statusFor[req.url], { "Content-Type": "application/json" });
    res.end(req.url === "/system_stats" ? "{}" : JSON.stringify({ error: "boom" }));
  });
  await new Promise((resolve) => server.listen(0, resolve));
  const client = new ComfyClient(`http://127.0.0.1:${server.address().port}`);
  try {
    await assert.rejects(client.check(), /doesn't have ComfyUI_GPC_Photoshop loaded\. Clone https:\/\/github\.com\/gprzzzz\/ComfyUI_GPC_Photoshop/);
    statusFor["/gpc_ps/templates"] = 500;
    await assert.rejects(client.check(), /listing templates failed: 500 boom/);
  } finally {
    server.close();
  }
});

// A ComfyUI that accepts a prompt and then never finishes it.
function stuckServer() {
  const seen = [];
  const server = http.createServer((req, res) => {
    const send = (code, body) => {
      res.writeHead(code, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.url === "/prompt") return send(200, { prompt_id: "p9" });
    if (req.url === "/history/p9") return send(200, {});
    if (req.url === "/queue" || req.url === "/interrupt") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        seen.push({ url: req.url, body: JSON.parse(body) });
        send(200, {});
      });
      return;
    }
    send(404, {});
  });
  return new Promise((resolve) => server.listen(0, () => resolve({ server, url: `http://127.0.0.1:${server.address().port}/`, seen })));
}

async function until(fn, ms = 2000) {
  const started = Date.now();
  while (!fn()) {
    if (Date.now() - started > ms) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 10));
  }
}

test("cancel frees the panel without waiting on the server", async () => {
  const { server, url, seen } = await stuckServer();
  try {
    const client = new ComfyClient(url);
    const id = await client.queue({ 1: {} });
    const waiting = client.wait(id);
    const started = Date.now();
    client.cancel(id);
    await assert.rejects(waiting, (e) => e.cancelled === true && e.message === "Stopped");
    assert.ok(Date.now() - started < 500, `cancel took ${Date.now() - started}ms; it must not wait for the server`);
    await until(() => seen.length >= 2);
    const sent = Object.fromEntries(seen.map((s) => [s.url, s.body]));
    // Deleting reaches a pending prompt; interrupting reaches a running one. Both are sent:
    // the panel doesn't know yet which one this is.
    assert.deepStrictEqual(sent["/queue"], { delete: ["p9"] });
    assert.deepStrictEqual(sent["/interrupt"], { prompt_id: "p9" });
  } finally {
    server.close();
  }
});

test("where() reads ComfyUI's queue, and knows when there's no answer", async () => {
  let body = { queue_running: [], queue_pending: [] };
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  });
  const url = await new Promise((resolve) => server.listen(0, () => resolve(`http://127.0.0.1:${server.address().port}/`)));
  const client = new ComfyClient(url);
  body = { queue_running: [[1, "p1"]], queue_pending: [] };
  assert.deepStrictEqual(await client.where("p1"), { state: "running" });
  body = { queue_running: [], queue_pending: [[2, "someone-else"], [3, "p1"]] };
  assert.deepStrictEqual(await client.where("p1"), { state: "pending", ahead: 1 });
  body = { queue_running: [], queue_pending: [] };
  assert.deepStrictEqual(await client.where("p1"), { state: "gone" });
  // A payload we don't recognize must never read as "gone": that would unlock the
  // panel while ComfyUI is still busy.
  body = {};
  assert.deepStrictEqual(await client.where("p1"), { state: "unknown" });
  await new Promise((resolve) => server.close(resolve));
  assert.deepStrictEqual(await client.where("p1"), { state: "unknown" });
});

test("a run interrupted from ComfyUI reads as cancelled, not failed", async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ p2: { status: { status_str: "error", completed: false, messages: [["execution_start", {}], ["execution_interrupted", {}]] }, outputs: {} } }));
  });
  const url = await new Promise((resolve) => server.listen(0, () => resolve(`http://127.0.0.1:${server.address().port}/`)));
  try {
    await assert.rejects(new ComfyClient(url).wait("p2"), /^Error: Cancelled$/);
  } finally {
    server.close();
  }
});
