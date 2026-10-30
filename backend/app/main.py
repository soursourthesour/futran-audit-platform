import importlib
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import Engine

from app.core.config import VERSION, Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import install_error_handlers

STATIC_DIR = Path(__file__).parent / "static"


def _health_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health(request: Request):
        s: Settings = request.app.state.settings
        return {
            "status": "ok",
            "test_mode": s.test_mode,
            "data_region": s.data_region_label,
            "version": VERSION,
        }

    return router


WEAK_KEYS = {"change-me", "change-me-in-env", "", "secret"}


def check_secret_key(settings: Settings) -> None:
    if settings.mfa_required and (settings.secret_key in WEAK_KEYS or len(settings.secret_key) < 32):
        raise RuntimeError(
            "SECRET_KEY in .env is missing, a placeholder, or shorter than 32 characters. "
            "Set a long random value before switching on sign-in codes (MFA_REQUIRED=true)."
        )


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    check_secret_key(settings)
    engine = engine or make_engine(settings.database_url)

    app = FastAPI(title="Futran Audit Platform", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    install_error_handlers(app)

    importlib.import_module("app.models_registry")
    from app.routers_registry import api_routers

    app.include_router(_health_router(), prefix="/api/v1")
    for r in api_routers():
        app.include_router(r, prefix="/api/v1")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str):
        return JSONResponse(status_code=404, content={"detail": "Not found.", "errors": []})

    _mount_spa(app)
    if settings.seed_on_start:
        from app.regmaster.startup import seed_if_empty

        seed_if_empty(app)
        from app.regmaster.startup import repair_on_start

        repair_on_start(app)
        from app.litigation.startup import court_sources_on_start  # v0.6 WS-D

        court_sources_on_start(app)
    _start_scheduler(app, settings)
    return app


def _mount_spa(app: FastAPI) -> None:
    index = STATIC_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"detail": "The web interface has not been built. Run `npm run build` in frontend/."},
        )


def _start_scheduler(app: FastAPI, settings: Settings) -> None:
    if settings.disable_scheduler:
        return
    try:
        from app.notifications.jobs import start_scheduler
    except ImportError:
        return
    start_scheduler(app)
