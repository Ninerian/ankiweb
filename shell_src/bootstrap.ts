import { addBrowserClasses } from "./browser_selector";
import { Bridge } from "./pycmd_shim";

// Context resolution order: explicit page global, then ?context= (the spike), then "default".
const ctx =
  (window as any).__ankiwebContext ||
  new URLSearchParams(location.search).get("context") ||
  "default";

const bridge = new Bridge(ctx);
(window as any).__ankiwebBridge = bridge;

function nightOn(): boolean {
  return location.hash.includes("night") || localStorage.getItem("ankiweb-night") === "1";
}

// Server-invokable navigation/reload helpers (called via {type:"call"}).
bridge.registerCalls({
  ankiwebNavigate: (url: unknown) => {
    location.href = String(url);
  },
  ankiwebReload: () => {
    location.reload();
  },
});

(window as any).ankiwebImportFile = () => {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".csv,.tsv,.txt,.apkg,.zip";
  input.onchange = async () => {
    const f = input.files && input.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const resp = await fetch("/import/upload", { method: "POST", body: fd });
    if (!resp.ok) { window.alert("Import failed: " + (await resp.text())); return; }
    const { route, path } = await resp.json();
    window.location.href = "/" + route + "/" + encodeURIComponent(path);
  };
  input.click();
};

(window as any).ankiwebImageOcclusion = () => {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.onchange = async () => {
    const f = input.files && input.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    const resp = await fetch("/image-occlusion/upload", { method: "POST", body: fd });
    if (!resp.ok) { window.alert("Image occlusion upload failed: " + (await resp.text())); return; }
    const { path } = await resp.json();
    window.location.href = "/image-occlusion/" + encodeURIComponent(path);
  };
  input.click();
};

// Cross-screen refresh: a screen may set window.__ankiwebOnOpchanges to handle this
// itself (e.g. the Browser re-searches in place to keep an embedded editor iframe alive);
// otherwise reload when another screen's op changed our data.
window.addEventListener("anki-opchanges", (e: Event) => {
  const detail = (e as CustomEvent).detail;
  const flags = detail.flags || {};
  if (detail.initiator === ctx) return;
  const custom = (window as any).__ankiwebOnOpchanges;
  if (typeof custom === "function") {
    custom(detail);
    return;
  }
  if (flags.study_queues || flags.deck || flags.card || flags.note) {
    location.reload();
  }
});

// Upstream browser_selector.ts parity: platform/browser classes on <html>.
addBrowserClasses();

// Night-mode: the #night hash convention OR the persisted preference. Applied
// synchronously in <head> (before <body>) so server-rendered screens don't flash.
if (nightOn()) {
  document.documentElement.classList.add("night-mode");
  document.documentElement.setAttribute("data-bs-theme", "dark");
}


(window as any).ankiwebToggleNight = () => {
  const on = localStorage.getItem("ankiweb-night") === "1";
  localStorage.setItem("ankiweb-night", on ? "0" : "1");
  location.reload();
};

// Bootstrap tooltips are opt-in: create one per tooltip target, and keep up with elements that
// Datastar patches in or out later. Targets are [data-bs-toggle="tooltip"] elements plus the
// editor's title-bearing controls (toolbar buttons/selects, per-field action buttons). Per-element instances (not the delegated
// `selector` option) so each element keeps its own data-bs-trigger / delay / placement.
// Only the slice of Bootstrap's Tooltip API used here (bootstrap.bundle.min.js sets window.bootstrap).
interface TooltipStatics {
  getOrCreateInstance(el: Element, config?: { container?: string; trigger?: string }): unknown;
  getInstance(el: Element): { dispose(): void } | null;
}

declare global {
  interface Window {
    bootstrap?: { Tooltip?: TooltipStatics };
  }
}

function tooltipTargets(node: Node): Element[] {
  if (!(node instanceof Element)) return [];
  const sel = '[data-bs-toggle="tooltip"], .editor-toolbar [title], .field-action-btn[title]';
  return [...(node.matches(sel) ? [node] : []), ...node.querySelectorAll(sel)];
}

function createTooltip(Tooltip: TooltipStatics, el: Element): void {
  // Render in <body> so overflow/stacking of toolbars and cards can never clip a tooltip.
  // Title-based controls are hover-only: a clicked button keeps focus, and Bootstrap's default
  // "hover focus" trigger would keep its tooltip open after the pointer has left.
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
