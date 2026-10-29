"""Preview and confirm one-time deck emoji migration.

Include contract: call render_migration_region(col, lang) inside service.run and
place the returned HTML on the deck page. The stable patch target is
#deck-migrate-region; the coordinator refreshes #deck-list on migrateDone.
"""

from collections.abc import Callable

from anki.collection import Collection
from datastar_py.attributes import SignalValue
from datastar_py.fastapi import DatastarResponse, ReadSignals
from datastar_py.fastapi import ServerSentEventGenerator as SSE
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ankiweb.adapters.inbound.http_shared.templating import render
from ankiweb.core.app_client.emoji_migration import (
    MigrationResult,
    apply_emoji_migration,
    filtered_deck_warning_count,
    plan_emoji_migration,
)
from ankiweb.core.app_client.lang import ResolvedLang
from ankiweb.core.app_client.strings import s
from ankiweb.core.ports import CollectionPort


def render_migration_region(
    col: Collection, lang: ResolvedLang, result: MigrationResult | None = None
) -> str:
    """Render the persistent migration patch target and optional result."""
    # Deferred to avoid a cycle when the deck router registers these routes.
    from ankiweb.adapters.inbound.http_app.decks import _js_literal

    plan = plan_emoji_migration(col)
    selected = [item.deck_id for item in plan if item.status == "ready"]
    return render(
        "app/_deck_migrate.html.jinja",
        app_lang=lang,
        migration_plan=plan,
        migration_ready=len(selected),
        migration_ids_js=_js_literal(selected),
        migration_id_literals={
            item.deck_id: _js_literal(item.deck_id) for item in plan
        },
        migration_filtered_count=filtered_deck_warning_count(col, plan),
        migration_result=result,
    )


def add_decks_migrate_routes(
    router: APIRouter, get_service: Callable[[], CollectionPort], lang: ResolvedLang
) -> None:
    """Attach preview and confirmation routes to the guarded app router."""

    @router.get("/decks/migrate-emoji", response_class=HTMLResponse)
    async def preview() -> str:
        return await get_service().run(lambda col: render_migration_region(col, lang))

    @router.post("/decks/migrate-emoji")
    async def apply(payload: ReadSignals = None) -> DatastarResponse:
        ids = payload.get("migrateIds") if isinstance(payload, dict) else None
        if (
            not isinstance(ids, list)
            or not ids
            or any(
                type(value) is not int or value <= 0 or value >= 2**63 for value in ids
            )
        ):
            return DatastarResponse(
                SSE.patch_signals(
                    {
                        "migrateError": s(
                            "app_decks_migrate_select", lang=lang.catalog_lang
                        )
                    }
                )
            )
        service = get_service()
        result = await service.run_op(
            lambda col: apply_emoji_migration(col, ids), initiator="app"
        )

        def snapshot(col: Collection) -> tuple[str, list[SignalValue]]:
            fragment = render_migration_region(col, lang, result)
            remaining: list[SignalValue] = [
                item.deck_id
                for item in plan_emoji_migration(col)
                if item.status == "ready"
            ]
            return fragment, remaining

        fragment, remaining = await service.run(snapshot)
        return DatastarResponse(
            [
                SSE.patch_elements(fragment, selector="#deck-migrate-region"),
                SSE.patch_signals(
                    {
                        "migrateDone": True,
                        "migrateOpen": False,
                        "migrateError": "",
                        "migrateIds": remaining,
                    }
                ),
            ]
        )
