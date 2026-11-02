"""Trust Center API (spec §21 F9, screen 32): the client's editor (/trust), the Futran Chief Auditor's confirmation queue
(/trust/confirmations) and the public page (/public/trust/{slug}, no sign-in)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.core.ratelimit import client_ip, limiter
from app.policy.actions import Action
from app.policy.authorize import authorize, visible_org_ids
from app.trust import service as svc

router = APIRouter(tags=["trust"])


def _client(actor: Actor):
    if actor.is_futran:
        raise NotFound()
    return actor.organization


def _can(db: Session, actor: Actor, action: Action, org_id: str) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id)
        return True
    except (Forbidden, NotFound):
        return False


def _editor(db: Session, actor: Actor) -> dict:
    org = actor.organization
    p = svc.page_for(db, org.id)
    return {"page": svc.page_out(p) if p else None, "items": [svc.item_out(db, i) for i in svc.items(db, p)] if p else [],
            "sources": svc.sources(db, org.id), "views": svc.views(db, p) if p else [], "kinds": [{"value": k, "label": v} for k, v in svc.KIND_LABELS.items()],
            "has_signed_report": svc.latest_final_report(db, org.id) is not None, "can": {"edit": _can(db, actor, Action.EDIT_TRUST_CENTER, org.id)}}


@router.get("/trust")
def get_trust(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(actor)
    authorize(db, actor, Action.VIEW_TRUST_CENTER, org_id=org.id)
    return _editor(db, actor)


@router.put("/trust/page")
def put_page(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(actor)
    authorize(db, actor, Action.EDIT_TRUST_CENTER, org_id=org.id)
    return svc.page_out(svc.save_page(db, actor.user, org, body))


def _page(db: Session, actor: Actor):
    org = _client(actor)
    authorize(db, actor, Action.EDIT_TRUST_CENTER, org_id=org.id)
    p = svc.page_for(db, org.id)
    if p is None:
        raise NotFound("Set up the page first.")
    return p


@router.post("/trust/items")
def add_item(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.item_out(db, svc.create_item(db, actor.user, _page(db, actor), body))


def _item(db: Session, actor: Actor, item_id: str):
    p = _page(db, actor)
    it = svc.get_item(db, p.organization_id, item_id)
    if it.page_id != p.id:
        raise NotFound()
    return it


@router.put("/trust/items/{item_id}")
def edit_item(item_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.item_out(db, svc.update_item(db, actor.user, _item(db, actor, item_id), body))


@router.post("/trust/items/{item_id}/approve")
def approve_item(item_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.item_out(db, svc.approve_item(db, request.app.state.settings, actor.user, _item(db, actor, item_id)))


@router.post("/trust/items/{item_id}/withdraw")
def withdraw_item(item_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.item_out(db, svc.withdraw_item(db, actor.user, _item(db, actor, item_id)))


@router.delete("/trust/items/{item_id}")
def delete_item(item_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    svc.delete_item(db, actor.user, _item(db, actor, item_id))
    return {"deleted": True}


# ---- Futran Chief Auditor
@router.get("/trust/confirmations")
def confirmations(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.CONFIRM_TRUST_ITEMS, list_view=True)
    return {"items": svc.confirmation_queue(db, visible_org_ids(db, actor))}


def _futran_item(db: Session, actor: Actor, item_id: str):
    if not actor.is_futran:
        raise NotFound()
    it = svc.get_item(db, None, item_id)
    authorize(db, actor, Action.CONFIRM_TRUST_ITEMS, org_id=it.organization_id)
    return it


@router.post("/trust/items/{item_id}/confirm")
def confirm(item_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.item_out(db, svc.confirm_item(db, actor.user, _futran_item(db, actor, item_id), body.get("note")))


@router.post("/trust/items/{item_id}/return")
def return_item(item_id: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.item_out(db, svc.return_item(db, actor.user, _futran_item(db, actor, item_id), body.get("note")))


# ---- public (no sign-in). Every lookup starts from the slug's page; items and documents are matched to that page.
def _noindex(response: Response, p) -> None:
    if not p.indexable:
        response.headers["X-Robots-Tag"] = "noindex"


@router.get("/public/trust/{slug}")
def public_page(slug: str, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    limiter(request, "trust_public", 120).check(client_ip(request))
    p = svc.public_page(db, slug)
    svc.count_view(db, p)
    _noindex(response, p)
    response.headers["Cache-Control"] = "no-store"
    return svc.public_out(db, p)


@router.post("/public/trust/{slug}/nda")
def public_nda(slug: str, body: dict, request: Request, response: Response, db: Session = Depends(get_db, scope="function")):
    limiter(request, "trust_nda", 20).check(client_ip(request))
    p = svc.public_page(db, slug)
    raw, exp = svc.accept_nda(db, p, body)
    _noindex(response, p)
    return {"access_token": raw, "expires_at": exp.isoformat()}


@router.get("/public/trust/{slug}/items/{item_id}/document")
def public_document(slug: str, item_id: str, request: Request, access: str | None = None, db: Session = Depends(get_db, scope="function")):
    limiter(request, "trust_public", 120).check(client_ip(request))
    p = svc.public_page(db, slug)
    data, name = svc.document(db, request.app.state.settings, p, item_id, access)
    safe = name.encode("ascii", "replace").decode().replace('"', "")
    headers = {"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    if not p.indexable:
        headers["X-Robots-Tag"] = "noindex"
    return Response(content=data, media_type="application/pdf", headers=headers)
