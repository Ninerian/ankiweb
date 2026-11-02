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

window.avBackKey = (event, control) => {
  if (control.hasAttribute("href") || (event.key !== "Enter" && event.key !== " ")) return;
  event.preventDefault();
  if (!event.repeat && !event.isComposing) control.click();
};

let browseTimer;
let browseSequence = 0;
let browseTrigger = "pile";
let browseOrigin;
let browseEditing = false;
const browseMotionTime = (duration) =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : duration;
const browseEvent = (name, detail = {}) =>
  document.getElementById("add-wizard")?.dispatchEvent(new CustomEvent(name, { detail }));

let editUrl;
let editState;
let skipHistoryDiscard = false;
let restoringHistory = false;
let pendingHistoryFailure = false;
let pendingBrowseAfterSave = false;
let pendingSavedList = false;
let historyCard = false;

const editViewUrl = (view, card) => {
  const url = new URL(window.location.href);
  url.searchParams.delete("view");
  url.searchParams.delete("card");
  if (view === "cards") url.searchParams.set("view", "cards");
  if (view === "card") url.searchParams.set("card", String(card));
  return url.href;
};

const validEditHistory = (state) =>
  state?.avEdit === true && Number.isSafeInteger(state.avIndex) &&
  state.avIndex >= 0 && state.avIndex < history.length;

const setEditHistory = (view, card, replace = false) => {
  const listSkips = view === "card" ? editState?.avSkipList : 0;
  const state = {
    avEdit: true,
    avIndex: (editState?.avIndex ?? 0) + (replace ? 0 : 1),
    ...(listSkips ? { avSkipList: listSkips } : {}),
  };
  const url = editViewUrl(view, card);
  history[replace ? "replaceState" : "pushState"](state, "", url);
  editUrl = url;
  editState = state;
};

const finishHistoryRestore = () => {
  restoringHistory = false;
  if (pendingHistoryFailure) {
    pendingHistoryFailure = false;
    window.avEditHistoryFailed();
  }
  if (pendingBrowseAfterSave) {
    pendingBrowseAfterSave = false;
    window.avOpenBrowseAfterSave();
  }
};

const restoreEditHistory = (state) => {
  const targetIndex = validEditHistory(state) ? state.avIndex : null;
  const delta = targetIndex === null ? 0 : editState.avIndex - targetIndex;
  if (delta) {
    restoringHistory = true;
    history.go(delta);
  } else {
    history.replaceState(editState, "", editUrl);
    finishHistoryRestore();
  }
};


window.avEditCardLoaded = (nid) => {
  if (historyCard) historyCard = false;
  else setEditHistory("card", nid);
};

window.avEditHistoryFailed = () => {
  if (!historyCard) return;
  if (restoringHistory) {
    pendingHistoryFailure = true;
    return;
  }
  historyCard = false;
  setEditHistory("editor", null, true);
  browseEvent("av-history", { view: "editor" });
  browseEvent("av-history-failed");
};

window.avEditBack = (event, front, back, hint, example, saving, message, nid, original, browsing, phase) => {
  if (saving || phase === "closing" || phase === "returning") {
    event.preventDefault();
    return;
  }
  if (!browsing && !nid) {
    if (event.currentTarget.hasAttribute("href")) {
      window.avGuardNav(event, front, back, hint, example, saving, message, nid, original);
    } else {
      event.preventDefault();
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (window.avConfirmDiscard(front, back, hint, example, saving, message, nid, original)) {
        window.location.assign("/app/");
      }
    }
    return;
  }
  event.preventDefault();
  if (!browsing && !window.avConfirmDiscard(front, back, hint, example, saving, message, nid, original)) return;
  if (browsing && editState?.avSkipList > editState.avIndex) {
    setEditHistory("editor", null, true);
    browseEvent("av-history", { view: "editor" });
  } else if (editState?.avIndex > 0) {
    skipHistoryDiscard = true;
    history.go(browsing && editState.avSkipList ? -editState.avSkipList : -1);
  } else {
    const view = browsing ? "editor" : "cards";
    setEditHistory(view, null, true);
    browseEvent("av-history", { view });
  }
};

window.avEditPop = (event, front, back, hint, example, saving, message, nid, original, browsing, phase) => {
  if (restoringHistory) {
    if (event.state?.avEdit && event.state.avIndex === editState.avIndex && location.href === editUrl) {
      finishHistoryRestore();
    } else {
      restoreEditHistory(event.state);
    }
    return;
  }
  const url = new URL(window.location.href);
  const card = url.searchParams.get("card");
  const view = card ? "card" : url.searchParams.get("view") === "cards" ? "cards" : "editor";
  const sameView = view === "card" ? !browsing && Number(card) === nid :
    view === "cards" ? browsing && !nid && (phase === "opening" || phase === "open") : !browsing && !nid;
  if (saving || (!sameView && !skipHistoryDiscard && !browsing &&
      !window.avConfirmDiscard(front, back, hint, example, saving, message, nid, original))) {
    skipHistoryDiscard = false;
    restoreEditHistory(event.state);
    return;
  }
  skipHistoryDiscard = false;
  editUrl = url.href;
  editState = validEditHistory(event.state) ? event.state : { avEdit: true, avIndex: 0 };
  if (sameView) {
    if (pendingSavedList && view === "cards") {
      window.avOpenBrowse(document.getElementById("pile"), false);
    }
    pendingSavedList = false;
    return;
  }
  pendingSavedList = false;
  historyCard = view === "card";
  browseEvent("av-history", { view, card });
};

document.addEventListener("DOMContentLoaded", () => {
  const wizard = document.getElementById("add-wizard");
  if (!wizard) return;
  editState = validEditHistory(history.state) ? { ...history.state } : { avEdit: true, avIndex: 0 };
  if (!Number.isSafeInteger(editState.avSkipList) || editState.avSkipList <= 0 ||
      editState.avSkipList > history.length) delete editState.avSkipList;
  editUrl = editViewUrl(wizard.dataset.initialView, wizard.dataset.initialCard);
  history.replaceState(editState, "", editUrl);
});

// The focus helper reads the browse phase initialized by Datastar.
document.addEventListener("datastar-ready", () => {
  if (document.getElementById("add-wizard")?.dataset.initialView === "cards") {
    window.avBrowseReadyFocus();
  }
}, { once: true });

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
// Match the future stage slot without changing the current editor layout or scroll.
const prepareBrowsePreview = (wizard) => {
  const header = wizard.querySelector(".review-hud");
  const steps = header.querySelector(":scope > .browse-fade");
  const stepStyle = getComputedStyle(steps);
  const stepHeight = steps.getBoundingClientRect().height +
    parseFloat(stepStyle.marginTop) + parseFloat(stepStyle.marginBottom);
  const top = header.getBoundingClientRect().bottom - wizard.getBoundingClientRect().top - stepHeight;
  wizard.style.setProperty("--browse-preview-top", `${top}px`);
  captureBrowseOrigin();
  wizard.style.setProperty("--browse-drag", "0");
  wizard.dataset.browseDrag = "measuring";
  const list = wizard.querySelector(".deck-browse-list");
  list.scrollTop = 0;
  wizard.style.setProperty("--browse-scrollbar", `${list.offsetWidth - list.clientWidth}px`);
  wizard.dataset.browseDrag = "dragging";
  positionBrowseRows();
};


const pileSwipeThreshold = 28;
const pileDragDistance = 48;
let pilePointer;
let pileDragTransition;

const clearPileDrag = (wizard) => {
  pileDragTransition = null;
  wizard.removeAttribute("data-browse-drag");
  wizard.style.removeProperty("--browse-drag");
  wizard.style.removeProperty("--browse-drag-duration");
  wizard.style.removeProperty("--browse-preview-top");
  wizard.style.removeProperty("--browse-scrollbar");
};

const returnPileDrag = (wizard) => {
  if (!wizard?.hasAttribute("data-browse-drag")) return;
  // Commit the last pointer position before enabling transitions.
  void wizard.offsetWidth;
  wizard.dataset.browseDrag = "settling";
  wizard.style.setProperty("--browse-drag-duration", "300ms");
  wizard.style.setProperty("--browse-drag", "0");
  const stack = wizard.querySelector("#added-cards");
  pileDragTransition = stack?.getAnimations().find((animation) => animation.transitionProperty === "transform");
  if (!pileDragTransition) {
    clearPileDrag(wizard);
    return;
  }
  const transition = pileDragTransition;
  transition.finished.then(() => {
    if (pileDragTransition === transition) clearPileDrag(wizard);
  }, () => {});
};

document.addEventListener("av-browse-returning", (event) => {
  if (event.target instanceof HTMLElement && event.target.hasAttribute("data-browse-drag")) {
    event.target.dataset.browseRestored = "";
    returnPileDrag(event.target);
  }
}, { capture: true });
document.addEventListener("av-browse-settled", (event) => {
  if (event.target instanceof HTMLElement) event.target.removeAttribute("data-browse-restored");
}, { capture: true });


window.avOpenBrowse = (trigger, pushHistory = true) => {
  clearTimeout(browseTimer);
  const sequence = ++browseSequence;
  document.getElementById("add-editor")?.classList.remove("animate-fresh-card");
  for (const element of document.querySelectorAll("#added-cards .animate-slide-to-added, #added-cards .animate-bump")) {
    element.classList.remove("animate-slide-to-added", "animate-bump");
  }
  browseTrigger = trigger?.id || "pile";
  if (pushHistory) setEditHistory("cards");
  browseEditing = false;
  const wizard = document.getElementById("add-wizard");
  wizard?.removeAttribute("data-browse-restored");
  if (pilePointer && pilePointer.wizard === wizard) pilePointer.committed = true;
  const returning = wizard?.dataset.browseDrag === "settling";
  const dragged = returning || wizard?.dataset.browseDrag === "dragging";
  if (!dragged) wizard?.removeAttribute("data-browse-unfolded");
  const stack = returning && wizard.querySelector("#added-cards");
  const progress = returning
    ? stack ? Math.max(0, Math.min(1, -new DOMMatrixReadOnly(getComputedStyle(stack).transform).m42 / pileDragDistance)) : 0
    : dragged ? Number(wizard.style.getPropertyValue("--browse-drag")) : 0;
  if (returning) pileDragTransition = null;
  const duration = browseMotionTime(dragged ? 300 * (1 - progress) : 300);
  if (dragged) {
    wizard.dataset.browseUnfolded = "";
    void wizard.offsetWidth;
    wizard.dataset.browseDrag = "settling";
    wizard.style.setProperty("--browse-drag-duration", `${duration}ms`);
    wizard.style.setProperty("--browse-drag", "1");
  }
  const finishOpening = () => {
    if (sequence !== browseSequence) return;
    captureBrowseOrigin();
    browseEvent("av-browse-ready");
    positionBrowseRows();
    if (dragged) clearPileDrag(wizard);
  };
  const transition = dragged && wizard.querySelector("#added-cards")?.getAnimations()
    .find((animation) => animation.transitionProperty === "transform");
  if (transition) transition.finished.then(finishOpening, () => {});
  else browseTimer = setTimeout(finishOpening, duration);
};

window.avOpenBrowseAfterSave = () => {
  if (restoringHistory) {
    pendingBrowseAfterSave = true;
    return;
  }
  // Cards reached from a list already have that list immediately behind them.
  // Returning there avoids replacing the card with a second identical list.
  if (editState?.avIndex > 0) {
    pendingSavedList = true;
    history.back();
    return;
  } else {
    setEditHistory("cards", null, true);
  }
  window.avOpenBrowse(document.getElementById("pile"), false);
};

window.avCloseBrowse = (editing = false, phase = "open") => {
  if (editing) browseEditing = true;
  if (phase === "closing") return;
  if (phase === "closed" || phase === "returning") {
    if (editing) window.avBrowseFocus(true);
    return;
  }
  clearTimeout(browseTimer);
  browseSequence++;
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
let suppressPileClickUntil = 0;
document.addEventListener("pointerdown", (event) => {
  const pile = event.target instanceof Element ? event.target.closest("#pile") : null;
  if (!pile || pile.disabled || !event.isPrimary || event.button !== 0) return;
  suppressPileClickUntil = 0;
  const wizard = document.getElementById("add-wizard");
  let startProgress = 0;
  if (wizard?.dataset.browsePhase === "closed" && wizard.dataset.browseDrag === "settling") {
    const stack = document.getElementById("added-cards");
    if (stack) {
      startProgress = Math.max(0, Math.min(1, -new DOMMatrixReadOnly(getComputedStyle(stack).transform).m42 / pileDragDistance));
    }
    pileDragTransition = null;
    wizard.dataset.browseDrag = "dragging";
    wizard.style.removeProperty("--browse-drag-duration");
    wizard.style.setProperty("--browse-drag", `${startProgress}`);
  }
  pilePointer = {
    id: event.pointerId, x: event.clientX, y: event.clientY, pile, wizard, moved: false, startProgress,
    touch: event.pointerType === "touch" || event.pointerType === "pen",
    interactive: (event.pointerType === "touch" || event.pointerType === "pen") &&
      wizard?.dataset.browsePhase === "closed" && browseMotionTime(1) !== 0,
  };
  pile.setPointerCapture?.(event.pointerId);
});
const updatePileDrag = (event) => {
  if (!pilePointer || pilePointer.id !== event.pointerId) return;
  const { x, y, wizard, startProgress } = pilePointer;
  const dx = event.clientX - x;
  const dy = y - event.clientY;
  if (Math.abs(dx) > 6 || Math.abs(dy) > 6) pilePointer.moved = true;
  if (pilePointer.committed) return;
  if (!pilePointer.interactive) return;
  const progress = dy > Math.abs(dx)
    ? Math.min(startProgress + dy / pileDragDistance, 1)
    : Math.max(startProgress + Math.min(dy, 0) / pileDragDistance, 0);
  if (progress > 0 && !wizard.hasAttribute("data-browse-drag")) {
    if (!pilePointer.moved) return;
    prepareBrowsePreview(wizard);
  }
  if (wizard.dataset.browseDrag === "dragging") {
    wizard.style.setProperty("--browse-drag", `${progress}`);
  }
};
document.addEventListener("pointermove", updatePileDrag);
const cancelPilePointer = (event) => {
  if (!pilePointer || pilePointer.id !== event.pointerId) return;
  if (pilePointer.moved || pilePointer.committed) suppressPileClickUntil = performance.now() + 700;
  if (!pilePointer.committed) returnPileDrag(pilePointer.wizard);
  pilePointer = null;
};
document.addEventListener("pointercancel", cancelPilePointer);
document.addEventListener("lostpointercapture", cancelPilePointer);
document.addEventListener("pointerup", (event) => {
  if (!pilePointer || pilePointer.id !== event.pointerId) return;
  updatePileDrag(event);
  const { x, y, pile, wizard, moved, touch, startProgress, committed } = pilePointer;
  pilePointer = null;
  const dx = event.clientX - x;
  const dy = y - event.clientY;
  if (committed) {
    suppressPileClickUntil = performance.now() + 700;
    return;
  }
  const distance = startProgress * pileDragDistance + dy;
  if (moved) {
    suppressPileClickUntil = performance.now() + 700;
    if ((touch ? distance >= pileSwipeThreshold : distance > pileSwipeThreshold) && dy > Math.abs(dx)) {
      pile.click();
      // Discard confirmation can reject the open.
      if (wizard?.dataset.browseDrag === "dragging") returnPileDrag(wizard);
    } else {
      returnPileDrag(wizard);
    }
  } else if (wizard?.dataset.browseDrag === "dragging" && !startProgress) {
    clearPileDrag(wizard);
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
document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element) || !event.target.closest("#pile")) return;
  const wizard = document.getElementById("add-wizard");
  if (wizard?.dataset.browseDrag === "dragging") returnPileDrag(wizard);
});


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
  if (new URL(window.location.href).searchParams.has("card")) {
    setEditHistory("editor", null, true);
  }
  summaryTrigger = trigger;
  requestAnimationFrame(() => {
    if (document.getElementById("add-summary")?.classList.contains("modal-open")) {
      document.getElementById("summary-keep-adding")?.focus();
    }
  });
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
