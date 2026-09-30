// Port of ts/reviewer/browser_selector.ts: tag <html> with platform/browser classes so
// upstream card CSS (e.g. `.mac .foo`, `.mobile .bar`) works unchanged. Applied
// synchronously from <head>, before <body> renders, exactly like upstream.
export function addBrowserClasses(): void {
  const ua = navigator.userAgent.toLowerCase();
  const el = document.documentElement;

  if (/ipad/.test(ua)) el.classList.add("ipad");
  else if (/iphone/.test(ua)) el.classList.add("iphone");
  else if (/android/.test(ua)) el.classList.add("android");

  if (/ipad|iphone|ipod/.test(ua)) el.classList.add("ios");

  if (/ipad|iphone|ipod|android/.test(ua)) el.classList.add("mobile");
  else if (/linux/.test(ua)) el.classList.add("linux");
  else if (/windows/.test(ua)) el.classList.add("win");
  else if (/mac/.test(ua)) el.classList.add("mac");

  if (/firefox\//.test(ua)) el.classList.add("firefox");
  else if (/chrome\//.test(ua)) el.classList.add("chrome");
  else if (/safari\//.test(ua)) el.classList.add("safari");
}
