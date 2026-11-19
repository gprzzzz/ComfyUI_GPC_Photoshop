// A small ComfyUI client: queue a prompt, follow its progress, fetch its images.

const net = require("./net.js");

const NOT_INSTALLED =
  "This ComfyUI doesn't have ComfyUI_GPC_Photoshop loaded. Clone https://github.com/gprzzzz/ComfyUI_GPC_Photoshop " +
  "into its custom_nodes folder (or a custom_nodes folder in its extra_model_paths.yaml) and restart it. " +
  "Already there? Check its startup log for an import error.";

class ComfyClient {
  constructor(url) {
    this.url = url.replace(/\/+$/, "");
    this.clientId = "gpc-ps-" + Math.random().toString(36).slice(2, 10);
    this.socket = null;
    this.listeners = new Set();
    // The run being followed: { promptId, stop() }. One at a time.
    this.pending = null;
  }

  async request(path, options = {}) {
    const res = await net.request(this.url + path, options);
    if (!res.ok) {
      let detail = "";
      try {
        detail = formatError(await res.json());
      } catch (_) {
        detail = res.statusText;
      }
      throw new Error(`${res.status} ${detail}`.trim());
    }
    return res;
  }

  async json(path) {
    return (await this.request(path)).json();
  }

  // Checks the server and that this pack's nodes are installed.
  async check() {
    await this.json("/system_stats");
    try {
      return await this.json("/gpc_ps/templates");
    } catch (e) {
      if (e.message.startsWith("404")) throw new Error(NOT_INSTALLED);
      throw new Error("Connected, but listing templates failed: " + e.message);
    }
  }

  templates() {
    return this.json("/gpc_ps/templates");
  }

  template(name) {
    return this.json("/gpc_ps/templates/" + encodeURIComponent(name));
  }

  // { missing, message } for a template; null when the server predates this check.
  async checkTemplate(name) {
    try {
      return await this.json("/gpc_ps/check/" + encodeURIComponent(name));
    } catch (e) {
      if (e.message.startsWith("404")) return null;
      throw e;
    }
  }

  async queue(prompt) {
    let res;
    try {
      res = await this.request("/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, client_id: this.clientId }),
      });
    } catch (e) {
      if (/'GPC_PS_\w+' not found/.test(e.message)) throw new Error(NOT_INSTALLED);
      throw e;
    }
    return (await res.json()).prompt_id;
  }

  // The colour check ("check", { image }) or Match to Reference ("match", { image, reference }),
  // base64 PNGs. Resolves to { findings, layers }.
  async colour(kind, body) {
    try {
      const res = await this.request("/gpc_ps/colour/" + kind, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return await res.json();
    } catch (e) {
      if (/^40[45]/.test(e.message)) throw new Error("This ComfyUI predates the colour check: update the pack and restart ComfyUI.");
      throw e;
    }
  }

  // Stops a prompt: settles the wait at once, then asks the server to drop it.
  // Whether the server let go is a separate question, answered by where().
  cancel(promptId) {
    if (this.pending && this.pending.promptId === promptId) this.pending.stop();
    const headers = { "Content-Type": "application/json" };
    // A pending prompt is only in the queue; a running one only answers to /interrupt.
    // Servers that predate the prompt_id argument ignore the body and interrupt globally.
    this.request("/queue", { method: "POST", headers, body: JSON.stringify({ delete: [promptId] }) }).catch(() => {});
    this.request("/interrupt", { method: "POST", headers, body: JSON.stringify({ prompt_id: promptId }) }).catch(() => {});
  }

  // Where a prompt stands: "running", "pending", "gone" (finished, dropped, or a
  // restarted server that never heard of it) or "unknown" (no answer).
  async where(promptId) {
    let queue;
    try {
      queue = await this.json("/queue");
    } catch (_) {
      return { state: "unknown" };
    }
    const { queue_running: running, queue_pending: pending } = queue || {};
    // Anything but the expected shape is "we don't know": reporting "gone" would
    // unlock the panel on a busy server.
    if (!Array.isArray(running) || !Array.isArray(pending)) return { state: "unknown" };
    const index = (list) => list.findIndex((item) => item && item[1] === promptId);
    if (index(running) >= 0) return { state: "running" };
    const ahead = index(pending);
    if (ahead >= 0) return { state: "pending", ahead };
    return { state: "gone" };
  }

  // A restarted ComfyUI has closed the progress socket; a half-dead one never says so.
  reconnect() {
    this.close();
    this.connect();
  }

  // Progress messages over the websocket. Optional: run() also polls history,
  // so a blocked socket only loses the progress bar.
  connect() {
    if (this.socket) return;
    this.socket = net.openSocket(this.url.replace(/^http/, "ws") + "/ws?clientId=" + this.clientId, {
      onText: (text) => {
        let msg;
        try {
          msg = JSON.parse(text);
        } catch (_) {
          return;
        }
        for (const fn of this.listeners) fn(msg);
      },
      onClose: () => {
        this.socket = null;
      },
    });
  }

  close() {
    if (this.socket) this.socket.close();
    this.socket = null;
  }

  // Waits for a prompt to finish. Resolves to its history entry.
  // onResult(index, total, imageRef): a result sent before the run ends (Nano Banana);
  // onNotice(text): something the run wants said, e.g. that part of a batch failed.
  wait(promptId, onProgress = () => {}, onResult = () => {}, onNotice = () => {}) {
    return new Promise((resolve, reject) => {
      let done = false;
      const finish = (fn, value) => {
        if (done) return;
        done = true;
        clearInterval(timer);
        this.listeners.delete(listener);
        if (this.pending === job) this.pending = null;
        fn(value);
      };
      // cancel() settles this without touching the network, so a wedged server
      // can't leave the panel waiting.
      const job = {
        promptId,
        stop() {
          const error = new Error("Stopped");
          error.cancelled = true;
          finish(reject, error);
        },
      };
      this.pending = job;
      const listener = (msg) => {
        const d = msg.data || {};
        if (d.prompt_id && d.prompt_id !== promptId) return;
        if (msg.type === "progress") onProgress(d.value / d.max, d.value, d.max);
        if (msg.type === "gpc_ps.result") onResult(d.index, d.total, d.image);
        if (msg.type === "gpc_ps.notice") onNotice(d.text);
        if (msg.type === "execution_error") finish(reject, new Error(d.exception_message || "Execution failed"));
        if (msg.type === "execution_interrupted") finish(reject, new Error("Cancelled"));
      };
      this.listeners.add(listener);
      // One poll at a time: a server that stops answering mustn't stack requests.
      let polling = false;
      const timer = setInterval(async () => {
        if (polling) return;
        polling = true;
        try {
          const history = await this.json("/history/" + promptId);
          const entry = history[promptId];
          if (!entry) return;
          const status = entry.status || {};
          if (status.status_str === "error") {
            const err = (status.messages || []).find((m) => m[0] === "execution_error");
            finish(reject, new Error(err ? err[1].exception_message : "Execution failed"));
          } else if (status.completed !== false) {
            finish(resolve, entry);
          }
        } catch (_) {
          // keep polling; the server may be busy
        } finally {
          polling = false;
        }
      }, 1000);
    });
  }

  // Images written by the template's PS Output nodes, as ArrayBuffers.
  // `kind` "gpc_masks": the masks PS Output sends on their own ("layer mask").
  async outputImages(entry, outputIds, kind = "images") {
    const images = [];
    for (const id of outputIds) {
      for (const img of (entry.outputs[id] || {})[kind] || []) images.push(await this.view(img));
    }
    return images;
  }

  // One image ComfyUI saved ({ filename, subfolder, type }), as an ArrayBuffer.
  async view(img) {
    const q = { filename: img.filename, subfolder: img.subfolder || "", type: img.type || "temp" };
    const query = Object.entries(q).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");
    return (await this.request("/view?" + query)).arrayBuffer();
  }
}

function formatError(body) {
  if (!body) return "";
  const parts = [];
  if (body.error) parts.push(body.error.message || body.error);
  for (const [id, info] of Object.entries(body.node_errors || {})) {
    for (const e of info.errors || []) parts.push(`${info.class_type} #${id}: ${e.details || e.message}`);
  }
  return parts.join("\n");
}

module.exports = { ComfyClient, formatError };
