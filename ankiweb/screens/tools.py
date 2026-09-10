from __future__ import annotations

from ankiweb.i18n import tr
from ankiweb.screens import templating


def render_tools_html(col) -> str:
    """Server-rendered Tools page: Check Database, Check Media, Empty Cards (each a
    button + an empty result <div> filled by the WS handler via ankiwebToolsResult),
    plus a link to Manage Note Types. Mirrors the E4/E5 server-rendered screens."""
    return templating.render(
        "tools.html",
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
        "tools_media_result.html",
        report=mc.report,
        unused=unused,
        missing=missing,
        delete_label=tr.media_check_delete_unused(),
    )


def _db_result_html(report: str) -> str:
    return templating.render("tools_db_result.html", report=report)


def _emptycards_result_html(report: str, cids: list) -> str:
    return templating.render(
        "tools_emptycards_result.html",
        report=report,
        cids=cids,
        delete_label=tr.empty_cards_delete_button(),
    )


def _emptycards_deleted_html(n: int) -> str:
    return templating.render("tools_emptycards_deleted.html", n=n)


def make_tools_handler(service, hub):
    """WS handler for the Tools page. A per-handler `state` dict stashes the last
    check's results so the matching delete acts on that report rather than recomputing
    and deleting blindly."""
    state: dict = {}

    async def _push_media(mc):
        state["unused"] = list(mc.unused)
        await hub.push_call("tools", "ankiwebToolsResult", ["media", _media_result_html(mc)])

    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")

        if cmd == "checkdb":
            report, ok = await service.run(lambda col: col.fix_integrity())
            await hub.push_call(
                "tools", "ankiwebToolsResult",
                ["db", _db_result_html(report)])
            return None

        if cmd == "checkmedia":
            mc = await service.run(lambda col: col.media.check())
            await _push_media(mc)
            return None

        if cmd == "deleteunused":
            un = state.get("unused") or []
            if un:
                await service.run(
                    lambda col: (col.media.trash_files(un), col.media.empty_trash()))
            state["unused"] = []
            # Re-run the check so the displayed count reflects the deletion.
            mc = await service.run(lambda col: col.media.check())
            await _push_media(mc)
            return None

        if cmd == "emptycards":
            rep = await service.run(lambda col: col.get_empty_cards())
            cids = [cid for n in rep.notes for cid in n.card_ids]
            state["empty"] = cids
            await hub.push_call("tools", "ankiwebToolsResult", ["empty", _emptycards_result_html(rep.report, cids)])
            return None

        if cmd == "emptycards_delete":
            cids = state.get("empty") or []
            if cids:
                await service.run_op(
                    lambda col: col.remove_cards_and_orphaned_notes(cids),
                    initiator="tools")
            n = len(cids)
            state["empty"] = []
            await hub.push_call(
                "tools", "ankiwebToolsResult",
                ["empty", _emptycards_deleted_html(n)])
            return None

        return None

    return handler
