"""Server-side deck form projections, previews, and creation."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from datastar_py.fastapi import DatastarResponse
from fastapi import APIRouter, Request

from ankiweb.adapters.inbound.http_app import deck_dialog
from ankiweb.adapters.inbound.http_app.decks import (
    _JS_TRIM,
    _deck_error,
    search_form_patch,
    toast_patch,
)
from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.deck_languages import (
    LANGUAGES,
    DeckLanguageError,
    LanguageMode,
    choose,
)
from ankiweb.core.app_client.decks import (
    DeckNameError,
    DeckSettings,
    create_deck,
    deck_settings,
)
from ankiweb.core.app_client.emoji_picker import EMOJI_GROUPS
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.ports import CollectionPort

_FLAGS = {language.code: language.flag for language in LANGUAGES}


class _LanguageChip(StrEnum):
    """Language summary displayed in the deck preview."""

    PAIR = "pair"
    NONE = "none"
    UNSET = "unset"


class _LanguageMessage(StrEnum):
    """Language guidance displayed alongside the form."""

    NONE = ""
    SAME = "same"
    MISSING_DST = "missing_dst"
    MISSING_SRC = "missing_src"
    NONE_REMOVES = "none_removes"


@dataclass(frozen=True)
class FormDraft:
    name: str
    emoji: str
    mode: str
    src: str
    dst: str


@dataclass(frozen=True)
class FormProjection:
    name: str
    name_count: int
    emoji: str
    mode: str
    chip: _LanguageChip
    message: _LanguageMessage
    suggestion: str
    dirty: int
    changed_name: bool
    changed_emoji: bool
    changed_languages: bool
    can_submit_content: bool
    can_swap: bool
    src_flag: str
    dst_flag: str
    src: str
    dst: str


def _language_message(draft: FormDraft, baseline: FormDraft | None) -> _LanguageMessage:
    if draft.mode == LanguageMode.PAIR:
        if draft.src and draft.src == draft.dst:
            return _LanguageMessage.SAME
        if draft.src and not draft.dst:
            return _LanguageMessage.MISSING_DST
        if draft.dst and not draft.src:
            return _LanguageMessage.MISSING_SRC
    elif (
        draft.mode == LanguageMode.NONE
        and baseline
        and baseline.mode == LanguageMode.PAIR
        and baseline.src
        and baseline.dst
    ):
        return _LanguageMessage.NONE_REMOVES
    return _LanguageMessage.NONE


def _flag_suggestion(draft: FormDraft, baseline: FormDraft | None) -> str:
    if (
        baseline is None
        and draft.mode == LanguageMode.PAIR
        and draft.dst
        and draft.src != draft.dst
    ):
        flag = _FLAGS.get(draft.dst, "")
        if draft.emoji != flag:
            return flag
    return ""


def _language_changed(draft: FormDraft, baseline: FormDraft | None) -> bool:
    return baseline is not None and (
        draft.mode != baseline.mode
        or (
            draft.mode == LanguageMode.PAIR
            and (draft.src != baseline.src or draft.dst != baseline.dst)
        )
    )


def project_form(draft: FormDraft, baseline: FormDraft | None = None) -> FormProjection:
    """Project a draft; a baseline marks a settings form, not authorization."""
    pair = (
        draft.mode == LanguageMode.PAIR
        and bool(draft.src and draft.dst)
        and draft.src != draft.dst
    )
    chip = (
        _LanguageChip.NONE
        if draft.mode == LanguageMode.NONE
        else _LanguageChip.PAIR
        if pair
        else _LanguageChip.UNSET
    )
    message = _language_message(draft, baseline)
    changed_name = baseline is not None and draft.name != baseline.name
    changed_emoji = baseline is not None and draft.emoji != baseline.emoji
    changed_languages = _language_changed(draft, baseline)
    dirty = sum((changed_name, changed_emoji, changed_languages))
    suggestion = _flag_suggestion(draft, baseline)
    name = draft.name.strip(_JS_TRIM)
    return FormProjection(
        name=name,
        name_count=len(draft.name.encode("utf-16-le", errors="surrogatepass")) // 2,
        emoji=draft.emoji,
        mode=draft.mode,
        chip=chip,
        message=message,
        suggestion=suggestion,
        dirty=dirty,
        changed_name=changed_name,
        changed_emoji=changed_emoji,
        changed_languages=changed_languages,
        can_submit_content=bool(name)
        and (draft.mode == LanguageMode.NONE or pair)
        and (baseline is None or dirty > 0),
        can_swap=draft.mode == LanguageMode.PAIR and bool(draft.src or draft.dst),
        src_flag=_FLAGS.get(draft.src, "?"),
        dst_flag=_FLAGS.get(draft.dst, "?"),
        src=draft.src,
        dst=draft.dst,
    )


def render_fragment(
    fragment: str,
    prefix: str,
    projection: FormProjection,
    lang: ResolvedLang,
    *,
    error: str = "",
) -> tuple[str, str]:
    """Render one independently patchable, server-computed form fragment."""
    target = (
        f"flag-{fragment[:3]}" if fragment in ("src-flag", "dst-flag") else fragment
    )
    return f"{prefix}-{target}", render(
        "app/_deck_projection.html.jinja",
        fragment=fragment,
        prefix=prefix,
        projection=projection,
        error=error,
        app_lang=lang,
        LANGUAGES=LANGUAGES,
    )


def _draft(fields: dict[str, str]) -> FormDraft | None:
    try:
        return FormDraft(
            *(fields[key] for key in ("name", "emoji", "mode", "src", "dst"))
        )
    except KeyError:
        return None


def _valid_projection_draft(draft: FormDraft) -> bool:
    return (
        draft.mode in {LanguageMode.PAIR, LanguageMode.NONE}
        and (not draft.src or draft.src in _FLAGS)
        and (not draft.dst or draft.dst in _FLAGS)
    )


def _projection_events(
    token: str, prefix: str, projection: FormProjection, lang: ResolvedLang
) -> list:
    fragments = ["preview", "messages", "src-flag", "dst-flag", "swap"]
    if prefix == "new":
        fragments.append("suggest")
    else:
        fragments.extend(["dirty", "name-changed", "emoji-changed", "lang-changed"])
    fragments.extend(["name-count", "error", "submit"])
    events = []
    for fragment in fragments:
        target, html = render_fragment(fragment, prefix, projection, lang)
        if fragment == "error":
            form_id = "deck-create-form" if prefix == "new" else "deck-settings-form"
            target = f"{form_id}:not([data-submitted]) #{target}"
        event = deck_dialog.patch_in_dialog(token, target, html)
        if event is not None:
            events.append(event)
    return events


def _baseline(settings: DeckSettings) -> FormDraft:
    pair = settings.languages
    return FormDraft(
        settings.name,
        settings.emoji,
        LanguageMode.PAIR if pair else LanguageMode.NONE,
        pair.src if pair else "",
        pair.dst if pair else "",
    )


def _add_new_dialog_route(router: APIRouter, lang: ResolvedLang) -> None:
    @router.get("/decks/new")
    async def new_dialog(request: Request) -> DatastarResponse:
        fields = await deck_dialog.read_fields(request)
        query = fields.get("q", "")
        name = query[:40] if fields.get("prefill") == "1" else ""
        draft = FormDraft(name, "📚", LanguageMode.PAIR, "", "")
        body = render(
            "app/_deck_create_dialog.html.jinja",
            token=deck_dialog.new_token(),
            q=query,
            draft=draft,
            projection=project_form(draft),
            app_lang=lang,
            LANGUAGES=LANGUAGES,
            emoji_groups=EMOJI_GROUPS,
        )
        return DatastarResponse(deck_dialog.show_dialog(body))


def _add_preview_routes(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.post("/decks/new/preview")
    async def preview_new(request: Request) -> DatastarResponse:
        fields = await deck_dialog.form_fields(request)
        if fields is None:
            return deck_dialog.no_patch()
        token = deck_dialog.valid_token(fields.get("token"))
        draft = _draft(fields)
        if token is None or draft is None or not _valid_projection_draft(draft):
            return deck_dialog.no_patch()
        return DatastarResponse(
            _projection_events(token, "new", project_form(draft), lang)
        )

    @router.post("/decks/{deck_id}/settings/preview")
    async def preview_settings(deck_id: str, request: Request) -> DatastarResponse:
        from ankiweb.adapters.inbound.http_app.deck_settings import _parse_deck_id

        fields = await deck_dialog.form_fields(request)
        if fields is None:
            return deck_dialog.no_patch()
        token = deck_dialog.valid_token(fields.get("token"))
        draft = _draft(fields)
        if token is None or draft is None or not _valid_projection_draft(draft):
            return deck_dialog.no_patch()
        try:
            parsed_id = _parse_deck_id(deck_id)
            settings = await get_service().run(
                lambda col: deck_settings(col, parsed_id)
            )
        except DeckNameError:
            return deck_dialog.no_patch()
        projection = project_form(draft, _baseline(settings))
        return DatastarResponse(_projection_events(token, "set", projection, lang))


def _add_create_route(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    @router.post("/decks")
    async def create(request: Request) -> DatastarResponse:
        fields = await deck_dialog.form_fields(request)
        if fields is None:
            return deck_dialog.no_patch()
        token = deck_dialog.valid_token(fields.get("token"))
        draft = _draft(fields)
        if token is None or draft is None:
            return deck_dialog.no_patch()
        try:
            languages = choose(draft.mode, draft.src, draft.dst)
            row = await get_service().run_op(
                lambda col: create_deck(col, draft.name, draft.emoji, languages),
                initiator="app",
            )
        except (DeckNameError, DeckLanguageError) as error:
            target, html = render_fragment(
                "error",
                "new",
                project_form(draft),
                lang,
                error=_deck_error(error, lang, src=draft.src),
            )
            return DatastarResponse(deck_dialog.patch_in_dialog(token, target, html))
        return DatastarResponse(
            [
                search_form_patch(lang, ""),
                toast_patch(s("app_decks_created", lang=lang.catalog_lang)),
                deck_dialog.close_dialog(token),
                deck_dialog.refresh_decks(row.deck_id),
            ]
        )


def add_deck_form_routes(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    """Attach create and read-only form projection routes."""
    _add_new_dialog_route(router, lang)
    _add_preview_routes(router, get_service, lang)
    _add_create_route(router, get_service, lang)
