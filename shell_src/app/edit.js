// Datastar's input binding observes the input event after the caret-preserving edit.
window.avInsert = (button) => {
  const input = document.getElementById(button.dataset.target);
  if (!(input instanceof HTMLTextAreaElement)) return;

  const start = input.selectionStart;
  const end = input.selectionEnd;
  input.setRangeText(button.dataset.value ?? "", start, end, "end");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
};

window.avFocus = (id) => {
  requestAnimationFrame(() => document.getElementById(id)?.focus());
};

window.avAddKey = (event) => {
  if (
    event.key !== "Enter" || event.isComposing || event.keyCode === 229 ||
    event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey ||
    event.metaKey
  ) return;

  const target = event.target;
  const wizard = document.getElementById("add-wizard");
  if (!(target instanceof HTMLTextAreaElement) || !wizard?.contains(target)) return;
  const phase = wizard.dataset.browsePhase;
  if (phase === "opening" || phase === "open" || phase === "closing") return;
  if (event.shiftKey) return;

  const next = document.getElementById("btn-next");
  if (!next || getComputedStyle(next).display === "none" || next.disabled) return;
  event.preventDefault();
  next.click();
};

window.avConfirmDiscard = (front, back, hint, example, saving, message, nid = 0, original = {}) => {
  if (saving) return false;
  const fields = { front, back, hint, example };
  const dirty = nid
    ? Object.entries(fields).some(([key, value]) => value !== original[key])
    : Object.values(fields).some(Boolean);
  return !dirty || window.confirm(message);
};

window.avGuardNav = (event, front, back, hint, example, saving, message, nid, original) => {
  if (!window.avConfirmDiscard(front, back, hint, example, saving, message, nid, original)) {
    event.preventDefault();
  }
};

let browseTimer;
let browseTrigger;
let browseOpener;
let browseOrigin;
let browseEditing = false;
const browseMotionTime = (duration) =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : duration;
const browseEvent = (name, detail = {}) =>
  document.getElementById("add-wizard")?.dispatchEvent(new CustomEvent(name, { detail }));

const captureBrowseOrigin = () => {
  const card = document.querySelector("#added-cards .stacked-card");
  if (!card) {
    browseOrigin = null;
    return;
  }
  const cardRect = card.getBoundingClientRect();
  browseOrigin = {
    x: cardRect.left + cardRect.width / 2,
    y: cardRect.top + cardRect.height / 2,
  };
};

const positionBrowseRows = () => {
  if (!browseOrigin) return;
  const { x, y } = browseOrigin;
  // Measure unanimated list items first; row transforms do not affect their bounds.
  const positions = [...document.querySelectorAll("#deck-cards .browse-card")].map((row) => {
    const rect = row.parentElement.getBoundingClientRect();
    return [row, x - (rect.left + rect.width / 2), y - (rect.top + rect.height / 2)];
  });
  for (const [row, offsetX, offsetY] of positions) {
    row.style.setProperty("--fan-offset-x", `${offsetX}px`);
    row.style.setProperty("--fan-offset-y", `${offsetY}px`);
  }
};

window.avBrowseFromBack = (trigger) => {
  browseOpener = trigger.id;
  try {
    document.getElementById("pile")?.click();
  } finally {
    browseOpener = undefined;
  }
};

window.avOpenBrowse = (trigger) => {
  clearTimeout(browseTimer);
  document.getElementById("add-editor")?.classList.remove("animate-fresh-card");
  for (const element of document.querySelectorAll("#added-cards .animate-slide-to-added, #added-cards .animate-bump")) {
    element.classList.remove("animate-slide-to-added", "animate-bump");
  }
  browseTrigger = browseOpener || trigger.id;
  browseEditing = false;
  browseTimer = setTimeout(() => {
    captureBrowseOrigin();
    browseEvent("av-browse-ready");
    positionBrowseRows();
  }, browseMotionTime(300));
};

window.avCloseBrowse = (editing = false, phase = "open") => {
  if (editing) browseEditing = true;
  if (phase === "closing") return;
  if (phase === "closed" || phase === "returning") {
    if (editing) window.avBrowseFocus(true);
    return;
  }
  clearTimeout(browseTimer);
  const returnEditor = () => {
    browseEvent("av-browse-returning", { editing: browseEditing });
    const duration = browseMotionTime(500);
    if (duration) browseTimer = setTimeout(() => browseEvent("av-browse-settled"), duration);
    else browseEvent("av-browse-settled");
  };
  if (phase === "opening") {
    returnEditor();
  } else {
    positionBrowseRows();
    browseEvent("av-browse-closing");
    const duration = browseMotionTime(460);
    if (duration) browseTimer = setTimeout(returnEditor, duration);
    else returnEditor();
  }
};

window.avBrowseReadyFocus = () => {
  requestAnimationFrame(() => {
    if (document.getElementById("add-wizard")?.dataset.browsePhase === "open") {
      document.getElementById("deck-cards")?.focus({ preventScroll: true });
    }
  });
};

window.avBrowseFocus = (editing) => {
  requestAnimationFrame(() => {
    const phase = document.getElementById("add-wizard")?.dataset.browsePhase;
    if (phase === "returning" || phase === "closed") {
      document.getElementById(editing ? "input-front" : browseTrigger)?.focus({ preventScroll: true });
    }
  });
};

// Delegate gestures so server morphs can replace the pile without losing listeners.
let pilePointer;
let suppressPileClickUntil = 0;
document.addEventListener("pointerdown", (event) => {
  const pile = event.target instanceof Element ? event.target.closest("#pile") : null;
  if (!pile || pile.disabled || !event.isPrimary || event.button !== 0) return;
  pilePointer = { id: event.pointerId, x: event.clientX, y: event.clientY, pile };
  pile.setPointerCapture?.(event.pointerId);
});
document.addEventListener("pointercancel", () => { pilePointer = null; });
document.addEventListener("pointerup", (event) => {
  if (!pilePointer || pilePointer.id !== event.pointerId) return;
  const { x, y, pile } = pilePointer;
  pilePointer = null;
  const dx = event.clientX - x;
  const dy = y - event.clientY;
  if (Math.abs(dx) > 6 || Math.abs(dy) > 6) {
    suppressPileClickUntil = performance.now() + 700;
    if (dy > 28 && dy > Math.abs(dx)) pile.click();
  }
});
document.addEventListener("click", (event) => {
  if (event.isTrusted && event.detail && performance.now() < suppressPileClickUntil &&
      event.target instanceof Element && event.target.closest("#pile")) {
    event.preventDefault();
    event.stopImmediatePropagation();
    suppressPileClickUntil = 0;
  }
}, true);

let toastTimer;
window.avAddToast = (message) => {
  const toast = document.getElementById("add-toast");
  if (!toast) return;
  toast.querySelector(".alert").textContent = message;
  toast.style.display = "grid";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.display = "none"; }, 4000);
};

window.avAnimateCommit = () => {
  const editor = document.getElementById("add-editor");
  const stack = document.getElementById("added-cards");
  const stamp = stack?.dataset.ts;
  if (!editor || !stamp || editor.dataset.ts === stamp) return;
  editor.dataset.ts = stamp;

  const animations = [
    [editor, "animate-fresh-card"],
    [stack.querySelector("[data-note-id]"), "animate-slide-to-added"],
    [stack.querySelector(".add-stack-count"), "animate-bump"],
  ];
  for (const [element, name] of animations) element?.classList.remove(name);
  // Restart CSS animations even when morphing retains the same elements.
  void editor.offsetWidth;
  for (const [element, name] of animations) element?.classList.add(name);
};

document.addEventListener("animationend", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (event.animationName === "slideToAdded" && target.matches("#added-cards .stacked-card")) {
    target.classList.remove("animate-slide-to-added");
  } else if (event.animationName === "bump" && target.matches("#added-cards .add-stack-count")) {
    target.classList.remove("animate-bump");
  } else if (event.animationName === "popInFreshCard" && target.id === "add-editor") {
    target.classList.remove("animate-fresh-card");
  }
});

let summaryTrigger;
window.avOpenSummary = (trigger) => {
  summaryTrigger = trigger;
  requestAnimationFrame(() => document.getElementById("summary-keep-adding")?.focus());
};

window.avCloseSummary = () => {
  summaryTrigger?.focus();
};

window.avModalKey = (event) => {
  if (event.key !== "Tab") return;
  const dialog = event.currentTarget;
  const controls = [...dialog.querySelectorAll("a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])")]
    .filter((element) => element.getClientRects().length > 0);
  if (!controls.length) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
};
