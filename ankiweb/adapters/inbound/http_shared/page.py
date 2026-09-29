from __future__ import annotations
from typing import Sequence

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr


def _page_title(context: str) -> str:
    """Human title for the browser tab/history; unknown contexts fall back to the app name."""
    titles = {
        "deckbrowser": tr.actions_decks(),
        "overview": tr.actions_decks(),
        "customstudy": tr.actions_custom_study(),
        "filtereddeck": tr.qt_misc_create_filtered_deck(),
        "reviewer": tr.studying_study_now(),
        "browser": tr.qt_misc_browse(),
        "add": tr.actions_add(),
        "preferences": tr.preferences_preferences(),
        "notetypes": tr.notetypes_note_types(),
        "tools": tr.qt_accel_tools().replace("&", ""),
        "notify": "Push notifications",
        "about": "Source",
        "export": tr.actions_export(),
    }
    title = titles.get(context)
    return f"{title} \u2013 AnkiWeb" if title else "AnkiWeb"


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
        title=_page_title(context),
        css_files=css_files,
        js_files=js_files,
        toolbar=toolbar,
    )
