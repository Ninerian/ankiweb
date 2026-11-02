# Deploy the mobile PWA

The mobile client at `/app/` is a separate install from the existing client at `/`.
Both use the same collection and optional password. The new client needs the web UI
port, not the AnkiConnect port or the legacy reviewer's `/ws` bridge. It requires a
network connection for study and editing; offline navigation shows a fallback page,
not cached cards or an offline reviewer.

## HTTPS with Caddy

Installation on a phone requires HTTPS; a LAN IP over plain HTTP is not enough.
Browsers treat localhost as a secure-context exception on the machine running the
browser, not on a separate phone. Use a hostname the phone can resolve and a
certificate the phone trusts. For example, with DNS pointing `anki.example.com` at
the Caddy host and Caddy able to obtain a certificate:

```caddyfile
anki.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Start ankiweb on the same host, leaving the UI bound to loopback:

```sh
ANKIWEB_ALLOWED_HOSTS=anki.example.com \
ANKIWEB_PASSWORD='choose-a-password' \
  uv run python -m ankiweb
```

Replace the hostname and password. Caddy must be reachable over HTTPS by the phone;
public certificate issuance also needs its own DNS and network prerequisites. For a
private-only hostname, use a certificate trusted by every device, including the phone.
The host allowlist accepts comma-separated names, optionally with a port; prefer
specific names rather than `*`. Do not expose the separate AnkiConnect port merely
to install the PWA. The password is a lightweight single-user gate, not hardened
internet-facing authentication; limit network access appropriately.

Caddy forwards the original host and scheme. The login cookie sets `Secure` only
when the request scheme seen by the application is `https`. The normal Uvicorn
startup accepts proxy headers by default from `127.0.0.1`; in the example, Caddy
connects from that trusted address. If the proxy connects from another address,
configure Uvicorn's `FORWARDED_ALLOW_IPS` with the actual trusted proxy address(es)
and restrict direct access to the backend. Do not trust forwarded headers from
arbitrary clients: forged scheme headers can make the cookie decision incorrect.
Ensure the proxy overwrites or sanitizes forwarded headers. A proxy not trusted by
Uvicorn leaves the backend request as HTTP, so the login cookie will not be Secure
even though the browser uses HTTPS. Check the cookie and request scheme in the
deployed setup. The separate `app_sid` session cookie currently does **not** set
`Secure`; HTTPS alone does not add that attribute.

## Install

1. Open `https://anki.example.com/app/` in the phone's browser and log in if needed.
2. On Android Chromium, use **Install app** if it appears, or the browser's install /
   add-to-home-screen menu. The in-app button appears only when the browser supplies
   an install prompt.
3. On iOS Safari, use **Share → Add to Home Screen**. An in-page hint may appear
   outside standalone mode and can be dismissed.

Open the home-screen icon to start the `/app/` install. The old `/` client retains
its own manifest and installation identity. Android and iOS device installation,
HTTPS deployment in practice, and launcher maskable-icon cropping have **not** been
verified; the shared icons are placeholders.

## Cache and updates

App pages and the offline page use `/shell/static/app-client.css?v=<build_hash>`.
Top-level app scripts under `/shell/static/app/*.js` use the same version; other
scripts, including `datastar.js`, do not. The 12-character build hash reflects
the deployed app CSS and JavaScript and also versions the worker cache. After
changing `shell_src/app-client.css` or app JavaScript sources, run `npm run build`
before deployment to rebuild the served assets.

The `/app/` worker precaches the public offline page and the same versioned CSS.
App CSS and JavaScript are served cache-first; precaching and cache misses use
`cache: 'reload'` to bypass the browser HTTP cache. App navigations are network-only,
with the offline page as a fallback; authenticated HTML is not deliberately cached.

The app checks for worker updates at load and when it returns to the foreground.
It does not forcibly reload the current screen, protecting unsaved inputs. Save
your work and navigate or reload online to see updates; a new versioned CSS URL
can be fetched on the next navigation even if the old worker still controls it.

iOS device storage and workers are local to each device: updating a simulator or
another device does not update a physical iPhone. Verify the installed app on the
target iPhone over trusted HTTPS; physical-iPhone update behavior is not verified.

On activation, the legacy root worker removes old `ankiweb-shell-` caches only;
the app worker removes old `ankiweb-app-` caches only. Each preserves the other's
caches and unrelated caches. Restricting legacy cleanup is a targeted change from
the original unchanged-worker plan; its other behavior remains unchanged.
