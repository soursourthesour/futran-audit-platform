"""G-08 EU AI Act conformity (`/e/:id/eu-ai-act`, and `/clients/:id/eu-ai-act` for systems with EU geography outside
an EU AI Act engagement). Futran screens; the client's CAICO reads a signed-off summary on the register record.
Every endpoint authorizes against the system's own tenant; the tenant is never taken from the request."""
from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Invalid, NotFound
from app.engagements.models import Engagement
from app.euaiact import rules
from app.euaiact import service as svc
from app.files.models import FileObject
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register.models import RegisterSystem
from app.tenancy.models import Organization

router = APIRouter(tags=["EU AI Act conformity"])


class RecordIn(BaseModel):
    engagement_id: str | None = None
    exposure_basis: str | None = Field(default=None, max_length=300)
    role: str | None = None
    also_deployer: bool | None = None
    classification: str | None = None
    annex_iii_area: str | None = None
    public_service: bool | None = None
    reasoning: str | None = Field(default=None, max_length=8000)
    legal_review_flag: bool | None = None


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)


class StatusIn(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class FriaIn(BaseModel):
    answers: dict[str, str | None] | None = None
    status: str | None = None


def _may(db: Session, actor: Actor, action: Action, org_id: str) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id)
        return True
    except Exception:
        return False


def _system(db: Session, actor: Actor, system_id: str, action: Action) -> RegisterSystem:
    s = db.get(RegisterSystem, system_id)
    if s is None or s.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, org_id=s.organization_id)
    return s


def _engagement(db: Session, actor: Actor, engagement_id: str) -> Engagement:
    if not actor.is_futran:
        raise NotFound()
    e = authorize(db, actor, Action.VIEW_EU_AI_ACT, engagement_id=engagement_id)
    if e.type != svc.ENGAGEMENT_TYPE:
        raise NotFound()
    return e


def _listing(db: Session, actor: Actor, org: Organization, systems: list[RegisterSystem], engagement: Engagement | None) -> dict:
    rows = [svc.summary(db, s, svc.record_of(db, s)) for s in systems]
    return {
        "engagement": {"id": engagement.id, "name": engagement.name, "audit_ref": engagement.audit_ref} if engagement else None,
        "client": {"id": org.id, "name": org.name}, "banner": rules.data().get("banner"), "systems": rows,
        "deadline_sources": {k: v.get("source") for k, v in rules.data()["deadlines"].items()},
        "can_edit": _may(db, actor, Action.EDIT_EU_AI_ACT, org.id), "can_sign": _may(db, actor, Action.SIGN_EU_CLASSIFICATION, org.id),
        "ready_for_report": bool(rows) and all(r["signoff_status"] == "signed_off" for r in rows if r["classification"]) and any(r["classification"] for r in rows),
        "options": {"roles": rules.roles(), "classifications": rules.classifications(), "areas": {k: v["label"] for k, v in rules.areas().items()}},
    }


@router.get("/e/{engagement_id}/eu-ai-act")
def workspace(engagement_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    e = _engagement(db, actor, engagement_id)
    org = db.get(Organization, e.client_id)
    return _listing(db, actor, org, svc.systems_for(db, org.id, everything=True), e)


@router.get("/clients/{client_id}/eu-ai-act")
def client_workspace(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if not actor.is_futran:
        raise NotFound()
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.VIEW_EU_AI_ACT, org_id=org.id)
    return _listing(db, actor, org, svc.systems_for(db, org.id, everything=False), None)


def _out(db: Session, actor: Actor, s: RegisterSystem) -> dict:
    rec = svc.record_of(db, s)
    if not actor.is_futran:
        return svc.client_view(db, s, rec)
    return svc.detail(db, s, rec) | {
        "can_edit": _may(db, actor, Action.EDIT_EU_AI_ACT, s.organization_id), "can_sign": _may(db, actor, Action.SIGN_EU_CLASSIFICATION, s.organization_id),
        "options": {"roles": rules.roles(), "classifications": rules.classifications(), "areas": {k: v["label"] for k, v in rules.areas().items()}},
    }


@router.get("/eu-ai-act/systems/{system_id}")
def get_system(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return _out(db, actor, _system(db, actor, system_id, Action.VIEW_EU_AI_ACT))


@router.put("/eu-ai-act/systems/{system_id}")
def put_system(system_id: str, body: RecordIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.EDIT_EU_AI_ACT)
    data = body.model_dump(exclude_unset=True)
    if data.get("engagement_id"):
        authorize(db, actor, Action.EDIT_EU_AI_ACT, engagement_id=data["engagement_id"])
    svc.update(db, actor.user, s, data)
    db.commit()
    return _out(db, actor, s)


@router.post("/eu-ai-act/systems/{system_id}/send")
def send(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.EDIT_EU_AI_ACT)
    svc.send_for_signoff(db, actor.user, s)
    db.commit()
    return _out(db, actor, s)


@router.post("/eu-ai-act/systems/{system_id}/signoff")
def signoff(system_id: str, body: DecisionIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.SIGN_EU_CLASSIFICATION)
    svc.decide(db, actor.user, s, body.approve, body.note)
    db.commit()
    return _out(db, actor, s)


@router.put("/eu-ai-act/systems/{system_id}/obligations/{key}")
def put_obligation(system_id: str, key: str, body: StatusIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.EDIT_EU_AI_ACT)
    svc.set_obligation(db, actor.user, s, key, body.status, body.note)
    db.commit()
    return _out(db, actor, s)


@router.post("/eu-ai-act/systems/{system_id}/obligations/{key}/evidence")
def post_evidence(system_id: str, key: str, request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor),
                  db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.EDIT_EU_AI_ACT)
    settings = request.app.state.settings
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(errors=[{"field": "file", "message": f"Files can be up to {settings.max_upload_mb} MB."}])
    svc.add_evidence(db, settings, actor.user, s, key, data, file.filename or "evidence")
    db.commit()
    return _out(db, actor, s)


@router.put("/eu-ai-act/systems/{system_id}/annex-iv/{section}")
def put_annex_iv(system_id: str, section: str, body: StatusIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.EDIT_EU_AI_ACT)
    svc.set_annex_iv(db, actor.user, s, section, body.status, body.note)
    db.commit()
    return _out(db, actor, s)


@router.put("/eu-ai-act/systems/{system_id}/fria")
def put_fria(system_id: str, body: FriaIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.EDIT_EU_AI_ACT)
    svc.set_fria(db, actor.user, s, body.answers, body.status)
    db.commit()
    return _out(db, actor, s)


# Evidence files: the Futran people who may see the EU AI Act workspace for that client; never the client side.
def _evidence_access(db: Session, actor: Actor, f: FileObject) -> None:
    if not actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.VIEW_EU_AI_ACT, org_id=f.organization_id)


def _register_file_rule() -> None:
    from app.files.router import FILE_ACCESS

    FILE_ACCESS.setdefault("euaiact_evidence", _evidence_access)


_register_file_rule()
