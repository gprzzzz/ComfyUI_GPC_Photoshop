// HTTP and WebSocket through Node instead of the panel's browser engine.
//
// The browser marks the panel's requests as cross-site (it's a local page
// talking to 127.0.0.1), and ComfyUI answers those with 403 Forbidden unless
// it runs with --enable-cors-header. Node adds no such headers.

const http = require("http");
const https = require("https");
const crypto = require("crypto");

// Node's own URL: in the panel the global URL is the browser's, which
// http.request doesn't recognize. Options are passed as a plain object too.
const { URL } = require("url");

const transport = (url) => (url.protocol === "https:" ? https : http);
const target = (url, extra) => ({
  protocol: url.protocol,
  hostname: url.hostname,
  port: url.port || undefined,
  path: url.pathname + url.search,
  ...extra,
});

// A fetch-like request. Resolves to { ok, status, statusText, json(), text(), arrayBuffer() }.
function request(href, { method = "GET", headers = {}, body } = {}) {
  const url = new URL(href);
  return new Promise((resolve, reject) => {
    const req = transport(url).request(target(url, { method, headers }), (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const data = Buffer.concat(chunks);
        resolve({
          ok: res.statusCode >= 200 && res.statusCode < 300,
          status: res.statusCode,
          statusText: res.statusMessage || "",
          text: async () => data.toString("utf8"),
          json: async () => JSON.parse(data.toString("utf8")),
          arrayBuffer: async () => data.buffer.slice(data.byteOffset, data.byteOffset + data.length),
        });
      });
      res.on("error", reject);
    });
    req.on("error", (e) => reject(new Error(`Can't reach ${url.origin}: ${e.code || e.message}`)));
    if (body !== undefined) req.write(body);
    req.end();
  });
}

// A minimal WebSocket client: text messages in, pings answered. Binary
// messages (ComfyUI's live previews) are skipped. Returns { close() }.
function openSocket(href, { onText, onClose = () => {} }) {
  const url = new URL(href.replace(/^ws/, "http"));
  const key = crypto.randomBytes(16).toString("base64");
  let socket = null;
  let closed = false;
  const finish = () => {
    if (!closed) {
      closed = true;
      onClose();
    }
  };

  const req = transport(url).request(target(url, {
    headers: { Connection: "Upgrade", Upgrade: "websocket", "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": key },
  }));
  req.on("upgrade", (res, sock, head) => {
    socket = sock;
    let buffer = head;
    let parts = [];
    sock.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      let frame;
      while ((frame = readFrame(buffer))) {
        buffer = buffer.subarray(frame.size);
        if (frame.opcode === 0x8) return sock.end();
        if (frame.opcode === 0x9) sock.write(encodeFrame(0xa, frame.payload));
        if (frame.opcode === 0x1 || (frame.opcode === 0x0 && parts.text)) {
          parts.push(frame.payload);
          parts.text = true;
        } else if (frame.opcode === 0x2) {
          parts = [];
        }
        if (frame.fin && parts.text) {
          const text = Buffer.concat(parts).toString("utf8");
          parts = [];
          onText(text);
        }
      }
    });
    sock.on("close", finish);
    sock.on("error", finish);
  });
  req.on("response", (res) => {
    res.resume();
    finish(); // the server refused the upgrade
  });
  req.on("error", finish);
  req.end();

  return {
    close() {
      if (socket) {
        socket.end(encodeFrame(0x8, Buffer.alloc(0)));
        setTimeout(() => socket.destroy(), 1000).unref(); // don't wait on a server that never closes
      } else {
        req.destroy();
      }
      finish();
    },
  };
}

// One frame from the start of `buf`, or null when it isn't all there yet.
function readFrame(buf) {
  if (buf.length < 2) return null;
  const fin = (buf[0] & 0x80) !== 0;
  const opcode = buf[0] & 0x0f;
  const masked = (buf[1] & 0x80) !== 0;
  let length = buf[1] & 0x7f;
  let offset = 2;
  if (length === 126) {
    if (buf.length < 4) return null;
    length = buf.readUInt16BE(2);
    offset = 4;
  } else if (length === 127) {
    if (buf.length < 10) return null;
    length = Number(buf.readBigUInt64BE(2));
    offset = 10;
  }
  const mask = masked ? buf.subarray(offset, offset + 4) : null;
  if (masked) offset += 4;
  if (buf.length < offset + length) return null;
  let payload = buf.subarray(offset, offset + length);
  if (mask) payload = Buffer.from(payload.map((b, i) => b ^ mask[i % 4]));
  return { fin, opcode, payload, size: offset + length };
}

// A client frame; clients must mask what they send.
function encodeFrame(opcode, payload) {
  const mask = crypto.randomBytes(4);
  const n = payload.length;
  const header = n < 126 ? Buffer.from([0x80 | opcode, 0x80 | n]) : Buffer.from([0x80 | opcode, 0x80 | 126, n >> 8, n & 255]);
  const body = Buffer.from(payload.map((b, i) => b ^ mask[i % 4]));
  return Buffer.concat([header, mask, body]);
}

module.exports = { request, openSocket, readFrame, encodeFrame };
