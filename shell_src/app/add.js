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
  if (event.shiftKey) return;

  const next = document.getElementById("btn-next");
  if (!next || getComputedStyle(next).display === "none" || next.disabled) return;
  event.preventDefault();
  next.click();
};

window.avConfirmDiscard = (front, back, hint, example, saving, message) =>
  saving || ![front, back, hint, example].some(Boolean) || window.confirm(message);

window.avGuardNav = (event, front, back, hint, example, saving, message) => {
  if (!window.avConfirmDiscard(front, back, hint, example, saving, message)) {
    event.preventDefault();
  }
};

let toastTimer;
window.avAddToast = (message) => {
  const toast = document.getElementById("add-toast");
  if (!toast) return;
  toast.querySelector(".alert").textContent = message;
  toast.style.display = "grid";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.display = "none"; }, 4000);
};

window.avEditLoaded = (hint, example) => {
  for (const [id, value] of [["input-hint", hint], ["input-example", example]]) {
    const details = document.getElementById(id)?.closest("details");
    if (details && value) details.open = true;
  }
  const wizard = document.getElementById("add-wizard");
  window.avAddToast(wizard.dataset.editing);
  window.avFocus("input-front");
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
    [document.querySelector("#hud-count button"), "animate-added-pill-pop"],
  ];
  for (const [element, name] of animations) element?.classList.remove(name);
  // Restart CSS animations even when morphing retains the same elements.
  void editor.offsetWidth;
  for (const [element, name] of animations) element?.classList.add(name);
};

window.avLastNoteId = () =>
  document.querySelector("#added-cards [data-note-id]")?.dataset.noteId;

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
