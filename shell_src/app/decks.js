let deckOpener = null;
const deckDialogs = new Map();

const isVisible = (element) => element?.isConnected
  && !element.closest("[hidden], [inert]")
  && element.getClientRects().length > 0
  && getComputedStyle(element).visibility === "visible";

window.avDeckOpener = (element) => { deckOpener = element; };
window.avDeckFocus = (open, dialogId = "deck-sheet", focusId = "deck-name") => {
  const state = deckDialogs.get(dialogId) ?? { open: false, opener: null, openerId: "" };
  deckDialogs.set(dialogId, state);
  if (state.open === open) return;
  state.open = open;
  if (open) {
    state.opener = deckOpener;
    state.openerId = deckOpener?.id ?? "";
  }
  requestAnimationFrame(() => {
    if (state.open !== open) return;
    if (open) {
      const target = document.getElementById(focusId);
      if (isVisible(target)) target.focus();
    } else {
      const replacement = state.openerId && document.getElementById(state.openerId);
      const target = isVisible(state.opener) ? state.opener
        : isVisible(replacement) ? replacement : document.getElementById("btn-new-deck");
      target?.focus();
    }
  });
};

window.avDeckModalKey = (event) => {
  if (event.key !== "Tab") return;
  const dialog = event.currentTarget;
  const visible = [...dialog.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [tabindex]")]
    .filter((element) => element.tabIndex >= 0 && !element.matches(":disabled") && isVisible(element));
  const radioGroups = new Map();
  for (const element of visible) {
    if (element.type !== "radio" || !element.name) continue;
    const current = radioGroups.get(element.name);
    if (!current || element.checked) radioGroups.set(element.name, element);
  }
  const controls = visible.filter((element) => element.type !== "radio" || !element.name
    || radioGroups.get(element.name) === element);
  if (!controls.length) return;
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (!dialog.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
};

window.avDeckMenuButtonKey = (event) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const menu = document.getElementById(event.currentTarget.getAttribute("popovertarget"));
  if (!menu) return;
  event.preventDefault();
  if (!menu.matches(":popover-open")) menu.showPopover();
  const items = [...menu.querySelectorAll('[role="menuitem"]:not(:disabled)')];
  (event.key === "ArrowUp" ? items.at(-1) : items[0])?.focus();
};

window.avDeckMenuKey = (event) => {
  const menu = event.currentTarget;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    menu.hidePopover();
    menu.previousElementSibling?.focus();
    return;
  }
  if (event.key === "Tab") {
    menu.hidePopover();
    return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  const items = [...menu.querySelectorAll('[role="menuitem"]:not(:disabled)')];
  if (!items.length) return;
  event.preventDefault();
  const current = items.indexOf(document.activeElement);
  const index = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
    : event.key === "ArrowDown" ? (current + 1) % items.length
      : (current <= 0 ? items.length - 1 : current - 1);
  items[index].focus();
};

document.addEventListener("change", (event) => {
  if (!(event.target instanceof HTMLInputElement)) return;
  const previewId = event.target.name.startsWith("new-emoji-") ? "preview-emoji"
    : event.target.name.startsWith("set-emoji-") ? "settings-preview-emoji" : null;
  if (!previewId) return;
  const preview = document.getElementById(previewId);
  if (!preview) return;
  preview.classList.remove("emoji-pop");
  void preview.offsetWidth;
  preview.classList.add("emoji-pop");
});
