"""Server-rendered deck settings and deletion dialogs."""

from collections.abc import Callable
from html import escape
from uuid import uuid4

from datastar_py.fastapi import DatastarResponse
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter

from ankiweb.adapters.inbound.http_app.decks import (
    FormSignals,
    _deck_error,
    _form_string,
    _js_literal,
    _render_decks,
)
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_languages import LANGUAGES, DeckLanguageError, choose
from ankiweb.core.app_client.decks import (
    DeckNameError,
    deck_rows,
    deck_settings,
    delete_deck,
    update_deck_settings,
)
from ankiweb.core.app_client.emoji_picker import EMOJI_GROUPS
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.ports import CollectionPort


def _toast(message: str):
    # A fresh keyed child restarts the toast animation when Datastar morphs.
    html = (
        '<div id="toast" class="toast toast-top toast-center pointer-events-none z-50" '
        'role="status" aria-live="polite">'
        f'<div id="deck-toast-{uuid4().hex}" class="alert deck-toast">'
        f"{escape(message)}</div></div>"
    )
    return SSE.patch_elements(html, selector="#toast")


def _parse_deck_id(value: str) -> int:
    """Reject malformed or out-of-range IDs before passing them to Anki."""
    if not value.isascii() or not value.isdecimal():
        raise DeckNameError("not_found")
    digits = value.lstrip("0") or "0"
    if len(digits) > 19:
        raise DeckNameError("not_found")
    deck_id = int(digits)
    if not 0 < deck_id <= 2**63 - 1:
        raise DeckNameError("not_found")
    return deck_id


def _emoji_group(emoji: str) -> str:
    group = "world" if any(item.flag == emoji for item in LANGUAGES) else "study"
    for item in EMOJI_GROUPS:
        if emoji in item.emojis:
            group = item.key
    return group


def add_deck_settings_routes(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    """Attach dialog and mutation routes to the guarded app router."""
    _add_get_settings_route(router, get_service, lang)
    _add_save_settings_route(router, get_service, lang)
    _add_get_delete_route(router, get_service, lang)
    _add_remove_deck_route(router, get_service, lang)


def _add_get_settings_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.get("/decks/{deck_id}/settings")
    async def get_settings(deck_id: str) -> DatastarResponse:
        try:
            parsed_id = _parse_deck_id(deck_id)
            settings = await get_service().run(
                lambda col: deck_settings(col, parsed_id)
            )
        except DeckNameError as error:
            return DatastarResponse(_toast(_deck_error(error, lang)))

        pair = settings.languages
        mode = "langs" if pair else "none"
        src = pair.src if pair else ""
        dst = pair.dst if pair else ""
        group = _emoji_group(settings.emoji)
        body = render(
            "app/_deck_settings_sheet.html.jinja",
            fragment="body",
            settings=settings,
            app_lang=lang,
            LANGUAGES=LANGUAGES,
            emoji_groups=EMOJI_GROUPS,
            js_literal=_js_literal,
        )
        return DatastarResponse(
            [
                SSE.patch_elements(body, selector="#deck-settings-body"),
                SSE.patch_signals(
                    {
                        "setId": settings.deck_id,
                        "setName": settings.name,
                        "setEmoji": settings.emoji,
                        "setMode": mode,
                        "setSrc": src,
                        "setDst": dst,
                        "baseName": settings.name,
                        "baseEmoji": settings.emoji,
                        "baseMode": mode,
                        "baseSrc": src,
                        "baseDst": dst,
                        "setEmojiGroup": group,
                        "saving": False,
                        "setError": "",
                        "setOpen": True,
                    }
                ),
            ]
        )


def _add_save_settings_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.post("/decks/{deck_id}/settings")
    async def save_settings(
        deck_id: str, payload: FormSignals = None
    ) -> DatastarResponse:
        name = payload.get("setName") if isinstance(payload, dict) else None
        emoji = payload.get("setEmoji") if isinstance(payload, dict) else None
        mode = payload.get("setMode") if isinstance(payload, dict) else None
        src = payload.get("setSrc") if isinstance(payload, dict) else None
        dst = payload.get("setDst") if isinstance(payload, dict) else None
        try:
            parsed_id = _parse_deck_id(deck_id)
            valid_name = _form_string(name)
            valid_emoji = _form_string(emoji)
            languages = choose(_form_string(mode), _form_string(src), _form_string(dst))
            service = get_service()
            await service.run_op(
                lambda col: update_deck_settings(
                    col, parsed_id, valid_name, valid_emoji, languages
                ),
                initiator="app",
            )
        except (DeckNameError, DeckLanguageError) as error:
            return DatastarResponse(
                SSE.patch_signals({"setError": _deck_error(error, lang, src=src)})
            )

        rows = await service.run(deck_rows)
        return DatastarResponse(
            [
                SSE.patch_elements(
                    _render_decks(rows, lang, fragment="content"),
                    selector="#decks-content",
                ),
                _toast(s("app_decks_saved", lang=lang.catalog_lang)),
                SSE.patch_signals({"setError": "", "setOpen": False}),
            ]
        )


def _add_get_delete_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.get("/decks/{deck_id}/delete")
    async def get_delete(deck_id: str) -> DatastarResponse:
        try:
            parsed_id = _parse_deck_id(deck_id)
            settings = await get_service().run(
                lambda col: deck_settings(col, parsed_id)
            )
            if settings.deck_id == 1:
                raise DeckNameError("protected")
        except DeckNameError as error:
            return DatastarResponse(_toast(_deck_error(error, lang)))
        body = render(
            "app/_deck_delete_sheet.html.jinja",
            fragment="body",
            settings=settings,
            app_lang=lang,
        )
        return DatastarResponse(
            [
                SSE.patch_elements(body, selector="#deck-delete-body"),
                SSE.patch_signals({"delOpen": True}),
            ]
        )


def _add_remove_deck_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.post("/decks/{deck_id}/delete")
    async def remove_deck(deck_id: str) -> DatastarResponse:
        try:
            parsed_id = _parse_deck_id(deck_id)
            if parsed_id == 1:
                raise DeckNameError("protected")
            service = get_service()
            await service.run_op(
                lambda col: delete_deck(col, parsed_id), initiator="app"
            )
        except DeckNameError as error:
            return DatastarResponse(_toast(_deck_error(error, lang)))
        rows = await service.run(deck_rows)
        return DatastarResponse(
            [
                SSE.patch_elements(
                    _render_decks(rows, lang, fragment="content"),
                    selector="#decks-content",
                ),
                _toast(s("app_decks_deleted", lang=lang.catalog_lang)),
                SSE.patch_signals({"delOpen": False}),
            ]
        )
