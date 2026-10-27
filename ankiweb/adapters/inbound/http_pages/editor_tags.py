from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Query


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tags/complete")
    async def complete_tag(
        input: Annotated[str, Query(description="Tag prefix or search string")] = "",
        match_limit: Annotated[
            int, Query(alias="matchLimit", description="Max tags to return")
        ] = 500,
    ):
        service = get_service()

        def _complete(col):
            clean_input = input.strip().strip(":")
            return list(
                col._backend.complete_tag(input=clean_input, match_limit=match_limit)
            )

        tags = await service.run(_complete)
        return {"tags": tags}

    @router.get("/api/tags/all")
    async def all_tags():
        service = get_service()

        def _all(col):
            return list(col.tags.all())

        tags = await service.run(_all)
        return {"tags": tags}

    return router
