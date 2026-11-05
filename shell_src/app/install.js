const installButton = document.getElementById("install-app");
const iosHint = document.getElementById("ios-install-hint");
const iosDismiss = document.getElementById("ios-install-dismiss");
const dismissalKey = "app-ios-install-dismissed";
let installPrompt = null;

function hide(element) {
  const hadFocus = element.contains(document.activeElement);
  element.hidden = true;
  if (hadFocus) document.getElementById("btn-new-deck")?.focus();
}

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  installButton.hidden = false;
});

installButton.addEventListener("click", async () => {
  if (!installPrompt) return;
  const prompt = installPrompt;
  installPrompt = null;
  try {
    let result;
    try {
      result = prompt.prompt();
    } finally {
      hide(installButton);
    }
    await result;
  } catch (error) {
    console.warn("install prompt failed", error);
  }
});

window.addEventListener("appinstalled", () => {
  installPrompt = null;
  hide(installButton);
  hide(iosHint);
});

const userAgent = navigator.userAgent;
const isIOS = /iPhone|iPad|iPod/.test(userAgent)
  || (/Mac/i.test(navigator.platform) && navigator.maxTouchPoints > 0);
const isSafari = /Version\/[\d.]+.*Safari\//.test(userAgent)
  && !/CriOS|FxiOS|EdgiOS|OPiOS|DuckDuckGo|GSA|YaBrowser/i.test(userAgent);
const isStandalone = navigator.standalone
  || window.matchMedia?.("(display-mode: standalone)").matches;
let dismissed = false;
try {
  dismissed = sessionStorage.getItem(dismissalKey) === "1";
} catch {
  // Storage may be unavailable; the hint remains dismissible for this page.
}
if (isIOS && isSafari && !isStandalone && !dismissed) iosHint.hidden = false;

iosDismiss.addEventListener("click", () => {
  hide(iosHint);
  try {
    sessionStorage.setItem(dismissalKey, "1");
  } catch {
    // Keep the hint hidden even when storage is unavailable.
  }
});
