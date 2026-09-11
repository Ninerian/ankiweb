from __future__ import annotations
import copy
from ankiweb.i18n import tr
from ankiweb.screens import templating


def _heading() -> str:
    """Prefer the desktop "Manage Note Types" string; fall back to a keyless heading.
    (qt_misc_manage_note_types exists; notetypes_notetypes does not.)"""
    try:
        return tr.qt_misc_manage_note_types()
    except Exception:
        return "Note Types"


def render_notetypes_html(col) -> str:
    rows = []
    for nt in col.models.all_names_and_ids():
        ntid = int(nt.id)
        count = len(col.models.nids(ntid))
        rows.append({"id": ntid, "name": nt.name, "count": count})

    return templating.render(
        "notetypes.html.jinja",
        heading=_heading(),
        rows=rows,
        L_rename=tr.actions_rename(),
        L_delete=tr.actions_delete(),
        L_add=tr.actions_add(),
        L_name=tr.actions_name(),
        L_fields=tr.notetypes_fields(),
        L_cards=tr.notetypes_cards(),
    )

def make_notetypes_handler(service, hub):
    async def handler(arg: str):
        cmd, _, rest = arg.partition(":")

        if cmd == "rename":
            sid, _, newname = rest.partition(":")
            if not newname:
                await hub.push_call("notetypes", "ankiwebNotetypesError",
                                    ["A name is required."])
                return None

            def do_rename(col):
                m = col.models.get(int(sid))
                m["name"] = newname
                return col.models.update_dict(m)

            try:
                await service.run_op(do_rename, initiator="notetypes")
            except Exception as exc:
                await hub.push_call("notetypes", "ankiwebNotetypesError", [str(exc)])
                return None
            await hub.push_call("notetypes", "ankiwebReload", [])
            return None

        if cmd == "delete":
            try:
                ntid = int(rest)
            except ValueError:
                return None

            # Guard: never delete the only note type.
            if await service.run(lambda col: len(col.models.all_names_and_ids())) <= 1:
                await hub.push_call("notetypes", "ankiwebNotetypesError",
                                    ["Cannot delete the only note type"])
                return None

            def do_delete(col):
                return col.models.remove(ntid)

            try:
                await service.run_op(do_delete, initiator="notetypes")
            except Exception as exc:
                await hub.push_call("notetypes", "ankiwebNotetypesError", [str(exc)])
                return None
            await hub.push_call("notetypes", "ankiwebReload", [])
            return None

        if cmd == "add":
            sbase, _, newname = rest.partition(":")
            if not newname:
                await hub.push_call("notetypes", "ankiwebNotetypesError",
                                    ["A name is required."])
                return None

            def do_add(col):
                # Deep-clone the base notetype into a fresh, usable one (id=0 lets the
                # backend assign a new id while keeping flds/tmpls/css so cards generate).
                base = col.models.get(int(sbase))
                nt = copy.deepcopy(base)
                nt["name"] = newname
                nt["id"] = 0
                return col.models.add_dict(nt)

            try:
                await service.run_op(do_add, initiator="notetypes")
            except Exception as exc:
                await hub.push_call("notetypes", "ankiwebNotetypesError", [str(exc)])
                return None
            await hub.push_call("notetypes", "ankiwebReload", [])
            return None

        return None

    return handler
