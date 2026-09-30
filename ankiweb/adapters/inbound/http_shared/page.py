from __future__ import annotations
from typing import Sequence

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr


# Callables, not strings: `tr` is bound to the language set when the collection opens
# (ANKIWEB_LANG), which happens after import, so titles must resolve at request time.
_TITLES = {
    "deckbrowser": lambda: tr.actions_decks(),
    "overview": lambda: tr.actions_decks(),
    "customstudy": lambda: tr.actions_custom_study(),
    "filtereddeck": lambda: tr.qt_misc_create_filtered_deck(),
    "reviewer": lambda: tr.studying_study_now(),
    "browser": lambda: tr.qt_misc_browse(),
    "add": lambda: tr.actions_add(),
    "preferences": lambda: tr.preferences_preferences(),
    "notetypes": lambda: tr.notetypes_note_types(),
    "tools": lambda: tr.qt_accel_tools(),
    "notify": lambda: "Push notifications",
    "about": lambda: "Source",
    "export": lambda: tr.actions_export(),
    "graphs": lambda: tr.qt_misc_stats(),
    "deckoptions": lambda: tr.deck_config_title(),
    "card-info": lambda: tr.actions_card_info(),
    "changenotetype": lambda: tr.browsing_change_notetype(),
    "image-occlusion": lambda: tr.editing_image_occlusion_mode(),
    "importcsv": lambda: tr.actions_import(),
    "import_package": lambda: tr.actions_import(),
    "import_page": lambda: tr.actions_import(),
    "editor": lambda: tr.editing_edit_current(),
}


def _page_title(context: str) -> str:
    """Human title for the browser tab/history; unknown contexts fall back to the app name."""
    make = _TITLES.get(context)
    if not make:
        return "AnkiWeb"
    raw_title = make()
    clean_title = templating.tr_clean(raw_title)
    return f"{clean_title} \u2013 AnkiWeb" if clean_title else "AnkiWeb"

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
