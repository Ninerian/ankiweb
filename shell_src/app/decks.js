let deckOpener;
let deckWasOpen = false;

window.avDeckOpener = (element) => { deckOpener = element; };
window.avDeckFocus = (open) => {
  if (open === deckWasOpen) return;
  deckWasOpen = open;
  requestAnimationFrame(() => {
    if (open) {
      document.getElementById("deck-name")?.focus();
    } else {
      const target = deckOpener?.isConnected && deckOpener.getClientRects().length
        ? deckOpener : document.getElementById("btn-new-deck");
      target?.focus();
    }
  });
};

window.avDeckModalKey = (event) => {
  if (event.key !== "Tab") return;
  const dialog = event.currentTarget;
  const tabbable = (element) => element.getClientRects().length > 0 && (element.type !== "radio"
    || element.checked || !dialog.querySelector(`input[name="${element.name}"]:checked`));
  const controls = [...dialog.querySelectorAll("button:not([disabled]), input:not([disabled])")]
    .filter(tabbable);
  if (!controls.length) return;
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
};

document.addEventListener("change", (event) => {
  if (!(event.target instanceof HTMLInputElement) || !event.target.name.startsWith("deck-emoji")) return;
  const preview = document.getElementById("preview-emoji");
  if (!preview) return;
  preview.classList.remove("emoji-pop");
  void preview.offsetWidth;
  preview.classList.add("emoji-pop");
});
