"""Search engines and the public Trust Center (spec §21 F9): the page is `noindex` unless the client opts in. The API
response carries the header; this middleware adds it to the HTML of /trust/<slug> too, so crawlers that do not run
JavaScript see it."""
from fastapi import FastAPI, Request

from app.trust.models import TrustCenterPage


def _indexable(app: FastAPI, slug: str) -> bool:
    from sqlalchemy import select

    with app.state.sessionmaker() as db:
        p = db.scalar(select(TrustCenterPage).where(TrustCenterPage.slug == slug.lower(), TrustCenterPage.deleted_at.is_(None)))
        return bool(p is not None and p.live and p.indexable)


def install_robots(app: FastAPI) -> None:
    @app.middleware("http")
    async def trust_robots(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if request.method == "GET" and path.startswith("/trust/"):
            slug = path[len("/trust/"):].strip("/").split("/")[0]
            if not slug or not _indexable(app, slug):
                response.headers["X-Robots-Tag"] = "noindex"
        return response
