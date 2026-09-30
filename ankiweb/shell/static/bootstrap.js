(() => {
  var __defProp = Object.defineProperty;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);

  // shell_src/browser_selector.ts
  function addBrowserClasses() {
    const ua = navigator.userAgent.toLowerCase();
    const el = document.documentElement;
    if (/ipad/.test(ua)) el.classList.add("ipad");
    else if (/iphone/.test(ua)) el.classList.add("iphone");
    else if (/android/.test(ua)) el.classList.add("android");
    if (/ipad|iphone|ipod/.test(ua)) el.classList.add("ios");
    if (/ipad|iphone|ipod|android/.test(ua)) el.classList.add("mobile");
    else if (/linux/.test(ua)) el.classList.add("linux");
    else if (/windows/.test(ua)) el.classList.add("win");
    else if (/mac/.test(ua)) el.classList.add("mac");
    if (/firefox\//.test(ua)) el.classList.add("firefox");
    else if (/chrome\//.test(ua)) el.classList.add("chrome");
    else if (/safari\//.test(ua)) el.classList.add("safari");
  }

  // shell_src/pycmd_shim.ts
  var Bridge = class {
    constructor(ctx2) {
      this.ctx = ctx2;
      __publicField(this, "ws");
      __publicField(this, "nextId", 1);
      __publicField(this, "cbs", /* @__PURE__ */ new Map());
      __publicField(this, "domDone", false);
      __publicField(this, "queue", []);
      __publicField(this, "calls", {});
      const proto = location.protocol === "https:" ? "wss" : "ws";
      this.ws = new WebSocket(`${proto}://${location.host}/ws?context=${ctx2}`);
      this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
      const fn = (arg, cb) => {
        const id = cb ? this.nextId++ : null;
        if (id !== null && cb) this.cbs.set(id, cb);
        this.send({ type: "cmd", id, ctx: this.ctx, arg });
        return false;
      };
      window.pycmd = window.bridgeCommand = fn;
    }
    /** Register named functions the server may invoke via {type:"call"}. */
    registerCalls(map) {
      Object.assign(this.calls, map);
    }
    /** Signal the page is ready; flush queued server messages. */
    ready() {
      this.send({ type: "ready", ctx: this.ctx });
      this.domDone = true;
      for (const m of this.queue) this.handle(m);
      this.queue = [];
    }
    send(obj) {
      if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
      else this.ws.addEventListener("open", () => this.ws.send(JSON.stringify(obj)), { once: true });
    }
    onMessage(msg) {
      if (msg.type === "result" && this.cbs.has(msg.id)) {
        this.cbs.get(msg.id)(msg.value);
        this.cbs.delete(msg.id);
        return;
      }
      if (!this.domDone && (msg.type === "call" || msg.type === "eval")) {
        this.queue.push(msg);
        return;
      }
      this.handle(msg);
    }
    handle(msg) {
      if (msg.type === "call") {
        const f = this.calls[msg.fn] || window[msg.fn];
        const value = typeof f === "function" ? f(...msg.args || []) : void 0;
        if (msg.id != null) this.send({ type: "result", id: msg.id, value });
      } else if (msg.type === "eval") {
        const value = (0, eval)(msg.js);
        if (msg.id != null) this.send({ type: "result", id: msg.id, value });
      } else if (msg.type === "opchanges") {
        window.dispatchEvent(new CustomEvent("anki-opchanges", { detail: msg }));
      }
    }
  };

  // shell_src/bootstrap.ts
  var ctx = window.__ankiwebContext || new URLSearchParams(location.search).get("context") || "default";
  var bridge = new Bridge(ctx);
  window.__ankiwebBridge = bridge;
  function nightOn() {
    return location.hash.includes("night") || localStorage.getItem("ankiweb-night") === "1";
  }
  bridge.registerCalls({
    ankiwebNavigate: (url) => {
      location.href = String(url);
    },
    ankiwebReload: () => {
      location.reload();
    }
  });
  window.ankiwebImportFile = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".csv,.tsv,.txt,.apkg,.zip";
    input.onchange = async () => {
      const f = input.files && input.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      const resp = await fetch("/import/upload", { method: "POST", body: fd });
      if (!resp.ok) {
        window.alert("Import failed: " + await resp.text());
        return;
      }
      const { route, path } = await resp.json();
      window.location.href = "/" + route + "/" + encodeURIComponent(path);
    };
    input.click();
  };
  window.ankiwebImageOcclusion = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = async () => {
      const f = input.files && input.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append("file", f);
      const resp = await fetch("/image-occlusion/upload", { method: "POST", body: fd });
      if (!resp.ok) {
        window.alert("Image occlusion upload failed: " + await resp.text());
        return;
      }
      const { path } = await resp.json();
      window.location.href = "/image-occlusion/" + encodeURIComponent(path);
    };
    input.click();
  };
  window.addEventListener("anki-opchanges", (e) => {
    const detail = e.detail;
    const flags = detail.flags || {};
    if (detail.initiator === ctx) return;
    const custom = window.__ankiwebOnOpchanges;
    if (typeof custom === "function") {
      custom(detail);
      return;
    }
    if (flags.study_queues || flags.deck || flags.card || flags.note) {
      location.reload();
    }
  });
  addBrowserClasses();
  if (nightOn()) {
    document.documentElement.classList.add("night-mode");
    document.documentElement.setAttribute("data-bs-theme", "dark");
  }
  window.ankiwebToggleNight = () => {
    const on = localStorage.getItem("ankiweb-night") === "1";
    localStorage.setItem("ankiweb-night", on ? "0" : "1");
    location.reload();
  };
  function tooltipTargets(node) {
    if (!(node instanceof Element)) return [];
    const sel = '[data-bs-toggle="tooltip"], .editor-toolbar [title], .field-action-btn[title]';
    return [...node.matches(sel) ? [node] : [], ...node.querySelectorAll(sel)];
  }
  function createTooltip(Tooltip, el) {
    Tooltip.getOrCreateInstance(el, el.hasAttribute("data-bs-toggle") ? { container: "body" } : { container: "body", trigger: "hover" });
  }
  document.addEventListener("DOMContentLoaded", () => {
    const Tooltip = window.bootstrap?.Tooltip;
    if (!Tooltip) return;
    tooltipTargets(document.body).forEach((el) => createTooltip(Tooltip, el));
    new MutationObserver((records) => {
      for (const r of records) {
        r.removedNodes.forEach((n) => tooltipTargets(n).forEach((el) => Tooltip.getInstance(el)?.dispose()));
        r.addedNodes.forEach((n) => tooltipTargets(n).forEach((el) => createTooltip(Tooltip, el)));
      }
    }).observe(document.body, { childList: true, subtree: true });
  });
  window.addEventListener("load", () => bridge.ready());
})();
