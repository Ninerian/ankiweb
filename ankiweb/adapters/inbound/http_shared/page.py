from __future__ import annotations

from collections.abc import Sequence

from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr

# Store translation method names so `_page_title` resolves them after the active
# collection language is selected, rather than capturing translations at import.
_TITLE_TRANSLATIONS = {
    "deckbrowser": "actions_decks",
    "overview": "actions_decks",
    "customstudy": "actions_custom_study",
    "filtereddeck": "qt_misc_create_filtered_deck",
    "reviewer": "studying_study_now",
    "browser": "qt_misc_browse",
    "add": "actions_add",
    "preferences": "preferences_preferences",
    "notetypes": "notetypes_note_types",
    "tools": "qt_accel_tools",
    "export": "actions_export",
    "graphs": "qt_misc_stats",
    "deckoptions": "deck_config_title",
    "card-info": "actions_card_info",
    "changenotetype": "browsing_change_notetype",
    "image-occlusion": "editing_image_occlusion_mode",
    "importcsv": "actions_import",
    "import_package": "actions_import",
    "import_page": "actions_import",
    "editor": "editing_edit_current",
}

_STATIC_TITLES = {
    "notify": "Push notifications",
    "about": "Source",
}


def _page_title(context: str) -> str:
    """Human title for the browser tab/history; unknown contexts fall back to the app name."""
    translation = _TITLE_TRANSLATIONS.get(context)
    if translation is not None:
        raw_title = getattr(tr, translation)()
    else:
        raw_title = _STATIC_TITLES.get(context)
        if raw_title is None:
            return "AnkiWeb"
    clean_title = templating.tr_clean(raw_title)
    return f"{clean_title} \u2013 AnkiWeb" if clean_title else "AnkiWeb"


def render_page(
    context: str,
    body: str,
    css_files: Sequence[str] | None = None,
    js_files: Sequence[str] | None = None,
    toolbar: bool | None = None,
    *,
    bridge: bool = False,
) -> str:
    """Wrap a server-rendered fragment in a full shell HTML document.

    Publishes ``window.__ankiwebContext`` and the bridge opt-in before scripts. Browser
    WebSocket transport (``/ws?context=...``) is disabled by default; only the native
    reviewer passes ``bridge=True``; all other pages retain their existing HTTP/
    Datastar behavior.

    Vendored ``js_files`` (served from ``/_anki/``) load before the shell bootstrap, so
    globals they define (e.g. reviewer.js's ``window._showQuestion``) exist when the page
    body's inline script runs.

    ``toolbar`` adds the always-present top toolbar (Decks/Add/Browse/Stats); pass ``False``
    for embedded fragments like the editor iframe inside the Browser.
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
        bridge=bridge,
    )
