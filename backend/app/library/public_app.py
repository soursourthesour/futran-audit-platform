"""The website library API, mounted at /api/public/v1/library as its own application (its reference is
/api/public/v1/library/openapi.json; the Swagger page, in test mode only, is /api/public/v1/library/docs).

Read-only. Futran's website calls it with a website API key (`X-API-Key: <key>` or `Authorization: Bearer <key>`), which is
not tied to a client organization: it opens the published law library and AI litigation tracker only (app.library.content).

Each key has its own rate limit (429 with Retry-After) and its own list of browser origins (CORS; a key with none is for
server-side calls only). Responses carry an ETag, `Cache-Control: public, max-age=300, stale-while-revalidate=600` and
`X-Library-Last-Refreshed`; If-None-Match answers 304. A small server-side cache keyed on the query is dropped whenever
the underlying records change (content.fingerprint) and after CACHE_SECONDS in any case.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Invalid, install_error_handlers
from app.core.ratelimit import TooManyRequests, client_ip, limiter
from app.library import content, guard
from app.library import keys as K
from app.library.models import WebsiteApiKey

PREFIX = "/api/public/v1/library"
CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=600"
VARY = "Origin, X-API-Key, Authorization"
CACHE_SECONDS = 60  # a cached body is rebuilt at least this often, even if no fingerprint column moved
CACHE_ENTRIES = 500
BAD_KEYS_PER_MINUTE = 30  # per network address: requests with a missing or wrong key, and CORS preflights
ORIGINS_SECONDS = 60  # how long preflights use the cached set of allowed origins
EXPOSE = "ETag, X-Library-Last-Refreshed, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining"
ALLOW_HEADERS = "X-API-Key, Authorization, If-None-Match, Content-Type"
NEVER = "never"
_CACHE_LOCK = threading.Lock()  # sync endpoints run in a thread pool


class LibraryError(Exception):
    def __init__(self, status: int, detail: str, headers: dict | None = None):
        self.status, self.detail, self.headers = status, detail, headers or {}

    def response(self) -> JSONResponse:
        return JSONResponse({"detail": self.detail, "errors": []}, status_code=self.status, headers=self.headers)


# ------------------------------------------------------------------ the key

def _raw_key(request: Request) -> str | None:
    k = request.headers.get("x-api-key")
    if k:
        return k.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def website_key(request: Request, db: Session = Depends(get_db, scope="function")) -> WebsiteApiKey:
    raw = _raw_key(request)
    k = K.find_active(db, raw) if raw else None
    if k is None:
        try:  # a guessed key cannot be tried at speed
            limiter(request, "library_bad_key", BAD_KEYS_PER_MINUTE).check(client_ip(request))
        except TooManyRequests:
            raise LibraryError(429, "Too many requests without a valid website API key. Wait a minute and try again.", {"Retry-After": "60"}) from None
        raise LibraryError(401, "Send a website API key in the X-API-Key header." if not raw else "This website API key is not valid or has been revoked.",
                           {"WWW-Authenticate": 'Bearer realm="library"'})
    origin = request.headers.get("origin")
    if origin:
        if K.normalize_origin(origin) not in (k.allowed_origins or []):
            raise LibraryError(403, "This website API key is not allowed from this origin.")
        request.state.cors_origin = origin
    lim = limiter(request, f"website_key:{k.id}", k.rate_limit_per_minute)
    try:
        lim.check(k.id)
    except TooManyRequests:
        hits = lim.hits[k.id]
        wait = max(1, min(60, int(lim.window - (time.monotonic() - hits[0])) + 1)) if hits else 60
        raise LibraryError(429, "Too many requests for this website API key. Wait and try again.",
                           {"Retry-After": str(wait), "X-RateLimit-Limit": str(k.rate_limit_per_minute), "X-RateLimit-Remaining": "0"}) from None
    request.state.rate = (k.rate_limit_per_minute, max(0, k.rate_limit_per_minute - len(lim.hits[k.id])))
    K.touch(k)
    return k


def _only(request: Request, allowed: set[str]) -> None:
    extra = sorted(set(request.query_params) - allowed)
    if extra:
        raise Invalid(f"Unknown parameter: {', '.join(extra)[:120]}.", [{"field": p[:60], "message": "Not a parameter of this endpoint."} for p in extra[:10]])


# ------------------------------------------------------------------ caching

def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    bare = etag.strip('"')
    return any(t.strip().removeprefix("W/").strip('"') == bare for t in header.split(","))


def _serve(request: Request, db: Session, name: str, params: dict, build, kind: str) -> Response:
    store: OrderedDict = request.app.state.__dict__.setdefault("_library_cache", OrderedDict())
    fp = (content.fingerprint(db), guard.names_fingerprint(db))  # a new client name must reach cached bodies too
    ck = (name, tuple(sorted((k, str(v)) for k, v in params.items() if v is not None)))
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = store.get(ck)
    if hit is None or hit["fp"] != fp or now - hit["at"] > CACHE_SECONDS:
        data = guard.scrub(jsonable_encoder(build()), guard.pattern(request.app.state, db), f"{name} {params.get('id', '')}".strip())
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        if kind == "both":
            refreshed = max((t for t in (content.last_refreshed(db, "law"), content.last_refreshed(db, "litigation")) if t), default=None)
        else:
            refreshed = content.last_refreshed(db, kind)
        hit = {"fp": fp, "at": now, "body": body, "etag": '"' + hashlib.sha256(body).hexdigest()[:32] + '"', "refreshed": refreshed or NEVER}
        with _CACHE_LOCK:
            store[ck] = hit
            store.move_to_end(ck)
            while len(store) > CACHE_ENTRIES:
                store.popitem(last=False)
    limit, remaining = getattr(request.state, "rate", (None, None))
    headers = {"ETag": hit["etag"], "Cache-Control": CACHE_CONTROL, "X-Library-Last-Refreshed": hit["refreshed"]}
    if limit is not None:
        headers |= {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining)}
    if _matches(request.headers.get("if-none-match"), hit["etag"]):
        return Response(status_code=304, headers=headers)
    return Response(hit["body"], media_type="application/json", headers=headers)


# ------------------------------------------------------------------ CORS

class LibraryCors:
    """CORS for the library only. A preflight carries no key, so it is allowed for an origin some active key lists; the
    real request is then checked against its own key's origins (website_key), which sets the allow-origin header."""

    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        if scope["method"] == "OPTIONS" and origin and "access-control-request-method" in headers:
            await self._preflight(scope, origin, headers["access-control-request-method"], send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                hs = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"vary"]
                hs.append((b"vary", VARY.encode()))
                allowed = (scope.get("state") or {}).get("cors_origin")
                if origin and allowed:
                    hs += [(b"access-control-allow-origin", allowed.encode("latin-1")), (b"access-control-expose-headers", EXPOSE.encode())]
                message = {**message, "headers": hs}
            await send(message)

        await self.app(scope, receive, send_with_cors)

    async def _preflight(self, scope, origin: str, method: str, send) -> None:
        request = Request(scope)
        try:  # a preflight carries no key: it counts against the same per-address allowance as a missing or wrong key
            limiter(request, "library_bad_key", BAD_KEYS_PER_MINUTE).check(client_ip(request))
        except TooManyRequests:
            body = json.dumps({"detail": "Too many requests from this address. Wait a minute and try again.", "errors": []}).encode()
            await _send(send, 429, [(b"content-type", b"application/json"), (b"retry-after", b"60"), (b"vary", VARY.encode())], body)
            return
        norm = K.normalize_origin(origin)
        ok = bool(norm) and method.upper() == "GET" and norm in allowed_origins(self.state)
        if ok:
            await _send(send, 204, [(b"access-control-allow-origin", origin.encode("latin-1")), (b"access-control-allow-methods", b"GET, OPTIONS"),
                                    (b"access-control-allow-headers", ALLOW_HEADERS.encode()), (b"access-control-max-age", b"600"), (b"vary", VARY.encode())])
            return
        body = json.dumps({"detail": "This origin is not allowed to call the library API.", "errors": []}).encode()
        await _send(send, 403, [(b"content-type", b"application/json"), (b"vary", VARY.encode())], body)


def allowed_origins(state) -> set[str]:
    """Every origin an active key lists, kept for ORIGINS_SECONDS (dropped at once when a key is created or revoked)."""
    now = time.monotonic()
    hit = state.__dict__.get(K.ORIGIN_CACHE)
    if hit is None or now - hit[0] > ORIGINS_SECONDS:
        db = state.sessionmaker()
        try:
            hit = (now, K.active_origins(db))
        finally:
            db.close()
        state.__dict__[K.ORIGIN_CACHE] = hit
    return hit[1]


async def _send(send, status: int, headers: list, body: bytes = b"") -> None:
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


# ------------------------------------------------------------------ endpoints

LawSort = Literal["geography", "name", "effective_on", "-effective_on"]
CaseSort = Literal["geography", "name", "-last_update_on"]
PAGE = {"ge": 1, "le": 10000}
LIMIT = {"ge": 1, "le": 200}


def build(main: FastAPI) -> FastAPI:
    from app.core.config import VERSION

    docs = main.state.settings.test_mode
    sub = FastAPI(title="Futran Audit Platform website library API", version=f"1 ({VERSION})", docs_url="/docs" if docs else None, openapi_url="/openapi.json",
                  redoc_url=None, description="Read-only access to the published law library and AI litigation tracker, for Futran's website. "
                                              "Send a website API key as `X-API-Key: <key>` (or `Authorization: Bearer <key>`).")
    sub.state = main.state  # one settings object, session factory, rate-limit store and cache
    install_error_handlers(sub)

    @sub.exception_handler(LibraryError)
    async def _lib(_: Request, exc: LibraryError):
        return exc.response()

    sub.add_middleware(LibraryCors, state=main.state)

    @sub.get("/laws", tags=["law library"], summary="Laws in the law library")
    def laws(request: Request, region: str | None = Query(None, max_length=40), status: str | None = Query(None, max_length=40),
             applies_to: str | None = Query(None, max_length=40), topic: str | None = Query(None, max_length=40), q: str | None = Query(None, max_length=200),
             show: Literal["library", "all"] = "library", sort: LawSort = "geography", page: int = Query(1, **PAGE), limit: int = Query(50, **LIMIT),
             _: WebsiteApiKey = Depends(website_key), db: Session = Depends(get_db, scope="function")):
        """Search (`q`: law name, citation, geography or requirement text) and filter as the app's Law library does."""
        _only(request, {"region", "status", "applies_to", "topic", "q", "show", "sort", "page", "limit"})
        p = {"region": region, "status": status, "applies_to": applies_to, "topic": topic, "q": q, "show": show, "sort": sort, "page": page, "limit": limit}
        return _serve(request, db, "laws", p, lambda: content.law_list(db, **p), "law")

    @sub.get("/laws/{law_id}", tags=["law library"], summary="One law's full record")
    def law(law_id: str, request: Request, _: WebsiteApiKey = Depends(website_key), db: Session = Depends(get_db, scope="function")):
        _only(request, set())
        return _serve(request, db, "law", {"id": law_id}, lambda: content.law_record(db, law_id), "law")

    @sub.get("/cases", tags=["AI court cases"], summary="AI court cases in the litigation tracker")
    def cases(request: Request, stage: str | None = Query(None, max_length=200), area: str | None = Query(None, max_length=160),
              geography: str | None = Query(None, max_length=120), q: str | None = Query(None, max_length=200), sort: CaseSort = "geography",
              page: int = Query(1, **PAGE), limit: int = Query(50, **LIMIT), _: WebsiteApiKey = Depends(website_key), db: Session = Depends(get_db, scope="function")):
        """Filter by `stage` (one or a comma list), `area` and `geography` exactly as /meta lists them; `q` searches name, area, court and description."""
        _only(request, {"stage", "area", "geography", "q", "sort", "page", "limit"})
        if stage and any(s not in content.STAGES for s in stage.split(",")):
            raise Invalid(errors=[{"field": "stage", "message": f"Choose from: {', '.join(content.STAGES)}."}])
        p = {"stage": stage, "area": area, "geography": geography, "q": q, "sort": sort, "page": page, "limit": limit}
        return _serve(request, db, "cases", p, lambda: content.case_list(db, **p), "litigation")

    @sub.get("/cases/{case_id}", tags=["AI court cases"], summary="One case's full record, with the laws it interprets")
    def case(case_id: str, request: Request, _: WebsiteApiKey = Depends(website_key), db: Session = Depends(get_db, scope="function")):
        _only(request, set())
        return _serve(request, db, "case", {"id": case_id}, lambda: content.case_record(db, case_id), "litigation")

    @sub.get("/meta", tags=["library"], summary="Filter values, record counts and when each library was last refreshed")
    def meta(request: Request, _: WebsiteApiKey = Depends(website_key), db: Session = Depends(get_db, scope="function")):
        _only(request, set())
        return _serve(request, db, "meta", {}, lambda: content.meta(db), "both")

    return sub


def mount(main: FastAPI) -> None:
    """Mounted before /api/public/v1, which would otherwise take these paths."""
    main.mount(PREFIX, build(main))
