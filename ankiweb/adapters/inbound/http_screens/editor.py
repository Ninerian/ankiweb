from __future__ import annotations

import json

from ankiweb.adapters.inbound.http_shared import templating


def _munge(col, html: str) -> str:
    """editor_will_munge_html equivalent: null-strip, drop bare <br>, unescape media."""
    html = (html or "").replace("\x00", "")
    if html in ("<br>", "<div><br></div>"):
        html = ""
    return col.media.escape_media_filenames(html, unescape=True)


def _build_load(col, nid: int) -> dict:
    note = col.get_note(nid)
    return {
        "nid": nid,
        "notetypeId": note.note_type()["id"],
        "deckId": None,
        "focusTo": None,
        "originalNoteId": None,
        "reviewerCardId": None,
        "initial": True,
    }


def _save_field(col, nid: int, ord_: int, html: str):
    note = col.get_note(nid)
    if 0 <= ord_ < len(note.fields):
        note.fields[ord_] = _munge(col, html)
        return col.update_note(note, skip_undo_entry=True)
    return None


def paste_handler_js() -> str:
    """A document-capture paste handler that takes over from editor.js (which prevent-defaults
    paste and fires a payload-less bridgeCommand('paste')). Inserts via the editor's pasteHTML."""
    return templating.render("paste_handler.html.jinja")


def editor_links_js() -> str:
    """Wraps the bridge so the editor toolbar's host-dependent buttons work in the browser:
    'attach' -> a file picker -> /upload_media -> pasteHTML(img/[sound:]); 'preview' ->
    open /preview/<nid> in a new tab (browse mode only). 'fields'/'cards' are added by F5/F6.
    Everything else passes through to the real bridge (blur/key/saveTags/paste...)."""
    return templating.render("editor_links.html.jinja")


def editor_page_body(nid: int) -> str:
    return templating.render(
        "editor_page_body.html.jinja",
        nid=int(nid),
        paste_handler_js=paste_handler_js(),
        editor_links_js=editor_links_js(),
    )


def make_editor_handler(service, hub):
    state: dict[str, int | None] = {"nid": None}

    async def handler(arg: str):
        head, _, rest = arg.partition(":")
        if head == "load":
            nid = int(rest)
            state["nid"] = nid
            data = await service.run(lambda col: _build_load(col, nid))
            await hub.push_call("editor", "ankiwebLoadNote", [data])
        elif head in ("blur", "key"):
            parts = rest.split(":", 2)
            if len(parts) == 3:
                ord_, nid, htmlval = int(parts[0]), int(parts[1]), parts[2]
                if head == "blur":
                    await service.run_op(
                        lambda col: _save_field(col, nid, ord_, htmlval),
                        initiator="editor",
                    )
                else:
                    await service.run(lambda col: _save_field(col, nid, ord_, htmlval))
        elif head == "saveTags":
            if state["nid"] is not None:
                tags = json.loads(rest)
                nid = state["nid"]

                def fn(col):
                    n = col.get_note(nid)
                    n.tags = list(tags)
                    return col.update_note(n, skip_undo_entry=True)

                await service.run_op(fn, initiator="editor")

    return handler
