"""Routers for pages replacing the vendored SvelteKit routes.

Every module in this package that defines ``make_router(get_service) -> APIRouter`` is
mounted automatically.
"""

from __future__ import annotations
import importlib
import pkgutil
from fastapi import APIRouter


def make_pages_router(get_service) -> APIRouter:
    router = APIRouter()
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        make_router = getattr(module, "make_router", None)
        if make_router is not None:
            router.include_router(make_router(get_service))
    return router
