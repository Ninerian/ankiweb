// The server owns cards and ratings; this module handles only presentation.
const focusable = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const streakVersions = new WeakMap();
const focusedCompletions = new WeakSet();
let sheetWasOpen = false;
let sheetHadFocus = false;

function highlightExamples(root) {
  for (const example of root.querySelectorAll('.av-example')) {
    const walker = document.createTreeWalker(example, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (node.parentElement?.closest('mark, script, style')) continue;
      const text = node.nodeValue;
      const pattern = /\*([^*\n]+)\*/g;
      let match = pattern.exec(text);
      if (!match) continue;
      const fragment = document.createDocumentFragment();
      let position = 0;
      do {
        fragment.append(document.createTextNode(text.slice(position, match.index)));
        const mark = document.createElement('mark');
        mark.textContent = match[1];
        fragment.append(mark);
        position = match.index + match[0].length;
        match = pattern.exec(text);
      } while (match);
      fragment.append(document.createTextNode(text.slice(position)));
      node.replaceWith(fragment);
    }
  }
}

window.avKeydown = (event, revealed, sheetOpen) => {
  if (sheetOpen || event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest('a, button, input, textarea, select, [contenteditable]')) return;
  if ((event.key === ' ' || event.key === 'Spacebar') && !revealed) {
    const button = document.getElementById('btn-show-ans');
    if (button) { event.preventDefault(); button.click(); }
  } else if (revealed && /^[1-4]$/.test(event.key)) {
    const button = document.getElementById(`ease-${event.key}`);
    if (button) { event.preventDefault(); button.click(); }
  }
};

window.avSheetKey = (event) => {
  if (event.key !== 'Tab') return;
  const sheet = document.getElementById('sheet');
  if (!sheet?.classList.contains('modal-open')) return;
  const controls = [...sheet.querySelectorAll(focusable)].filter((element) => element.getClientRects().length && !element.closest('[inert]'));
  if (!controls.length) { event.preventDefault(); return; }
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && (document.activeElement === first || !sheet.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !sheet.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
};

window.avFocusComplete = () => document.getElementById('sc-title')?.focus();

document.addEventListener('focusin', (event) => {
  if (document.getElementById('sheet')?.contains(event.target)) sheetHadFocus = true;
});

document.addEventListener('datastar-fetch', (event) => {
  // Datastar v1 dispatches the HTTP status as argsRaw.status on error.
  if (event.detail?.type === 'error' && event.detail.argsRaw?.status === '409') window.location.reload();
});

function syncReview() {
  const root = document.getElementById('review-app');
  if (!root) return;
  highlightExamples(root);
  const sheet = document.getElementById('sheet');
  const open = !!sheet?.classList.contains('modal-open');
  if (open && !sheetWasOpen) {
    sheetHadFocus = false;
    sheet.querySelector(focusable)?.focus();
  } else if (!open && sheetWasOpen && sheetHadFocus) {
    document.getElementById('btn-actions-sheet')?.focus();
    sheetHadFocus = false;
  }
  sheetWasOpen = open;
  const title = document.getElementById('sc-title');
  if (title && !focusedCompletions.has(title)) {
    focusedCompletions.add(title);
    window.avFocusComplete();
  }
  const badge = document.getElementById('streak-pill');
  if (badge) {
    const version = badge.dataset.ts;
    const previous = streakVersions.get(badge);
    streakVersions.set(badge, version);
    if (previous !== undefined && previous !== version) {
      const animation = ['animate-streak-pop', 'animate-streak-reset'].find((name) => badge.classList.contains(name));
      if (animation) {
        badge.classList.remove(animation);
        void badge.offsetWidth;
        badge.classList.add(animation);
      }
    }
  }
}

let scheduled = false;
const observer = new MutationObserver(() => {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => { scheduled = false; syncReview(); });
});
observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'data-mood', 'data-ts'] });
syncReview();
