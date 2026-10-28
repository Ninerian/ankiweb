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
