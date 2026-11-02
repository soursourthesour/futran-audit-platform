"""Policy builder API (spec §21 F7, screen 27). Client side: /policies. Futran side: /futran/policies (the Chief Auditor
records the team that tailored a policy, which drives the Lead Auditor independence check)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.files.models import FileObject
from app.policies import mail_links  # noqa: F401  (registers the acknowledgment link and its email template)
from app.policies import service as svc
from app.policies import templates as T
from app.policies.models import PolicyDocument
from app.policy.actions import Action
from app.policy.authorize import authorize, visible_org_ids
from app.tenancy.models import Organization, User

router = APIRouter(tags=["policies"])


class StartIn(BaseModel):
    template_code: str
    commitment_id: str | None = None


class AnswersIn(BaseModel):
    answers: dict
    regenerate: bool = False


class TextIn(BaseModel):
    blocks: list


class NoteIn(BaseModel):
    note: str | None = None


class ApproveIn(BaseModel):
    acknowledgment: dict | None = None


class TeamIn(BaseModel):
    user_ids: list[str] = []


def _client(actor: Actor) -> Organization:
    if actor.is_futran:
        raise NotFound()
    return actor.organization


def _can(db: Session, actor: Actor, action: Action, org_id: str) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id)
        return True
    except (Forbidden, NotFound):
        return False


def _load(db: Session, actor: Actor, policy_id: str, action: Action) -> PolicyDocument:
    org = _client(actor)
    authorize(db, actor, action, org_id=org.id)
    return svc.get(db, org.id, policy_id)


def _detail(db: Session, actor: Actor, p: PolicyDocument) -> dict:
    org_id = p.organization_id
    return svc.doc_out(db, p) | {"can": {"edit": _can(db, actor, Action.EDIT_POLICIES, org_id) and p.status == "draft",
                                         "approve": _can(db, actor, Action.APPROVE_POLICIES, org_id),
                                         "request_review": _can(db, actor, Action.EDIT_POLICIES, org_id) and not p.futran_review_requested_at}}


@router.get("/policies")
def list_policies(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(actor)
    authorize(db, actor, Action.VIEW_POLICIES, org_id=org.id)
    rows = db.scalars(select(PolicyDocument).where(PolicyDocument.organization_id == org.id, PolicyDocument.deleted_at.is_(None))
                      .order_by(PolicyDocument.title, PolicyDocument.version_no.desc()))
    return {"templates": [svc.template_out(t) for t in sorted(T.library().values(), key=lambda t: t.name)],
            "policies": [svc.doc_out(db, p, full=False) for p in rows],
            "commitments": svc.open_commitments(db, org.id),
            "can": {"edit": _can(db, actor, Action.EDIT_POLICIES, org.id), "approve": _can(db, actor, Action.APPROVE_POLICIES, org.id)}}


@router.get("/policy-templates/{code}")
def get_template(code: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """A template's questions and its sample draft, for the library preview."""
    org = _client(actor)
    authorize(db, actor, Action.VIEW_POLICIES, org_id=org.id)
    t = T.library().get(code)
    if t is None:
        raise NotFound()
    return svc.template_out(t) | {"questions": t.questions, "blocks": T.render(t, T.defaults(t, org.name))}


@router.post("/policies")
def start(body: StartIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _client(actor)
    authorize(db, actor, Action.EDIT_POLICIES, org_id=org.id)
    return _detail(db, actor, svc.start(db, actor.user, org, body.template_code, body.commitment_id))


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _detail(db, actor, _load(db, actor, policy_id, Action.VIEW_POLICIES))


@router.put("/policies/{policy_id}/answers")
def put_answers(policy_id: str, body: AnswersIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.EDIT_POLICIES)
    return _detail(db, actor, svc.save_answers(db, actor.user, p, body.answers, body.regenerate))


@router.put("/policies/{policy_id}/text")
def put_text(policy_id: str, body: TextIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.EDIT_POLICIES)
    return _detail(db, actor, svc.save_text(db, actor.user, p, body.blocks))


@router.post("/policies/{policy_id}/submit")
def submit(policy_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.EDIT_POLICIES)
    return _detail(db, actor, svc.submit(db, request.app.state.settings, actor.user, p))


@router.post("/policies/{policy_id}/return")
def return_policy(policy_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.APPROVE_POLICIES)
    return _detail(db, actor, svc.return_to_draft(db, actor.user, p, body.note))


@router.post("/policies/{policy_id}/approve")
def approve(policy_id: str, body: ApproveIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.APPROVE_POLICIES)
    return _detail(db, actor, svc.approve(db, request.app.state.settings, actor.user, p, body.acknowledgment))


@router.post("/policies/{policy_id}/acknowledgments/send")
def send_acks(policy_id: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.APPROVE_POLICIES)
    s = svc.send_acknowledgments(db, request.app.state.settings, actor.user, p, body)
    return {"send_id": s.id, "recipients": s.recipient_count, "acknowledgments": svc.ack_stats(db, p)}


@router.get("/policies/{policy_id}/acknowledgments")
def list_acks(policy_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.VIEW_POLICIES)
    authorize(db, actor, Action.EDIT_POLICIES, org_id=p.organization_id)  # names of individual staff: the people who run the policy
    return {"stats": svc.ack_stats(db, p), "rows": svc.ack_rows(db, p)}


@router.post("/policies/{policy_id}/new-version")
def new_version(policy_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.APPROVE_POLICIES)
    return _detail(db, actor, svc.new_version(db, actor.user, p))


@router.post("/policies/{policy_id}/futran-review")
def futran_review(policy_id: str, body: NoteIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _load(db, actor, policy_id, Action.EDIT_POLICIES)
    return _detail(db, actor, svc.request_futran_review(db, actor.user, p, body.note))


def _pdf(db: Session, request: Request, p: PolicyDocument) -> Response:
    from app.files.service import read

    f = db.get(FileObject, p.published_file_id) if p.published_file_id else None
    data = read(request.app.state.settings, f) if f is not None else svc.render_pdf(db, p)
    name = f"{p.title} v{p.version_no}{'' if f else ' draft'}.pdf".encode("ascii", "replace").decode().replace('"', "")
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@router.get("/policies/{policy_id}/pdf")
def pdf(policy_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _pdf(db, request, _load(db, actor, policy_id, Action.VIEW_POLICIES))


# ---- Futran side
def _futran_policy(db: Session, actor: Actor, policy_id: str, action: Action) -> PolicyDocument:
    if not actor.is_futran:
        raise NotFound()
    p = db.get(PolicyDocument, policy_id)
    if p is None or p.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, org_id=p.organization_id)
    return p


@router.get("/futran/policies")
def futran_list(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Client policies Futran was asked to review or has tailored. Futran does not see a client's other policies."""
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_CLIENT_POLICIES, list_view=True)
    allowed = visible_org_ids(db, actor)
    rows = db.scalars(select(PolicyDocument).where(PolicyDocument.deleted_at.is_(None)).order_by(PolicyDocument.futran_review_requested_at.desc()))
    out = []
    for p in rows:
        if not (p.futran_review_requested_at or p.authored_by_futran_team) or (allowed is not None and p.organization_id not in allowed):
            continue
        org = db.get(Organization, p.organization_id)
        out.append(svc.doc_out(db, p, full=False) | {"client_id": p.organization_id, "client_name": org.name if org else "", "review_note": p.futran_review_note})
    team = [{"id": u.id, "name": u.name} for u in db.scalars(select(User).join(Organization, Organization.id == User.organization_id)
                                                              .where(Organization.type == "futran", User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))]
    return {"policies": out, "people": team, "can": {"record": _can(db, actor, Action.RECORD_POLICY_AUTHORS, actor.organization.id)}}


@router.put("/futran/policies/{policy_id}/team")
def futran_team(policy_id: str, body: TeamIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _futran_policy(db, actor, policy_id, Action.RECORD_POLICY_AUTHORS)
    return svc.doc_out(db, svc.record_futran_team(db, actor.user, p, body.user_ids), full=False)


@router.get("/futran/policies/{policy_id}/pdf")
def futran_pdf(policy_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    p = _futran_policy(db, actor, policy_id, Action.VIEW_CLIENT_POLICIES)
    if not (p.futran_review_requested_at or p.authored_by_futran_team):
        raise NotFound()
    return _pdf(db, request, p)


# ---- file downloads of published policies (/files/{id})
def file_access(db: Session, actor: Actor, f: FileObject) -> None:
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_CLIENT_POLICIES, org_id=f.organization_id)
        return
    if actor.organization.id != f.organization_id:
        raise NotFound()
    authorize(db, actor, Action.VIEW_POLICIES, org_id=f.organization_id)


def _register_file_access() -> None:
    from app.files.router import FILE_ACCESS

    FILE_ACCESS["policy_document"] = file_access


_register_file_access()
