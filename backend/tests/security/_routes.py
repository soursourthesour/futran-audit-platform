"""The app's route table, flattened: every (method, path) the running app answers, with its endpoint and dependencies.

FastAPI includes routers lazily, so `app.routes` holds router wrappers; this walks them, and the mounted public API."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from functools import lru_cache

from fastapi.routing import _iter_routes_with_context
from starlette.routing import Mount

SKIP_METHODS = {"HEAD", "OPTIONS"}


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    endpoint: object = field(compare=False, repr=False)
    calls: tuple = field(compare=False, repr=False, default=())  # endpoint and every dependency callable

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def _dep_calls(dependant):
    for sub in getattr(dependant, "dependencies", []) or []:
        if sub.call is not None:
            yield sub.call
        yield from _dep_calls(sub)


def _walk(routes, prefix: str = ""):
    for orig, ctx in _iter_routes_with_context(routes):
        if isinstance(orig, Mount):
            yield from _walk(orig.routes, prefix + orig.path)
            continue
        path = ctx.path if ctx else getattr(orig, "path", None)
        endpoint = ctx.endpoint if ctx else getattr(orig, "endpoint", None)
        dependant = ctx.dependant if ctx else getattr(orig, "dependant", None)
        methods = (ctx.methods if ctx else getattr(orig, "methods", None)) or set()
        calls = (endpoint, *(_dep_calls(dependant) if dependant is not None else ()))
        for m in sorted(set(methods) - SKIP_METHODS):
            yield RouteInfo(m, prefix + path, endpoint, calls)


def route_table(app) -> list[RouteInfo]:
    return list(_walk(app.routes))


@lru_cache(maxsize=1)
def bare_app():
    """An app on an empty in-memory database, for reading the route table and the OpenAPI document."""
    from app.core.config import Settings
    from app.main import create_app

    s = Settings(database_url="sqlite://", mfa_required=False, email_mode="outbox", secret_key="test-secret-key-not-for-production-0123456789",
                 disable_scheduler=True, seed_on_start=False, file_store=f"local:{tempfile.mkdtemp(prefix='yama-files-')}")
    return create_app(s)


@lru_cache(maxsize=1)
def routes() -> list[RouteInfo]:
    return route_table(bare_app())
