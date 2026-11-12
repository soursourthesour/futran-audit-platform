"""SM-12 public acceptance: no sign-in. Each token resolves to one link for one proposal version; nothing else is
visible through it. Rate limited per token and address."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Invalid
from app.core.ratelimit import client_ip, limiter
from app.proposals import sending

router = APIRouter(prefix="/public/p", tags=["public"])
MAX_PO_BYTES = 10 * 1024 * 1024


def _limit(request: Request, token: str, kind: str) -> None:
    n = sending.VIEWS_PER_MINUTE if kind == "view" else sending.SUBMITS_PER_MINUTE
    limiter(request, f"proposal_link_{kind}", n).check(f"{token[:64]}:{client_ip(request)}")


@router.get("/{token}")
def view(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "view")
    link, p = sending.resolve(db, token)
    if p.status != "accepted":
        sending.mark_opened(db, link, p)
    return sending.public_view(db, link, p)


@router.get("/{token}/pdf")
def pdf(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "view")
    _, p = sending.resolve(db, token)
    data, name = sending.public_pdf(db, request.app.state.settings, p)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", "Cache-Control": "private, no-store"})


@router.post("/{token}/accept")
async def accept(token: str, request: Request, name: str = Form(""), title: str = Form(""), email: str = Form(""), authorised: str = Form(""),
                 po_number: str = Form(""), po_file: UploadFile | None = File(None), db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "submit")
    link, p = sending.resolve(db, token)
    upload = None
    if po_file is not None and po_file.filename:
        data = await po_file.read(MAX_PO_BYTES + 1)
        if len(data) > MAX_PO_BYTES:
            raise Invalid(errors=[{"field": "po_file", "message": "The purchase order can be up to 10 MB."}])
        upload = (data, po_file.filename, po_file.content_type)
    a = sending.accept(db, request.app.state.settings, link, p, name=name, title=title, email=email, authorised=authorised.lower() in ("true", "1", "on", "yes"),
                       po_number=po_number, po_file=upload, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    return {"accepted": True, "name": a.name, "at": a.accepted_at.isoformat()}


@router.post("/{token}/changes")
def changes(token: str, body: dict, request: Request, db: Session = Depends(get_db, scope="function")):
    _limit(request, token, "submit")
    link, p = sending.resolve(db, token)
    sending.request_changes(db, request.app.state.settings, link, p, str(body.get("message") or ""), body.get("name"))
    return {"received": True}
