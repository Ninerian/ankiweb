"""Server-rendered deck settings and deletion dialogs."""

from collections.abc import Callable

from datastar_py.fastapi import DatastarResponse
from fastapi import APIRouter, Request

from ankiweb.adapters.inbound.http_app import deck_dialog
from ankiweb.adapters.inbound.http_app.decks import _deck_error, toast_patch
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_languages import (
    LANGUAGES,
    DeckLanguageError,
    LanguageMode,
    choose,
)
from ankiweb.core.app_client.decks import (
    DeckNameError,
    deck_settings,
    delete_deck,
    update_deck_settings,
)
from ankiweb.core.app_client.emoji_picker import EMOJI_GROUPS
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.ports import CollectionPort


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
    from ankiweb.adapters.inbound.http_app.deck_form import FormDraft, project_form

    @router.get("/decks/{deck_id}/settings")
    async def get_settings(deck_id: str) -> DatastarResponse:
        try:
            parsed_id = _parse_deck_id(deck_id)
            settings = await get_service().run(
                lambda col: deck_settings(col, parsed_id)
            )
        except DeckNameError as error:
            return DatastarResponse(toast_patch(_deck_error(error, lang)))

        pair = settings.languages
        draft = FormDraft(
            settings.name,
            settings.emoji,
            LanguageMode.PAIR if pair else LanguageMode.NONE,
            pair.src if pair else "",
            pair.dst if pair else "",
        )
        body = render(
            "app/_deck_settings_dialog.html.jinja",
            settings=settings,
            projection=project_form(draft, draft),
            token=deck_dialog.new_token(),
            app_lang=lang,
            LANGUAGES=LANGUAGES,
            emoji_groups=EMOJI_GROUPS,
        )
        return DatastarResponse(deck_dialog.show_dialog(body))


def _add_save_settings_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    from ankiweb.adapters.inbound.http_app.deck_form import (
        FormDraft,
        project_form,
        render_fragment,
    )

    @router.post("/decks/{deck_id}/settings")
    async def save_settings(deck_id: str, request: Request) -> DatastarResponse:
        fields = await deck_dialog.form_fields(request)
        if fields is None:
            return deck_dialog.no_patch()
        token = deck_dialog.valid_token(fields.get("token"))
        if (
            token is None
            or not {"name", "emoji", "mode", "src", "dst"} <= fields.keys()
        ):
            return deck_dialog.no_patch()
        draft = FormDraft(
            *(fields[key] for key in ("name", "emoji", "mode", "src", "dst"))
        )
        try:
            parsed_id = _parse_deck_id(deck_id)
            languages = choose(draft.mode, draft.src, draft.dst)
            service = get_service()
            await service.run_op(
                lambda col: update_deck_settings(
                    col, parsed_id, draft.name, draft.emoji, languages
                ),
                initiator="app",
            )
        except (DeckNameError, DeckLanguageError) as error:
            target, html = render_fragment(
                "error",
                "set",
                project_form(draft),
                lang,
                error=_deck_error(error, lang, src=draft.src),
            )
            return DatastarResponse(deck_dialog.patch_in_dialog(token, target, html))

        return DatastarResponse(
            [
                toast_patch(s("app_decks_saved", lang=lang.catalog_lang)),
                deck_dialog.close_dialog(token),
                deck_dialog.refresh_decks(),
            ]
        )


def _add_get_delete_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.get("/decks/{deck_id}/delete")
    async def get_delete(deck_id: str) -> DatastarResponse:
        try:
            parsed_id = _parse_deck_id(deck_id)
            if parsed_id == 1:
                raise DeckNameError("protected")
            settings = await get_service().run(
                lambda col: deck_settings(col, parsed_id)
            )
        except DeckNameError as error:
            return DatastarResponse(toast_patch(_deck_error(error, lang)))
        body = render(
            "app/_deck_delete_dialog.html.jinja",
            settings=settings,
            token=deck_dialog.new_token(),
            app_lang=lang,
        )
        return DatastarResponse(deck_dialog.show_dialog(body))


def _add_remove_deck_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.post("/decks/{deck_id}/delete")
    async def remove_deck(deck_id: str, request: Request) -> DatastarResponse:
        fields = await deck_dialog.form_fields(request)
        if fields is None:
            return deck_dialog.no_patch()
        token = deck_dialog.valid_token(fields.get("token"))
        if token is None:
            return deck_dialog.no_patch()
        try:
            parsed_id = _parse_deck_id(deck_id)
            if parsed_id == 1:
                raise DeckNameError("protected")
            service = get_service()
            await service.run_op(
                lambda col: delete_deck(col, parsed_id), initiator="app"
            )
        except DeckNameError as error:
            return DatastarResponse(toast_patch(_deck_error(error, lang)))
        return DatastarResponse(
            [
                toast_patch(s("app_decks_deleted", lang=lang.catalog_lang)),
                deck_dialog.close_dialog(token),
                deck_dialog.refresh_decks(),
            ]
        )
