from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str = "", errors: list[dict] | None = None):
        super().__init__(detail)
        self.detail = detail or self.__class__.__name__
        self.errors = errors or []


class NotFound(AppError):
    status_code = 404

    def __init__(self, detail: str = "Not found.", errors=None):
        super().__init__(detail, errors)


class Unauthorized(AppError):
    status_code = 401

    def __init__(self, detail: str = "Sign in to continue.", errors=None):
        super().__init__(detail, errors)


class Forbidden(AppError):
    status_code = 403

    def __init__(self, detail: str = "You do not have permission to do this.", errors=None):
        super().__init__(detail, errors)


class Conflict(AppError):
    status_code = 409


class Invalid(AppError):
    status_code = 422

    def __init__(self, detail: str = "Some fields need attention.", errors=None):
        super().__init__(detail, errors)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "errors": exc.errors},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = [
            {
                "field": ".".join(str(p) for p in e.get("loc", [])[1:]),
                "message": e.get("msg", "Invalid value."),
            }
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": "Some fields need attention.", "errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        if exc.status_code == 404:
            detail = "Not found."
        return JSONResponse(status_code=exc.status_code, content={"detail": detail, "errors": []})
