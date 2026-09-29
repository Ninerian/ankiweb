(() => {
  // Queue for sequential modal execution
  const queue = [];
  let isShowing = false;

  let modalEl = null;
  let bsModal = null;
  let modalTitle = null;
  let modalBody = null;
  let modalInput = null;
  let modalCancelBtn = null;
  let modalOkBtn = null;
  let modalForm = null;

  function ensureModal() {
    if (modalEl) return;
    modalEl = document.createElement('div');
    modalEl.id = 'ankiwebDialogModal';
    modalEl.className = 'modal fade';
    modalEl.tabIndex = -1;
    modalEl.setAttribute('role', 'dialog');
    modalEl.setAttribute('aria-labelledby', 'ankiwebDialogTitle');
    modalEl.setAttribute('aria-hidden', 'true');

    modalEl.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title" id="ankiwebDialogTitle"></h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <form id="ankiwebDialogForm">
            <div class="modal-body">
              <div id="ankiwebDialogMessage" class="mb-2 text-break"></div>
              <input type="text" id="ankiwebDialogInput" class="form-control" autocomplete="off">
            </div>
            <div class="modal-footer">
              <button type="button" id="ankiwebDialogCancelBtn" class="btn btn-secondary" data-bs-dismiss="modal"></button>
              <button type="submit" id="ankiwebDialogOkBtn" class="btn btn-primary"></button>
            </div>
          </form>
        </div>
      </div>
    `;

    document.body.appendChild(modalEl);

    modalTitle = modalEl.querySelector('#ankiwebDialogTitle');
    modalBody = modalEl.querySelector('#ankiwebDialogMessage');
    modalInput = modalEl.querySelector('#ankiwebDialogInput');
    modalCancelBtn = modalEl.querySelector('#ankiwebDialogCancelBtn');
    modalOkBtn = modalEl.querySelector('#ankiwebDialogOkBtn');
    modalForm = modalEl.querySelector('#ankiwebDialogForm');

    bsModal = new bootstrap.Modal(modalEl, {
      backdrop: true,
      keyboard: true,
      focus: true
    });
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
      modalOkBtn.className = 'btn btn-danger';
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
      modalEl.removeEventListener('shown.bs.modal', onShown);
      modalEl.removeEventListener('hidden.bs.modal', onHidden);
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

      bsModal.hide();
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

    modalEl.addEventListener('shown.bs.modal', onShown, { once: true });
    modalEl.addEventListener('hidden.bs.modal', onHidden, { once: true });
    if (modalForm) modalForm.addEventListener('submit', onSubmit);
    if (modalOkBtn) modalOkBtn.addEventListener('click', onOkClick);

    bsModal.show();
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
