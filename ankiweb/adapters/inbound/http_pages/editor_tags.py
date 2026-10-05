from __future__ import annotations

from typing import Callable
from fastapi import APIRouter, Query


def make_router(get_service: Callable) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tags/complete")
    async def complete_tag(
        input: str = Query("", description="Tag prefix or search string"),
        match_limit: int = Query(500, alias="matchLimit", description="Max tags to return"),
    ):
        service = get_service()

        def _complete(col):
            clean_input = input.strip().strip(":")
            return list(col._backend.complete_tag(input=clean_input, match_limit=match_limit))

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
