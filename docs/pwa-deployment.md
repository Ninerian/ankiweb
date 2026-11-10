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

When a password is configured, unauthenticated visits to `/app` or `/app/...`
redirect to the same-origin `/app/login`. Both the standard form and Datastar login
return to `/app/` after successful authentication; failed attempts stay on the
app login page. The legacy client continues to use `/login` and returns to `/`
after a successful login.

1. Open `https://anki.example.com/app/` in the phone's browser and log in if needed.
2. On Android Chromium, use **Install app** if it appears, or the browser's install /
   add-to-home-screen menu. The in-app button appears only when the browser supplies
   an install prompt.
3. On iOS Safari, use **Share → Add to Home Screen**. An in-page hint may appear
   outside standalone mode and can be dismissed.

Open the home-screen icon to start the `/app/` install. The old `/` client retains
its own manifest and installation identity. Android and iOS device installation,
HTTPS deployment in practice, and launcher maskable-icon cropping have **not** been
verified.

The app stylesheet disables vertical viewport overscroll without locking document
or inner scrolling; horizontal navigation gestures are unchanged. This also applies
when `/app/` is opened in a browser tab. Safari supports `overscroll-behavior`
from iOS 16; older versions may still bounce. Check on a physical iPhone in Safari
and from the home screen: overscroll at both ends of short and long deck pages,
scroll long review cards and editor card lists, open scrollable dialogs, and check
login and editor fields with the keyboard open and dismissed. Actual device
behavior, including keyboard viewport movement, has not been verified.

The app uses the Kartenblitz icon: yellow flashcards with a lightning bolt. The
192- and 512-pixel PNGs are opaque, full-bleed squares, with the artwork inside
the maskable safe zone (a radius of at most 102.4 in a 256-by-256 coordinate
space). The 180-pixel apple-touch icon and simplified favicon (`favicon.svg`
and `favicon.ico` with 16- and 32-pixel images) live alongside them in
`ankiweb/shell/static/icons/`. These are committed assets, not build output.

### Regenerating icons

From the repository root, render the master SVG with `rsvg-convert` and
ImageMagick. The PNGs must have no alpha channel:

```sh
rsvg-convert -w 512 -h 512 ankiweb/shell/static/icons/icon.svg | magick png:- -alpha off -colorspace sRGB PNG24:ankiweb/shell/static/icons/icon-512.png
rsvg-convert -w 192 -h 192 ankiweb/shell/static/icons/icon.svg | magick png:- -alpha off -colorspace sRGB PNG24:ankiweb/shell/static/icons/icon-192.png
rsvg-convert -w 180 -h 180 ankiweb/shell/static/icons/icon.svg | magick png:- -alpha off -colorspace sRGB PNG24:ankiweb/shell/static/icons/apple-touch-icon.png
```

`favicon.svg` is hand-simplified and must not be derived from `icon.svg`. Render
it separately and use temporary PNGs to create the ICO:

```sh
tmpdir=$(mktemp -d)
rsvg-convert -w 16 -h 16 ankiweb/shell/static/icons/favicon.svg | magick png:- -alpha off -colorspace sRGB PNG24:"$tmpdir/favicon-16.png"
rsvg-convert -w 32 -h 32 ankiweb/shell/static/icons/favicon.svg | magick png:- -alpha off -colorspace sRGB PNG24:"$tmpdir/favicon-32.png"
(cd "$tmpdir" && magick favicon-16.png favicon-32.png favicon.ico)
cp "$tmpdir/favicon.ico" ankiweb/shell/static/icons/favicon.ico
rm -r "$tmpdir"
```

Existing home-screen icons update only when the browser re-reads the manifest or
the user re-adds the app. The legacy root worker caches `/shell/static/` assets
cache-first, so already-installed clients may keep old PNGs until its cache
version changes.

## Cache and updates

App pages and the offline page use `/shell/static/app-client.css?v=<build_hash>`.
Top-level app scripts under `/shell/static/app/*.js` use the same version; other
scripts, including `datastar.js`, do not. The 12-character build hash reflects
the deployed app CSS and JavaScript. The worker cache version also includes the
rendered offline page, so changes to its content or language create a new worker
cache without changing asset URL versions. After changing `shell_src/app-client.css`
or app JavaScript sources, run `npm run build` before deployment to rebuild the
served assets.

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
