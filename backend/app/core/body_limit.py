"""Refuse request bodies larger than the upload limit before they are read (review 11-25 #2).

Without this, Starlette spools a multipart body to a temporary file before any route dependency runs, so a caller with
no session could send gigabytes to an upload route and fill the disk. A declared Content-Length over the limit is
refused at once; a chunked body is counted as it arrives and cut off once it passes the limit. The limit is the upload
limit plus 1 MB for multipart framing and form fields, read from the app's settings on each request.
"""
import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

SLACK = 1024 * 1024


class BodyTooLarge(Exception):
    pass


def _detail(limit_mb: int) -> bytes:
    return json.dumps({"detail": f"The request is over the {limit_mb} MB upload limit."}).encode()


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        settings = getattr(getattr(scope.get("app"), "state", None), "settings", None)
        limit_mb = int(getattr(settings, "max_upload_mb", 50) or 50)
        limit = limit_mb * 1024 * 1024 + SLACK
        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._refuse(send, limit_mb)
            return
        seen = 0
        started = over = replaced = False

        async def counting_receive() -> Message:
            nonlocal seen, over
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    over = True
                    raise BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            # FastAPI turns an error while reading a form into its own 400; once the limit was passed, answer 413.
            nonlocal started, replaced
            if over and not started:
                if message["type"] == "http.response.start":
                    started = replaced = True
                    await self._refuse(send, limit_mb)
                return
            if replaced:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await self._refuse(send, limit_mb)

    @staticmethod
    async def _refuse(send: Send, limit_mb: int) -> None:
        body = _detail(limit_mb)
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})
