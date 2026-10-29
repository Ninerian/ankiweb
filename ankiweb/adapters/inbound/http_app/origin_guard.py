"""Reject browser-marked cross-site writes to /app before any route runs.

Browsers label every request: `Sec-Fetch-Site` says where it came from and `Origin` names
the page that sent it. A POST that a browser marks as anything but same-origin is not
something the app's own pages send. Requests without either header (scripts, tests)
carry no browser credentials ambiguity, so they pass.
"""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_ALLOWED_FETCH_SITE = frozenset({"same-origin", "none"})


def _origin_matches_host(origin: str, host: str) -> bool:
    return urlsplit(origin).netloc.lower() == host.lower()


async def reject_cross_site_writes(request: Request) -> None:
    if request.method in _SAFE_METHODS:
        return
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in _ALLOWED_FETCH_SITE:
        raise HTTPException(status_code=403)
    origin = request.headers.get("origin")
    if origin is not None and not _origin_matches_host(
        origin, request.headers.get("host", "")
    ):
        raise HTTPException(status_code=403)
