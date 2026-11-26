"""Browser security headers on every response (BUG-H05).

The web app is one built React bundle served from this origin: no inline script, no eval, fonts and images from
/assets. Styles are allowed inline because React sets style attributes and the email previews (srcdoc iframes, which
inherit this policy) carry the message's own inline CSS. A route that sets its own Content-Security-Policy (file
downloads, generated SVG) keeps it.
"""
from starlette.types import ASGIApp, Message, Receive, Scope, Send

APP_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
           "object-src 'none'; base-uri 'self'; form-action 'self'")
# Swagger UI (FastAPI's page) loads its script and styles from jsDelivr, starts with an inline script and shows the
# FastAPI favicon. Only the API documentation pages get this policy.
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")
DOCS_PATHS = ("/api/docs", "/api/public/v1/docs", "/api/public/v1/library/docs")
HSTS = "max-age=31536000"

_COMMON = ((b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"strict-origin-when-cross-origin"))


class SecurityHeaders:
    """Pure ASGI middleware, so streamed downloads and background tasks behave as without it."""

    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        csp = (DOCS_CSP if path.startswith(DOCS_PATHS) else APP_CSP).encode()

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                have = {k.lower() for k, _ in headers}
                extra = [*_COMMON, (b"content-security-policy", csp)]
                if path.startswith("/api/"):  # API answers carry client data: not kept by caches (review 11-25 #8)
                    extra.append((b"cache-control", b"no-store"))
                if self.hsts:
                    extra.append((b"strict-transport-security", HSTS.encode()))
                headers += [(k, v) for k, v in extra if k not in have]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
