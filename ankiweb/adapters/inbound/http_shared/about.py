from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ankiweb.adapters.inbound.http_shared import templating

_ANKI_SRC = "https://github.com/ankitects/anki"
_AC_SRC = "https://github.com/FooSoft/anki-connect"


def render_about_html(settings) -> str:
    """The AGPL §13 Corresponding-Source offer, shown to every user of the running app."""
    try:
        ver = version("ankiweb")
    except PackageNotFoundError:
        ver = "0.1.0"
    src = (getattr(settings, "source_url", "") or "").strip()
    return templating.render(
        "about.html.jinja",
        version=ver,
        source_url=src,
        anki_src=_ANKI_SRC,
        ac_src=_AC_SRC,
    )
