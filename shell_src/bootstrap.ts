import { addBrowserClasses } from "./browser_selector";
import { Bridge } from "./pycmd_shim";

// Resolve once for this document; browser navigation creates a new document and context.
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
    const target = String(url);
    location.assign(target);
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
    if (route === "import-anki-package" && (window as any).__ankiwebContext === "deckbrowser") {
      const modalResp = await fetch("/import-anki-package/modal/" + encodeURIComponent(path));
      if (modalResp.ok) {
        const modalHtml = await modalResp.text();
        let container = document.getElementById("deckbrowserImportModalContainer");
        if (!container) {
          container = document.createElement("div");
          container.id = "deckbrowserImportModalContainer";
          document.body.appendChild(container);
        }
        container.innerHTML = modalHtml;
        const modalEl = document.getElementById("importPackageModal") as HTMLDialogElement | null;
        if (modalEl && typeof modalEl.showModal === "function") {
          modalEl.showModal();
          return;
        }
      }
    }
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
  document.documentElement.setAttribute("data-theme", "dark");
} else {
  document.documentElement.setAttribute("data-theme", "light");
}

(window as any).ankiwebToggleNight = () => {
  const on = localStorage.getItem("ankiweb-night") === "1";
  localStorage.setItem("ankiweb-night", on ? "0" : "1");
  location.reload();
};

// daisyUI tooltips: convert title-bearing controls (.editor-toolbar [title], .field-action-btn[title])
// into daisyUI tooltip (class="tooltip", data-tip=<title>), keeping up with elements that
// Datastar patches in or out later. Controls that cannot render pseudo-element tooltips
// (e.g. <select>, <input>, <option>, elements with overflow:hidden) retain native title.
function canRenderDaisyTooltip(el: Element): boolean {
  const tag = el.tagName.toLowerCase();
  if (tag === "select" || tag === "input" || tag === "option" || tag === "textarea") {
    return false;
  }
  // Elements with overflow:hidden (or ancestor clipping inside the toolbar) clip ::before/::after
  if (el.classList.contains("overflow-hidden")) {
    return false;
  }
  return true;
}

function tooltipTargets(node: Node): Element[] {
  if (!(node instanceof Element)) return [];
  const sel = '.editor-toolbar [title], .field-action-btn[title]';
  return [...(node.matches(sel) ? [node] : []), ...node.querySelectorAll(sel)];
}

function applyDaisyTooltip(el: Element): void {
  const tip = el.getAttribute("data-tip") || el.getAttribute("title");
  if (!tip) return;
  if (!el.getAttribute("aria-label")) {
    el.setAttribute("aria-label", tip);
  }
  if (!canRenderDaisyTooltip(el)) {
    // Keep native title attribute for controls where CSS tooltips cannot render
    return;
  }
  el.setAttribute("data-tip", tip);
  el.removeAttribute("title");
  el.classList.add("tooltip");
  // Place on bottom or top appropriately if not specified
  if (!el.classList.contains("tooltip-top") && !el.classList.contains("tooltip-bottom") &&
      !el.classList.contains("tooltip-left") && !el.classList.contains("tooltip-right")) {
    el.classList.add("tooltip-bottom");
  }
}
document.addEventListener("DOMContentLoaded", () => {
  tooltipTargets(document.body).forEach(applyDaisyTooltip);
  new MutationObserver((records) => {
    for (const r of records) {
      r.addedNodes.forEach((n) => tooltipTargets(n).forEach(applyDaisyTooltip));
    }
  }).observe(document.body, { childList: true, subtree: true });
});

// Tooltip CSS stays suppressed until the page has fully loaded (see route-editor-toolbar.css).
window.addEventListener("load", () => {
  setTimeout(() => document.documentElement.classList.add("tooltips-ready"), 150);
});

window.addEventListener("load", () => bridge.ready());
