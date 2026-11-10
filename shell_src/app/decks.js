window.avDeckDialogClosed = (dialog) => {
  dialog.remove();
  if (document.activeElement === document.body) {
    document.getElementById("btn-new-deck")?.focus();
  }
};

window.avDeckEmojiTab = (tab) => {
  const form = tab.closest("form");
  if (!form) return;
  for (const sibling of form.querySelectorAll('[role="tab"][aria-controls]')) {
    const selected = sibling === tab;
    sibling.setAttribute("aria-selected", String(selected));
    const panel = document.getElementById(sibling.getAttribute("aria-controls"));
    if (panel) panel.hidden = !selected;
  }
};

window.avDeckSwapLanguages = (button) => {
  const form = button.closest("form");
  const src = form?.querySelector('select[name="src"]');
  const dst = form?.querySelector('select[name="dst"]');
  if (!src || !dst) return;
  [src.value, dst.value] = [dst.value, src.value];
  src.dispatchEvent(new Event("input", { bubbles: true }));
};

window.avDeckPickFlag = (button) => {
  const form = button.closest("form");
  const radio = [...(form?.querySelectorAll('input[name="emoji"]') ?? [])]
    .find((input) => input.value === button.dataset.flag);
  if (!radio) return;
  radio.checked = true;
  const panel = radio.closest('[role="radiogroup"]');
  const tab = [...form.querySelectorAll('[role="tab"][aria-controls]')]
    .find((item) => item.getAttribute("aria-controls") === panel?.id);
  if (tab) {
    window.avDeckEmojiTab(tab);
    tab.focus();
  }
  radio.dispatchEvent(new Event("input", { bubbles: true }));
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

document.addEventListener("input", (event) => {
  if (!(event.target instanceof HTMLInputElement) || event.target.name !== "emoji") return;
  const form = event.target.form;
  const previewId = form?.id === "deck-create-form" ? "preview-emoji"
    : form?.id === "deck-settings-form" ? "settings-preview-emoji" : null;
  const preview = document.getElementById(previewId);
  if (!preview) return;
  preview.classList.remove("emoji-pop");
  void preview.offsetWidth;
  preview.classList.add("emoji-pop");
});

// Keep native scrolling while drawing a transient overlay outside its content box.
const deckScroll = document.getElementById("deck-scroll");
const deckScrollFrame = document.getElementById("deck-scroll-frame");
const deckScrollbar = document.getElementById("deck-scrollbar");
const deckThumb = document.getElementById("deck-scrollbar-thumb");
if (deckScroll && deckScrollFrame && deckScrollbar && deckThumb
    && window.ResizeObserver && window.MutationObserver && window.PointerEvent
    && (CSS.supports("scrollbar-width", "none")
      || "WebkitAppearance" in document.documentElement.style)) {
  let hideTimer;
  let drag = null;
  let updateFrame = 0;

  const updateScrollbar = () => {
    const height = deckScroll.clientHeight;
    const maxScroll = deckScroll.scrollHeight - height;
    deckScrollbar.hidden = maxScroll <= 0 || height <= 0;
    if (deckScrollbar.hidden) {
      clearTimeout(hideTimer);
      deckScrollFrame.removeAttribute("data-scroll-active");
      drag = null;
      return;
    }
    const thumbHeight = Math.min(height, Math.max(24, height * height / deckScroll.scrollHeight));
    const travel = height - thumbHeight;
    deckThumb.style.height = `${thumbHeight}px`;
    deckThumb.style.transform = `translateY(${travel * deckScroll.scrollTop / maxScroll}px)`;
  };
  const scheduleUpdate = () => {
    if (updateFrame) return;
    updateFrame = requestAnimationFrame(() => {
      updateFrame = 0;
      updateScrollbar();
    });
  };
  const hideAfterIdle = () => {
    clearTimeout(hideTimer);
    if (!drag) {
      hideTimer = setTimeout(() => deckScrollFrame.removeAttribute("data-scroll-active"), 1000);
    }
  };
  const showScrollbar = () => {
    updateScrollbar();
    if (deckScrollbar.hidden) return;
    deckScrollFrame.setAttribute("data-scroll-active", "");
    hideAfterIdle();
  };
  const resizeObserver = new ResizeObserver(scheduleUpdate);
  const observeSizes = () => {
    resizeObserver.disconnect();
    resizeObserver.observe(deckScroll);
    for (const child of deckScroll.children) resizeObserver.observe(child);
    scheduleUpdate();
  };
  const mutationObserver = new MutationObserver(observeSizes);
  mutationObserver.observe(deckScroll, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"],
  });
  observeSizes();
  deckScroll.addEventListener("scroll", showScrollbar, { passive: true });

  const moveThumb = (event) => {
    const track = deckScrollbar.getBoundingClientRect();
    const thumbHeight = deckThumb.offsetHeight;
    const travel = track.height - thumbHeight;
    if (travel > 0) {
      const position = Math.max(0, Math.min(travel, event.clientY - track.top - drag.offset));
      deckScroll.scrollTop = position / travel * (deckScroll.scrollHeight - deckScroll.clientHeight);
    }
  };
  deckScrollbar.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || drag) return;
    event.preventDefault();
    const thumb = deckThumb.getBoundingClientRect();
    drag = {
      pointerId: event.pointerId,
      offset: event.target === deckThumb ? event.clientY - thumb.top : thumb.height / 2,
    };
    deckScrollbar.setPointerCapture(event.pointerId);
    showScrollbar();
    moveThumb(event);
  });
  deckScrollbar.addEventListener("pointermove", (event) => {
    if (drag?.pointerId === event.pointerId) moveThumb(event);
  });
  const endDrag = (event) => {
    if (drag?.pointerId !== event.pointerId) return;
    drag = null;
    hideAfterIdle();
  };
  deckScrollbar.addEventListener("pointerup", endDrag);
  deckScrollbar.addEventListener("pointercancel", endDrag);
  deckScrollbar.addEventListener("lostpointercapture", endDrag);
  deckScrollFrame.classList.add("scrollbar-enhanced");
}
