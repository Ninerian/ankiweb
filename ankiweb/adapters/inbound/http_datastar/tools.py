from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter

from ankiweb.adapters.inbound.http_datastar.common import elements_response
from ankiweb.adapters.inbound.http_shared import templating
from ankiweb.core.i18n import tr


def render_tools_html(col) -> str:
    """Server-rendered Tools page: Check Database, Check Media, Empty Cards (each a
    button + an empty result <div> patched in place by the corresponding /tools/*
    Datastar route), plus a link to Manage Note Types. Mirrors the E4/E5
    server-rendered screens."""
    return templating.render(
        "tools.html.jinja",
        checkdb_label=tr.database_check_title(),
        checkmedia_label=tr.media_check_check_media_action(),
        emptycards_label=tr.qt_misc_empty_cards(),
        notetypes_label=tr.qt_misc_manage_note_types(),
    )


def _media_result_html(mc) -> str:
    """Build the Check Media result fragment: the report, a Delete-unused button when
    there are unused files, and short previews of the unused/missing names."""
    unused = list(mc.unused)
    missing = list(mc.missing)
    return templating.render(
        "tools_media_result.html.jinja",
        report=mc.report,
        unused=unused,
        missing=missing,
        delete_label=tr.media_check_delete_unused(),
    )


def _db_result_html(report: str) -> str:
    return templating.render("tools_db_result.html.jinja", report=report)


def _emptycards_result_html(report: str, cids: list) -> str:
    return templating.render(
        "tools_emptycards_result.html.jinja",
        report=report,
        cids=cids,
        delete_label=tr.empty_cards_delete_button(),
    )


def _emptycards_deleted_html(n: int) -> str:
    return templating.render("tools_emptycards_deleted.html.jinja", n=n)


def make_tools_routes(get_service: Callable) -> APIRouter:
    router = APIRouter(prefix="/tools")
    state: dict = {}

    def _push_media(mc):
        state["unused"] = list(mc.unused)
        res_html = f'<div id="res-media">{_media_result_html(mc)}</div>'
        return elements_response(res_html, selector="#res-media")

    @router.post("/checkdb")
    async def check_db():
        service = get_service()
        report, _ = await service.run(lambda col: col.fix_integrity())
        res_html = f'<div id="res-db">{_db_result_html(report)}</div>'
        return elements_response(res_html, selector="#res-db")

    @router.post("/checkmedia")
    async def check_media():
        service = get_service()
        mc = await service.run(lambda col: col.media.check())
        return _push_media(mc)

    @router.post("/deleteunused")
    async def delete_unused():
        service = get_service()
        un = state.get("unused") or []
        if un:
            await service.run(
                lambda col: (col.media.trash_files(un), col.media.empty_trash())
            )
        state["unused"] = []
        mc = await service.run(lambda col: col.media.check())
        return _push_media(mc)

    @router.post("/emptycards")
    async def empty_cards():
        service = get_service()
        rep = await service.run(lambda col: col.get_empty_cards())
        cids = [cid for n in rep.notes for cid in n.card_ids]
        state["empty"] = cids
        res_html = (
            f'<div id="res-empty">{_emptycards_result_html(rep.report, cids)}</div>'
        )
        return elements_response(res_html, selector="#res-empty")

    @router.post("/emptycards_delete")
    async def emptycards_delete():
        service = get_service()
        cids = state.get("empty") or []
        if cids:
            await service.run_op(
                lambda col: col.remove_cards_and_orphaned_notes(cids), initiator="tools"
            )
        n = len(cids)
        state["empty"] = []
        res_html = f'<div id="res-empty">{_emptycards_deleted_html(n)}</div>'
        return elements_response(res_html, selector="#res-empty")

    return router
