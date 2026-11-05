# Research: PWA Client for Smartphones, and Fit with the Current Stack

**Question**: What is needed for a smartphone PWA client, and does it work with the ankiweb stack?
**Scope**: research only. No project code changed. Nothing was built or tested on a phone.
**Evidence legend**: **belegt** = read in project files or stated by a source; **ungeprüft** = not tested here; **[INFERENCE]** = my conclusion, not directly observed.

---

## 1. Short answer

**The main blocker is HTTPS, not the manifest.** Service workers (and therefore installability on Android) need a secure context: `localhost` is exempt, a LAN IP over plain HTTP is not. The default deployment is plain HTTP on localhost/LAN, so a phone cannot install the app until a TLS endpoint (reverse proxy or tunnel) exists.

With HTTPS in place, a PWA wrapper (manifest, icons, service worker) is **feasible** with this stack and mostly additive. An **offline** PWA is a separate and much larger task: the collection lives only on the server and every card action goes through the server, so offline studying needs a new client-side data store plus a sync/conflict strategy. That is a design decision, not a PWA feature.

**Scope note**: this research covers the ankiweb stack (FastAPI/Jinja/Datastar). It does not cover the standalone mockups in `design/reviewer-redesign/` (`mockup.html`, `editor-mockup.html`, `decks-mockup.html`), which are static prototypes that are not yet ported into the Jinja templates (see `DESIGN.md` §4).

## 2. Relevant facts about the current stack (belegt, from the repo)

| Fact | Where |
|---|---|
| Backend: FastAPI + uvicorn, official `anki` Python package (Rust backend), Jinja templates, Datastar, Tailwind 4 + daisyUI 5 | `README.md`, `pyproject.toml` |
| Single-user, one collection on the server | `README.md` |
| Collection access is serialized on the server (asyncio lock + executor) | `adapters/outbound/anki_collection_adapter.py` |
| No client-side copy of cards or scheduling state | repo search: no IndexedDB/offline code found |
| No PWA scaffolding exists: no web manifest, no service worker, no apple-touch-icon, no theme-color in `ankiweb/`, `shell_src/`, `docs/`. The one grep hit is a substring match inside vendored `ankiweb/web_assets/js/editor.js` (not opened, not a manifest or service worker) | grep |
| `viewport` meta present in `shell.html.jinja` and `login.html.jinja` | grep |
| Reviewer uses a WebSocket bridge `/ws`; other pages use plain HTTP/Datastar. Only the native reviewer enables the bridge | `http_shared/page.py`, `ws_bridge/ws.py` |
| Host-header (DNS-rebinding) guard: only `localhost` allowed unless `ANKIWEB_ALLOWED_HOSTS` lists the host. Applied to HTTP and to `/ws` | `core/config.py`, `app.py`, `ws.py` |
| Optional password: session cookie, `httponly`, `samesite=lax`, 30 days; **no `secure` flag set** | `app.py` |
| Docker binds to `127.0.0.1` by default; LAN needs ports edited plus `ANKIWEB_ALLOWED_HOSTS` | `DOCKER.md` |
| README calls auth a "light gate for LAN use ... serve over HTTPS if it matters" | `README.md` |
| Static caching: `max-age=86400` for vendored css/js, one year for immutable/fonts | `assets.py` |
| Sync (AnkiWeb) is out of scope by design | `README.md` |

## 3. What a PWA needs (from sources, not tested here)

**Installable on Android/Chrome** (web.dev, MDN, Lighthouse results; belegt per search summary):
- Served over HTTPS, or from `localhost`.
- Web app manifest with `name` or `short_name`, `icons` including 192x192 and 512x512, `start_url`, and `display` of `standalone`, `fullscreen` or `minimal-ui`; `prefer_related_applications` must not be true.
- A registered service worker is reported as needed for Chrome's install prompt in current versions; a minimal pass-through worker is said to be enough (a GitHub discussion; MDN states a service worker is not strictly required for installability, so the sources disagree on this). **Treat as ungeprüft.**
- Chrome fires `beforeinstallprompt` only after user interaction and some time on the page.

**iOS / Safari** (TapPWA, Synthetixis, MobiLoud; secondary sources, belegt per search summary only):
- Install is manual: Share sheet -> Add to Home Screen.
- Web push (iOS 16.4+) works only for the home-screen instance and needs manifest plus service worker.
- Storage: the 7-day ITP eviction is described as not applying automatically to installed PWAs, but one source describes a roughly two-week idle clear for Cache Storage and IndexedDB. **The sources conflict; ungeprüft.**
- Storage quotas (secondary source, a blog, not Apple): Cache Storage about 50 MB, IndexedDB up to about 500 MB or half of free disk. **ungeprüft.**
- Manifest `shortcuts` and Web Share Target are not supported (one source).

**Secure context** (MDN/Workbox/Chromium results, belegt per search summary):
- Service workers run only in secure contexts. `localhost` is exempt. A **LAN IP over plain HTTP is not**, so a phone reaching `http://192.168.x.x:8000` cannot register a service worker and cannot install a PWA.
- Workarounds named: HTTPS with a (self-signed or trusted) certificate, or a Chrome flag for test devices only.

## 4. Fit with the stack

| Requirement | Fits? | Why |
|---|---|---|
| Manifest + icons + theme-color | Yes, additive | Static files and a `<link>` in `shell.html.jinja`. Nothing conflicts. **[INFERENCE]** |
| Service worker | Yes, but scope matters | Must be served from a path that covers the app (root scope). Needs a route on the FastAPI app; current static mounts do not obviously give root scope. **[INFERENCE, ungeprüft]** |
| HTTPS | **Needs work** | Default deployment is plain HTTP on localhost/LAN. A phone needs an HTTPS origin: reverse proxy (e.g. Caddy/nginx) or a tunnel. The repo does not ship one. **[INFERENCE]** |
| Host guard | Needs config | The phone's hostname must be in `ANKIWEB_ALLOWED_HOSTS`. With a public/proxy hostname this is straightforward; `*` disables the protection. |
| Cookie auth | Works, weaker than it should be | Under HTTPS the session cookie should get `secure=True`; today it does not. The 30-day cookie also survives PWA restarts, which helps the install experience. |
| WebSocket `/ws` (reviewer) | Likely fine behind a proxy | Needs the proxy to pass WebSocket upgrades and to forward a Host that passes the guard. Not tested. **[INFERENCE]** |
| Offline studying | **No** | No client data store. Server owns the collection, scheduling runs in the Rust backend, and every rating goes through RPC. **[INFERENCE]**: caching the HTML would show a page that cannot rate cards. Offline needs a new client-side copy of the collection and a sync/conflict strategy, which is the largest effort item. |
| Sync of offline reviews back | **Not available** | Sync is out of scope by design. A client-side queue of ratings would need a new API, conflict rules and a replay path. |
| Caching static assets | Easy | Already long-lived `Cache-Control`. A service worker could precache the shell and vendored bundles for faster starts. |
| Push notifications | Partly exists server-side | There is a "deck push notification" config (`/extra_actions/setNotifyConfig`, an outgoing URL poll). That is not Web Push; browser push would need VAPID keys, subscription storage and a service-worker handler. Not investigated further. |

## 5. Scenarios

1. **Installable shell, online only** (smallest): manifest, icons, minimal service worker, HTTPS via reverse proxy, `secure` cookie. Result: home-screen icon, standalone window, faster asset loading. Study still needs a network connection to the server. Reasonable fit.
2. **Shell + app-shell caching**: as above, with the service worker precaching the shell and vendored assets. Offline shows a clear "server unreachable" state instead of a browser error page. Moderate effort.
3. **Offline study**: requires a client-side card store (IndexedDB), a local scheduler or deferred rating queue, and a reconciliation API. Conflicts with the current architecture (server-owned collection, no sync). Large effort and a design decision, not a PWA feature.
4. **Native wrapper** (Capacitor or similar) is an alternative for push and storage guarantees, but was not researched here.

## 6. Open questions / ungeprüft

- Whether a service worker is required for installability in current Chrome (sources disagree).
- iOS storage eviction behaviour for installed PWAs (sources disagree).
- Whether the existing FastAPI static mounts can serve a service worker with root scope.
- Behaviour of `/ws` through a TLS reverse proxy and the Host guard.
- Whether the daisyUI/Tailwind shell layout works well in standalone display mode (safe areas, notch). Not checked.
- Interaction of the vendored `reviewer.js` and `editor.js` with a service worker cache (they set their own caching headers).
- Whether the standalone mockups in `design/reviewer-redesign/` are intended to replace the Jinja pages. They are separate static prototypes; their integration with the real stack is described in `DESIGN.md` §4 and is not covered by this research.
- Whether the vendored SvelteKit pages (deck options, card info, graphs, etc.) behave well in standalone mode or behind a service worker. Not examined.

## 7. Suggested next step if pursued

Decide the target first: online-only installable app (scenario 1 or 2) or offline study (scenario 3). They are different projects. For scenario 1 a small spike would answer most open points: add a manifest and a minimal service worker behind a local HTTPS proxy, then try install and the `/ws` reviewer from an Android and an iOS device.
