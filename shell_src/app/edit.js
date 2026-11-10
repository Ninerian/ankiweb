// Preserve the caret and dispatch input for counters and revision tracking.
window.avInsert = (button) => {
  const input = document.getElementById(button.dataset.target);
  if (!(input instanceof HTMLTextAreaElement)) return;

  const start = input.selectionStart;
  const end = input.selectionEnd;
  input.setRangeText(button.dataset.value ?? "", start, end, "end");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
};

let editorFocusGeneration = 0;
const requestEditorFocus = (callback) => {
  const generation = editorFocusGeneration;
  requestAnimationFrame(() => {
    if (generation === editorFocusGeneration &&
        !document.getElementById("add-summary")?.open) callback();
  });
};

window.avFocus = (id) => {
  requestEditorFocus(() => document.getElementById(id)?.focus());
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

const editForm = () => document.getElementById("edit-form");
const editSession = () => document.getElementById("edit-session");
const editWizard = () => document.getElementById("add-wizard");
const browsePhase = () => editWizard()?.dataset.browsePhase || "closed";
const browsing = () => ["opening", "open", "closing"].includes(browsePhase());
const busy = () => editWizard()?.getAttribute("aria-busy") === "true";
window.avNid = () => Number(editSession()?.dataset.nid || 0);
window.avAction = (suffix) => {
  const session = editSession();
  const deck = document.getElementById("add-wizard")?.dataset.deckId;
  return `/app/edit/${deck}/${session?.dataset.instance}/${session?.dataset.rev}${suffix}`;
};
window.avRequestStep = (to, via) => {
  window.avBumpRev();
  document.getElementById("edit-step-request")?.dispatchEvent(
    new CustomEvent("av-step", { detail: { to, via } })
  );
};
let stepRequest;
window.avStepRequest = () => {
  stepRequest?.abort();
  stepRequest = new AbortController();
  return stepRequest;
};
window.avBumpRev = () => {
  const session = editSession();
  if (session) session.dataset.rev = String(Number(session.dataset.rev) + 1);
};
const editDirty = () => {
  const form = editForm();
  if (!form) return false;
  const original = JSON.parse(editSession()?.dataset.original || "{}");
  return ["front", "back", "hint", "example"].some((key) => {
    const value = form.elements.namedItem(key)?.value ?? "";
    return window.avNid() ? value !== original[key] : value !== "";
  });
};
window.avConfirmDiscard = (message) => !busy() && (!editDirty() || window.confirm(message));
window.avGuardNav = (event, message) => {
  if (!window.avConfirmDiscard(message)) event.preventDefault();
};
window.avCanFinish = (message) =>
  !document.getElementById("add-summary")?.open &&
  !["opening", "closing", "returning"].includes(browsePhase()) &&
  window.avConfirmDiscard(message);

window.avSyncBack = () => {
  const phase = browsePhase();
  const inBrowse = browsing();
  const saving = busy();
  const back = document.getElementById("edit-back");
  if (!back) return;
  const nid = window.avNid();
  back.setAttribute("aria-label", inBrowse ? back.dataset.browseBack : nid ? back.dataset.listBack : back.dataset.exit);
  const link = !nid && !inBrowse && phase === "closed" && !saving && !editDirty();
  if (link) {
    back.setAttribute("href", "/app/");
    back.removeAttribute("role");
  } else {
    back.removeAttribute("href");
    back.setAttribute("role", "button");
  }
  back.setAttribute("aria-disabled", String(saving || phase === "closing" || phase === "returning"));
};
let pendingCommitBrowse = false;
window.avAfterCommit = () => {
  invalidateDraft();
  pendingCommitBrowse = true;
};
window.avEditFetch = (event) => {
  const { el, type } = event.detail;
  queueMicrotask(() => {
    window.avSyncBack();
    if (el.id === "btn-add" && type === "finished" && pendingCommitBrowse) {
      pendingCommitBrowse = false;
      browseEvent("av-open-saved");
    }
  });
  if (el !== editWizard()) return;
  if (type === "error" || type === "retries-failed") window.avEditHistoryFailed();
  else if (type === "finished" && document.getElementById("edit-error")?.textContent.trim()) {
    window.avEditHistoryFailed(false);
  }
};
window.avEditError = (message) => {
  const error = document.getElementById("edit-error");
  if (!error) return;
  if (!message) {
    error.hidden = true;
    error.replaceChildren();
    return;
  }
  const alert = document.createElement("div");
  alert.className = "alert alert-error";
  alert.textContent = message;
  error.replaceChildren(alert);
  error.hidden = false;
};
document.addEventListener("input", (event) => {
  const form = editForm();
  if (!form || !form.contains(event.target) || !(event.target instanceof HTMLTextAreaElement)) return;
  window.avEditError();
  window.avBumpRev();
  const counter = form.querySelector(`[data-counter-for=\"${event.target.name}\"]`);
  if (counter) counter.textContent = String(event.target.value.length);
  window.avSyncBack();
});
document.addEventListener("datastar-fetch", (event) => {
  if (event.detail.type !== "started") return;
  const source = event.detail.el;
  if (source === document.getElementById("add-wizard") || editSession()?.contains(source)) {
    window.avEditError();
  }
});
let lastEditorFocus;
document.addEventListener("focusin", (event) => {
  if (event.target instanceof HTMLElement) lastEditorFocus = event.target;
});
new MutationObserver((mutations) => {
  const sessionReplaced = mutations.some((mutation) => [...mutation.addedNodes].some((node) =>
    node instanceof Element && (node.id === "edit-session" || node.querySelector("#edit-session"))));
  if (sessionReplaced || mutations.some((mutation) => mutation.target === editWizard())) window.avSyncBack();
  if (!sessionReplaced) return;
  const lostFocus = lastEditorFocus;
  if (!lostFocus?.id || lostFocus.isConnected || document.activeElement !== document.body) return;
  if (!mutations.some((mutation) => [...mutation.removedNodes].some((node) =>
    node instanceof Element && node.contains(lostFocus)))) return;
  if (browsing()) {
    if (browsePhase() === "open") window.avBrowseReadyFocus();
    return;
  }
  requestEditorFocus(() => {
    if (document.activeElement === document.body) {
      document.getElementById(lostFocus.id)?.focus({ preventScroll: true });
    }
  });
}).observe(document.documentElement, {
  childList: true, subtree: true, attributes: true,
  attributeFilter: ["data-browse-phase", "aria-busy"],
});
window.avEditKey = (event) => {
  window.avAddKey(event);
  if (event.key === "Escape" && !event.repeat && !busy() && (browsing() || window.avNid())) {
    document.getElementById("edit-back")?.click();
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
let pendingHistoryFailure = null;
let pendingBrowseAfterSave = false;
let pendingSavedList = false;
let historyCard = false;
let draftGeneration = 0;
const staleDrafts = new Set();
let staleDirection = 0;
let arrivingStale = false;
const historySession = `ankiweb:editor-history:${document.getElementById("add-wizard")?.dataset.deckId}`;
try {
  const saved = JSON.parse(sessionStorage.getItem(historySession) || "{}");
  draftGeneration = saved.generation ?? 0;
  for (const generation of saved.stale ?? []) staleDrafts.add(generation);
} catch {
  sessionStorage.removeItem(historySession);
}
const saveDraftHistory = () => {
  sessionStorage.setItem(historySession, JSON.stringify({
    generation: draftGeneration, stale: [...staleDrafts],
  }));
};

const invalidateDraft = () => {
  const generation = editState?.avDraft;
  if (Number.isSafeInteger(generation)) staleDrafts.add(generation);
  saveDraftHistory();
};

const newDraft = () => {
  draftGeneration++;
  editState = { ...editState, avDraft: draftGeneration };
  saveDraftHistory();
};

const editViewUrl = (view, card, step = "front") => {
  const deck = document.getElementById("add-wizard")?.dataset.deckId;
  const prefix = `/app/edit/${deck}`;
  const path = view === "cards" ? `${prefix}/cards` :
    view === "card" ? `${prefix}/cards/${card}/${step}` : `${prefix}/${step}`;
  return new URL(path, location.origin).href;
};

const currentStep = () => ["front", "back", "preview"][
  Number(document.getElementById("edit-step")?.dataset.step || 1) - 1
];

const editUrlView = () => {
  const parts = location.pathname.split("/").filter(Boolean).slice(3);
  if (parts[0] === "cards") {
    return parts.length === 1 ? { view: "cards" } :
      { view: "card", card: parts[1], step: parts[2] };
  }
  return { view: "editor", step: parts[0] };
};

const validEditHistory = (state) =>
  state?.avEdit === true && Number.isSafeInteger(state.avIndex) &&
  state.avIndex >= 0 && state.avIndex < history.length;

const editHistoryView = (url) => new URL(url).pathname.endsWith("/cards") ? "cards" : "draft";

const setEditHistory = (view, card, replace = false, step = "front") => {
  if (view === "card" && !replace && editHistoryView(editUrl) === "cards") newDraft();
  const state = {
    ...editState,
    avEdit: true,
    avIndex: (editState?.avIndex ?? 0) + (replace ? 0 : 1),
  };
  if (view === "cards" && !replace) {
    state.avEditorIndex = editState?.avIndex ?? 0;
  } else if (view === "card" && !replace && new URL(editUrl).pathname.endsWith("/cards")) {
    state.avListIndex = editState?.avIndex ?? 0;
  }
  const url = editViewUrl(view, card, step);
  history[replace ? "replaceState" : "pushState"](state, "", url);
  editUrl = url;
  editState = state;
};

let pendingStepHistory;
window.avStepApplied = (step, nid, fromHistory) => {
  if (fromHistory) {
    if (!pendingStepHistory) return;
    const leaveList = pendingStepHistory.leaveList;
    editState = pendingStepHistory.state;
    editUrl = pendingStepHistory.url;
    pendingStepHistory = null;
    if (leaveList) browseEvent("av-history", { view: "editor" });
  } else if (editUrl !== editViewUrl(nid ? "card" : "editor", nid, step)) {
    setEditHistory(nid ? "card" : "editor", nid, false, step);
  }
};
window.avStepRejected = () => {
  if (!pendingStepHistory) return;
  const state = pendingStepHistory.state;
  pendingStepHistory = null;
  restoreEditHistory(state);
};

const finishHistoryRestore = () => {
  restoringHistory = false;
  if (pendingHistoryFailure !== null) {
    const showMessage = pendingHistoryFailure;
    pendingHistoryFailure = null;
    window.avEditHistoryFailed(showMessage);
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
  if (historyCard) newDraft();
  if (historyCard) historyCard = false;
  else setEditHistory("card", nid);
  window.avCloseBrowse(true);
};

window.avEditHistoryFailed = (showMessage = true) => {
  if (!historyCard) return;
  if (restoringHistory) {
    pendingHistoryFailure = showMessage;
    return;
  }
  historyCard = false;
  setEditHistory("editor", null, true);
  browseEvent("av-history", { view: "editor" });
  if (showMessage) browseEvent("av-history-failed");
};

window.avPrepareHistory = (event) => {
  const detail = event.detail;
  window.avBumpRev();
  if (detail.view === "card") {
    detail.path = `/card/${encodeURIComponent(detail.card)}`;
    return;
  }
  detail.path = window.avNid() ? "/reset" : null;
  detail.open = detail.view === "cards" &&
    !(browsing() && ["opening", "open"].includes(browsePhase()));
  if (detail.view !== "cards") window.avCloseBrowse(false);
};

window.avEditBack = (event) => {
  const inBrowse = browsing();
  const phase = browsePhase();
  const nid = window.avNid();
  const message = inBrowse || nid ? editWizard().dataset.discard : event.currentTarget.dataset.discard;
  if (busy() || phase === "closing" || phase === "returning") {
    event.preventDefault();
    return;
  }
  if (!inBrowse && !nid) {
    if (event.currentTarget.hasAttribute("href")) {
      window.avGuardNav(event, message);
    } else {
      event.preventDefault();
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (window.avConfirmDiscard(message)) window.location.assign("/app/");
    }
    return;
  }
  event.preventDefault();
  if (!inBrowse && !window.avConfirmDiscard(message)) return;
  const target = inBrowse ? editState?.avEditorIndex : editState?.avListIndex;
  if (Number.isSafeInteger(target) && target < editState.avIndex) {
    skipHistoryDiscard = true;
    history.go(target - editState.avIndex);
  } else {
    const view = inBrowse ? "editor" : "cards";
    setEditHistory(view, null, true);
    browseEvent("av-history", { view });
  }
};

window.addEventListener("popstate", (event) => {
  if (editHistoryView(location.href) === "cards") {
    if (staleDirection < 0 && validEditHistory(event.state) &&
        event.state.avIndex > editState.avIndex) staleDirection = 0;
    if (staleDirection > 0) {
      event.stopImmediatePropagation();
      staleDirection = 0;
      location.reload();
    }
    return;
  }
  if (!staleDrafts.has(event.state?.avDraft)) return;
  const delta = Math.sign(event.state.avIndex - editState.avIndex);
  const direction = arrivingStale ? 1 :
    (staleDirection < 0 && delta > 0 ? 1 : staleDirection || delta);
  if (!direction) return;
  staleDirection = direction;
  event.stopImmediatePropagation();
  if (direction > 0) setTimeout(() => {
    if (staleDirection > 0 && staleDrafts.has(history.state?.avDraft)) {
      staleDirection = 0;
      history.go(editState.avIndex - history.state.avIndex);
    }
  }, 200);
  history.go(direction);
}, true);

window.avEditPop = (event, message) => {
  const saving = busy();
  const inBrowse = browsing();
  const phase = browsePhase();
  if (arrivingStale) {
    if (editHistoryView(location.href) !== "cards" &&
        staleDrafts.has(event.state?.avDraft)) history.forward();
    else { arrivingStale = false; location.reload(); }
    return;
  }
  const nid = window.avNid();
  if (validEditHistory(event.state) && staleDrafts.has(event.state.avDraft) &&
      editHistoryView(location.href) !== "cards") {
    const direction = staleDirection || Math.sign(event.state.avIndex - editState.avIndex);
    if (direction) {
      staleDirection = direction;
      history.go(direction);
    }
    return;
  }
  staleDirection = 0;
  if (restoringHistory) {
    if (event.state?.avEdit && event.state.avIndex === editState.avIndex && location.href === editUrl) {
      finishHistoryRestore();
    } else {
      restoreEditHistory(event.state);
    }
    return;
  }
  if (pendingStepHistory) {
    stepRequest?.abort();
    pendingStepHistory = null;
  }
  const { view, card, step } = editUrlView();
  const sameDraft = view === "card" ? !inBrowse && Number(card) === nid :
    view === "editor" ? !inBrowse && !nid : false;
  const sameView = view === "cards" ? inBrowse && (phase === "opening" || phase === "open") :
    sameDraft && step === currentStep();
  const leaveList = view === "editor" && inBrowse && !nid && step !== currentStep();
  if (!saving && ((sameDraft && !sameView) || leaveList)) {
    pendingStepHistory = {
      state: validEditHistory(event.state) ? event.state : { avEdit: true, avIndex: 0 },
      url: location.href,
      leaveList,
    };
    window.avRequestStep(step, "history");
    return;
  }
  if (saving || (!sameView && !skipHistoryDiscard && !inBrowse &&
      !window.avConfirmDiscard(message))) {
    skipHistoryDiscard = false;
    restoreEditHistory(event.state);
    return;
  }
  skipHistoryDiscard = false;
  editUrl = location.href;
  editState = validEditHistory(event.state) ? event.state : { avEdit: true, avIndex: 0 };
  if (view === "editor" && staleDrafts.has(editState.avDraft)) newDraft();
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
  if (wizard.dataset.initialView === "cards") editState.avDraft = null;
  else {
    if (Number.isSafeInteger(editState.avDraft) && !staleDrafts.has(editState.avDraft)) {
      draftGeneration = Math.max(draftGeneration, editState.avDraft);
    } else {
      draftGeneration++;
    }
    editState.avDraft = draftGeneration;
    saveDraftHistory();
  }
  editUrl = editViewUrl(wizard.dataset.initialView, wizard.dataset.initialCard, wizard.dataset.initialStep);
  if (staleDrafts.has(history.state?.avDraft) && wizard.dataset.initialView !== "cards") {
    staleDirection = 1;
    arrivingStale = true;
    history.forward();
    return;
  }
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
  const listIndex = editState?.avListIndex;
  if (Number.isSafeInteger(listIndex) && listIndex < editState.avIndex) {
    pendingSavedList = true;
    history.go(listIndex - editState.avIndex);
    return;
  } else {
    setEditHistory("cards", null, true);
  }
  window.avOpenBrowse(document.getElementById("pile"), false);
};

window.avCloseBrowse = (editing = false, phase = browsePhase()) => {
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
  requestEditorFocus(() => {
    if (document.getElementById("add-wizard")?.dataset.browsePhase === "open") {
      document.getElementById("deck-cards")?.focus({ preventScroll: true });
    }
  });
};

window.avBrowseFocus = (editing) => {
  requestEditorFocus(() => {
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
  invalidateDraft();
  newDraft();
  setEditHistory("editor", null, true);
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

window.avFinishEditor = () => {
  if (editUrlView().view !== "cards") {
    invalidateDraft();
    newDraft();
    setEditHistory("editor", null, true);
  }
};

let summaryClosingForHistory = false;
window.avSummaryHistory = () => {
  const dialog = document.getElementById("add-summary");
  if (!dialog?.open) return;
  summaryClosingForHistory = true;
  dialog.close();
};

window.avSummaryClosed = (dialog) => {
  const placeholder = document.createElement("div");
  placeholder.hidden = true;
  const count = dialog.querySelector("#summary-count");
  if (count) placeholder.append(count);
  dialog.replaceWith(placeholder);
  if (summaryClosingForHistory) {
    summaryClosingForHistory = false;
    return;
  }
  editorFocusGeneration++;
  document.getElementById("edit-done")?.focus();
};

window.avSummaryKey = (event, dialog) => {
  if (event.key === "Escape") {
    event.stopPropagation();
    return;
  }
  if (event.key !== "Tab") return;
  const links = [...dialog.querySelectorAll("a[href]")];
  const first = links[0];
  const last = links.at(-1);
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
};
