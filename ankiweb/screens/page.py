from __future__ import annotations
from typing import Sequence

from ankiweb.screens import templating


def render_page(
    context: str,
    body: str,
    css_files: Sequence[str] | None = None,
    js_files: Sequence[str] | None = None,
    toolbar: bool | None = None,
) -> str:
    """Wrap a server-rendered fragment in a full shell HTML document.

    Sets window.__ankiwebContext BEFORE any script so the Bridge connects to
    /ws?context=<context>. Vendored js_files (served from /_anki/) load BEFORE
    the shell bootstrap.js, so globals they define (e.g. reviewer.js's
    window._showQuestion) exist when the page body's inline script runs.

    `toolbar` adds the always-present top toolbar (Decks/Add/Browse/Stats); pass
    False for embedded fragments like the editor iframe inside the Browser.
    """
    if css_files is None:
        css_files = ()
    if js_files is None:
        js_files = ()
    if toolbar is None:
        toolbar = True
    return templating.render(
        "shell.html.jinja",
        context=context,
        body=body,
        css_files=css_files,
        js_files=js_files,
        toolbar=toolbar,
    )
