(() => {
  // Queue for sequential modal execution
  const queue = [];
  let isShowing = false;

  let modalEl = null;
  let modalTitle = null;
  let modalBody = null;
  let modalInput = null;
  let modalCancelBtn = null;
  let modalOkBtn = null;
  let modalForm = null;

  function ensureModal() {
    if (modalEl) return;
    modalEl = document.createElement('dialog');
    modalEl.id = 'ankiwebDialogModal';
    modalEl.className = 'modal';
    modalEl.setAttribute('aria-labelledby', 'ankiwebDialogTitle');

    modalEl.innerHTML = `
      <div class="modal-box">
        <form method="dialog">
          <button class="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" aria-label="Close">\u2715</button>
        </form>
        <h3 class="text-lg font-bold" id="ankiwebDialogTitle"></h3>
        <form id="ankiwebDialogForm" class="flex flex-col gap-3 py-4">
          <div id="ankiwebDialogMessage" class="break-words"></div>
          <input type="text" id="ankiwebDialogInput" class="input w-full" autocomplete="off">
          <div class="modal-action">
            <button type="button" id="ankiwebDialogCancelBtn" class="btn"></button>
            <button type="submit" id="ankiwebDialogOkBtn" class="btn btn-primary"></button>
          </div>
        </form>
      </div>
      <form method="dialog" class="modal-backdrop"><button aria-label="Close">close</button></form>
    `;

    document.body.appendChild(modalEl);

    modalTitle = modalEl.querySelector('#ankiwebDialogTitle');
    modalBody = modalEl.querySelector('#ankiwebDialogMessage');
    modalInput = modalEl.querySelector('#ankiwebDialogInput');
    modalCancelBtn = modalEl.querySelector('#ankiwebDialogCancelBtn');
    modalOkBtn = modalEl.querySelector('#ankiwebDialogOkBtn');
    modalForm = modalEl.querySelector('#ankiwebDialogForm');
  }

  function getLabels() {
    const custom = window.__ankiwebDialogLabels || {};
    return {
      ok: custom.ok || 'OK',
      cancel: custom.cancel || 'Cancel',
      title: custom.title || 'AnkiWeb'
    };
  }

  function processQueue() {
    if (isShowing || queue.length === 0) return;
    isShowing = true;
    const task = queue.shift();
    runDialog(task);
  }

  function runDialog({ type, message, defaultValue, options, resolve }) {
    ensureModal();

    const opener = document.activeElement;
    const labels = getLabels();
    let settled = false;
    let resultValue;

    modalTitle.textContent = (options && options.title) || labels.title;
    modalBody.textContent = message || '';

    // Reset button styling
    modalOkBtn.className = 'btn btn-primary';
    if (options && options.danger) {
      modalOkBtn.className = 'btn btn-error';
    }

    const okLabel = (options && options.okLabel) || labels.ok;
    const cancelLabel = (options && options.cancelLabel) || labels.cancel;
    modalOkBtn.textContent = okLabel;
    modalCancelBtn.textContent = cancelLabel;

    if (type === 'alert') {
      modalInput.style.display = 'none';
      modalCancelBtn.style.display = 'none';
    } else if (type === 'confirm') {
      modalInput.style.display = 'none';
      modalCancelBtn.style.display = '';
    } else if (type === 'prompt') {
      modalInput.style.display = '';
      modalInput.value = defaultValue != null ? String(defaultValue) : '';
      modalCancelBtn.style.display = '';
    }

    function cleanup() {
      modalEl.removeEventListener('close', onHidden);
      modalCancelBtn.removeEventListener('click', onCancelClick);
      if (modalForm) modalForm.removeEventListener('submit', onSubmit);
      if (modalOkBtn) modalOkBtn.removeEventListener('click', onOkClick);
    }

    function onShown() {
      if (type === 'prompt') {
        modalInput.focus();
        modalInput.select();
      } else {
        modalOkBtn.focus();
      }
    }

    function onCancelClick() {
      modalEl.close();
    }

    function onHidden() {
      cleanup();
      if (!settled) {
        settled = true;
        if (type === 'alert') resultValue = undefined;
        else if (type === 'confirm') resultValue = false;
        else if (type === 'prompt') resultValue = null;
      }
      if (opener && typeof opener.focus === 'function') {
        try { opener.focus(); } catch (e) {}
      }
      resolve(resultValue);
      isShowing = false;
      setTimeout(processQueue, 0);
    }

    function finishSubmit() {
      if (settled) return;
      settled = true;
      if (type === 'alert') resultValue = undefined;
      else if (type === 'confirm') resultValue = true;
      else if (type === 'prompt') resultValue = modalInput.value;

      modalEl.close();
    }

    function onSubmit(e) {
      if (e && e.preventDefault) e.preventDefault();
      finishSubmit();
    }

    function onOkClick(e) {
      // In case click does not trigger submit in some browser automation contexts
      if (e && e.preventDefault) e.preventDefault();
      finishSubmit();
    }

    modalEl.addEventListener('close', onHidden, { once: true });
    modalCancelBtn.addEventListener('click', onCancelClick);
    if (modalForm) modalForm.addEventListener('submit', onSubmit);
    if (modalOkBtn) modalOkBtn.addEventListener('click', onOkClick);

    modalEl.showModal();
    onShown();
  }

  window.ankiwebPrompt = function(message, defaultValue = '') {
    return new Promise((resolve) => {
      queue.push({ type: 'prompt', message, defaultValue, resolve });
      processQueue();
    });
  };

  window.ankiwebConfirm = function(message, options = {}) {
    return new Promise((resolve) => {
      queue.push({ type: 'confirm', message, options, resolve });
      processQueue();
    });
  };

  window.ankiwebAlert = function(message, options = {}) {
    return new Promise((resolve) => {
      queue.push({ type: 'alert', message, options, resolve });
      processQueue();
    });
  };
})();
