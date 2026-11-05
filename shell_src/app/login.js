const form = document.getElementById("login");
const input = document.getElementById("password");
const peek = form?.querySelector(".login-peek");
const emoji = form?.querySelector(".login-mascot-emoji");

if (form && input && peek && emoji) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let visualTimer;
  let lastErrorKind = form.dataset.errorKind;
  let lastInputType = input.type;

  const cancelVisualTimer = () => {
    clearTimeout(visualTimer);
    visualTimer = undefined;
  };

  const setEmoji = (value) => {
    if (emoji.textContent === value) return;
    emoji.textContent = value;
    if (reducedMotion.matches) return;
    emoji.classList.remove("login-mascot-emoji");
    void emoji.offsetWidth;
    emoji.classList.add("login-mascot-emoji");
  };

  const setIdleEmoji = () => {
    if (form.dataset.errorKind) return;
    setEmoji(input.value === "" ? "🔐" : input.type === "text" ? "👀" : "🤫");
  };

  const showError = (kind) => {
    cancelVisualTimer();
    setEmoji(kind === "empty" ? "🙈" : "🙅");
    if (!reducedMotion.matches) {
      form.classList.remove("is-shaking");
      void form.offsetWidth;
      form.classList.add("is-shaking");
    }
    input.focus();
    input.select();
  };

  const observer = new MutationObserver(() => {
    const kind = form.dataset.errorKind;
    if (kind === lastErrorKind) return;
    lastErrorKind = kind;
    if (kind === "empty" || kind === "wrong") showError(kind);
  });
  observer.observe(form, { attributes: true, attributeFilter: ["data-error-kind"] });
  const typeObserver = new MutationObserver(() => {
    if (input.type === lastInputType) return;
    lastInputType = input.type;
    cancelVisualTimer();
    setIdleEmoji();
  });
  typeObserver.observe(input, { attributes: true, attributeFilter: ["type"] });

  if (lastErrorKind === "empty" || lastErrorKind === "wrong") showError(lastErrorKind);

  input.addEventListener("input", () => {
    cancelVisualTimer();
    visualTimer = setTimeout(() => {
      visualTimer = undefined;
      setIdleEmoji();
    }, 200);
  });

  form.addEventListener("submit", () => {
    cancelVisualTimer();
    // Datastar clears the error during this event; do not let an old input timer
    // overwrite a later server response.
  });

  peek.addEventListener("click", cancelVisualTimer);
}
