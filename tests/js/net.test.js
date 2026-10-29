const test = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const crypto = require("node:crypto");
const { request, openSocket, readFrame, encodeFrame } = require("../../photoshop/src/net.js");

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(`http://127.0.0.1:${server.address().port}`)));
}

// A server frame (unmasked), for the fake ComfyUI below.
function serverFrame(opcode, payload, fin = true) {
  const n = payload.length;
  const len = n < 126 ? Buffer.from([n]) : n < 65536 ? Buffer.from([126, n >> 8, n & 255]) : Buffer.concat([Buffer.from([127]), Buffer.alloc(8)]);
  if (n >= 65536) len.writeBigUInt64BE(BigInt(n), 1);
  return Buffer.concat([Buffer.from([(fin ? 0x80 : 0) | opcode]), len, payload]);
}

test("requests carry none of the headers ComfyUI's origin check rejects", async () => {
  let seen;
  const server = http.createServer((req, res) => {
    seen = req.headers;
    res.end(JSON.stringify({ ok: 1 }));
  });
  const url = await listen(server);
  try {
    const res = await request(url + "/system_stats", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    assert.strictEqual(res.ok, true);
    assert.deepStrictEqual(await res.json(), { ok: 1 });
    assert.strictEqual(seen.origin, undefined);
    assert.strictEqual(seen["sec-fetch-site"], undefined);
    assert.strictEqual(seen.host, url.slice(7));
  } finally {
    server.close();
  }
});

test("unreachable servers give a readable error", async () => {
  await assert.rejects(request("http://127.0.0.1:1/x"), /Can't reach http:\/\/127\.0\.0\.1:1: ECONNREFUSED/);
});

test("the socket reads text across chunks, skips binary, answers pings", async () => {
  let pong;
  const server = http.createServer();
  let serverSock;
  server.on("upgrade", (req, sock) => {
    serverSock = sock;
    const accept = crypto.createHash("sha1").update(req.headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
    sock.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    sock.on("data", (d) => {
      const f = readFrame(d);
      if (f && f.opcode === 0xa) pong = f.payload.toString();
    });
    const big = JSON.stringify({ type: "progress", data: { value: 1, max: 2, pad: "x".repeat(70000) } });
    const frames = Buffer.concat([
      serverFrame(0x2, Buffer.alloc(300)), // a preview image
      serverFrame(0x9, Buffer.from("hi")),
      serverFrame(0x1, Buffer.from('{"type":"sta'), false),
      serverFrame(0x0, Buffer.from('tus"}')),
      serverFrame(0x1, Buffer.from(big)),
    ]);
    // split mid-frame to exercise buffering
    sock.write(frames.subarray(0, 333));
    setTimeout(() => sock.write(frames.subarray(333)), 20);
  });
  const url = await listen(server);
  try {
    const messages = [];
    const got = new Promise((resolve) => {
      const ws = openSocket(url.replace("http", "ws") + "/ws?clientId=a", {
        onText: (t) => {
          messages.push(JSON.parse(t).type);
          if (messages.length === 2) setTimeout(() => (ws.close(), resolve()), 20);
        },
      });
    });
    await got;
    assert.deepStrictEqual(messages, ["status", "progress"]);
    assert.strictEqual(pong, "hi");
  } finally {
    serverSock.destroy();
    server.close();
  }
});

test("a refused upgrade just closes", async () => {
  const server = http.createServer((req, res) => {
    res.statusCode = 403;
    res.end();
  });
  const url = await listen(server);
  try {
    await new Promise((resolve) => openSocket(url.replace("http", "ws") + "/ws", { onText: () => {}, onClose: resolve }));
  } finally {
    server.close();
  }
});

test("client frames are masked and decode back", () => {
  const f = readFrame(encodeFrame(0x1, Buffer.from("hello")));
  assert.strictEqual(f.payload.toString(), "hello");
  assert.strictEqual(f.fin, true);
});

// Photoshop 2022's panel runs an older Node whose http.request only takes its
// own URL class, and the panel's global URL is the browser's. Passing that one
// made Node read the options as the callback ("listener" must be a function).
// So net.js must call request(plainOptions, callback), and nothing else.
test("http.request gets plain options and a callback, never a URL object", async () => {
  const calls = [];
  const original = http.request;
  http.request = (...args) => {
    calls.push(args);
    return original(...args);
  };
  const server = http.createServer((req, res) => res.end(req.url));
  const url = await listen(server);
  try {
    const res = await request(url + "/view?filename=a.png");
    assert.strictEqual(await res.text(), "/view?filename=a.png");
    await new Promise((resolve) => openSocket(url.replace("http", "ws") + "/ws", { onText: () => {}, onClose: resolve }));
    assert.strictEqual(calls.length, 2);
    for (const args of calls) {
      assert.strictEqual(Object.getPrototypeOf(args[0]), Object.prototype);
      assert.ok(args.length === 1 || typeof args[1] === "function");
    }
  } finally {
    http.request = original;
    server.close();
  }
});
