"""AI literacy training API (spec §21 F12, screen 33): the owner's screen (/training), the learner (/my-training,
/learn/{id}) and the no-sign-in player behind a personal email link (/public/training/{token})."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import NotFound
from app.core.ratelimit import client_ip, limiter
from app.files.models import FileObject
from app.mail import links
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization
from app.training import access, mail_links
from app.training import modules as M
from app.training import service as svc
from app.training.models import TrainingAssignment

router = APIRouter(tags=["training"])


class CheckIn(BaseModel):
    question_id: str = ""
    option_id: str = ""


def _pdf(data: bytes, name: str) -> Response:
    safe = name.encode("ascii", "replace").decode().replace('"', "")
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "private, no-store"})


# ---- owner
@router.get("/training")
def overview(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.VIEW_TRAINING)
    org = actor.organization
    from app.mail.groups import ensure_default_groups
    from app.mail.models import MailGroup
    from sqlalchemy import select
    from app.tenancy.models import Department

    ensure_default_groups(db, org.id)
    groups = [{"id": g.id, "name": g.name} for g in db.scalars(select(MailGroup).where(MailGroup.organization_id == org.id, MailGroup.deleted_at.is_(None)).order_by(MailGroup.name))]
    depts = [{"id": d.id, "name": d.name} for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)).order_by(Department.name))]
    return svc.overview(db, org) | {"can": {"manage": access.may(db, actor, Action.MANAGE_TRAINING)}, "is_literacy_owner": access.is_literacy_owner(db, actor),
                                    "options": {"groups": groups, "departments": depts,
                                                "roles": [{"value": r, "label": label} for r, label in (("caico", "Chief AI Compliance Officer"), ("client_admin", "Client Admin"),
                                                                                                         ("exec_sponsor", "Executive Sponsor"), ("dpo", "Data Protection Officer"),
                                                                                                         ("dept_compliance_lead", "Department Compliance Lead"), ("contributor", "Contributor"))]}}


@router.put("/training/program")
def put_program(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.MANAGE_TRAINING)
    p = svc.set_program(db, actor.user, actor.organization.id, body)
    return {"target_pct": p.target_pct, "target_date": p.target_date.isoformat() if p.target_date else None}


@router.get("/training/modules/{code}")
def module_preview(code: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.VIEW_TRAINING)
    m = M.library().get(code)
    if m is None:
        raise NotFound()
    return M.learner_view(m, actor.organization.name)


@router.get("/training/modules/{code}/scorm")
def scorm(code: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.MANAGE_TRAINING)
    m = M.library().get(code)
    if m is None:
        raise NotFound()
    from app.audit_log import service as audit

    audit.record(db, actor_id=actor.id, action="training.scorm_export", organization_id=actor.organization.id, object_type="TrainingModule", object_id=code,
                 summary=f"Exported the {code.replace('_', ' ')} module as a SCORM 1.2 package")
    return Response(content=M.scorm_zip(m, actor.organization.name), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="futran-{code}-v{m["version"]}-scorm12.zip"'})


@router.post("/training/assign/preview")
def assign_preview(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.MANAGE_TRAINING)
    return svc.preview(db, actor.user, actor.organization.id, body)


@router.post("/training/assign")
def assign(body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.MANAGE_TRAINING)
    return svc.assign(db, request.app.state.settings, actor.user, actor.organization, body)


@router.get("/training/assignments")
def assignments(module: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.VIEW_TRAINING)
    return {"rows": svc.assignment_rows(db, actor.organization, module)}


@router.post("/training/reminders")
def reminders(body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.MANAGE_TRAINING)
    return {"reminded": svc.send_reminders(db, request.app.state.settings, actor.user, actor.organization.id, body.get("module_code"))}


@router.post("/training/evidence")
def evidence(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.MANAGE_TRAINING)
    return svc.save_evidence(db, request.app.state.settings, actor.user, actor.organization)


@router.get("/training/assignments/{assignment_id}/certificate")
def owner_certificate(assignment_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    access.check(db, actor, Action.VIEW_TRAINING)
    a = db.get(TrainingAssignment, assignment_id)
    if a is None or a.deleted_at is not None or a.organization_id != actor.organization.id:
        raise NotFound()
    return _pdf(svc.certificate_pdf(db, a), f"Certificate {a.certificate_no}.pdf")


# ---- signed-in learner
def _mine(db: Session, actor: Actor, assignment_id: str) -> TrainingAssignment:
    org = access.client_org(actor)
    authorize(db, actor, Action.COMPLETE_OWN_TRAINING, org_id=org.id)
    a = db.get(TrainingAssignment, assignment_id)
    if a is None or a.deleted_at is not None or a.organization_id != org.id or not (a.user_id == actor.id or a.email == actor.user.email.lower()):
        raise NotFound()
    return a


@router.get("/my-training")
def my_training(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = access.client_org(actor)
    authorize(db, actor, Action.COMPLETE_OWN_TRAINING, org_id=org.id)
    return {"assignments": [svc.assignment_out(db, a, org.name) for a in svc.for_user(db, actor.user)],
            "can_manage": access.may(db, actor, Action.VIEW_TRAINING)}


@router.get("/learn/{assignment_id}")
def learn(assignment_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.player(db, _mine(db, actor, assignment_id), actor.organization.name)


@router.post("/learn/{assignment_id}/check")
def learn_check(assignment_id: str, body: CheckIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.check(db, _mine(db, actor, assignment_id), body.question_id, body.option_id, actor.organization.name)


@router.post("/learn/{assignment_id}/finish")
def learn_finish(assignment_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.finish(db, _mine(db, actor, assignment_id), actor.id)


@router.get("/learn/{assignment_id}/certificate")
def learn_certificate(assignment_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    a = _mine(db, actor, assignment_id)
    return _pdf(svc.certificate_pdf(db, a), f"Certificate {a.certificate_no}.pdf")


# ---- personal email link (no sign-in): the token resolves to one person's assignment
def _by_token(db: Session, token: str, opened: bool = False) -> TrainingAssignment:
    r, s = links.open_personal(db, token) if opened else links.personal(db, token)
    return mail_links.assignment_for(db, r, s)


def _company(db: Session, a: TrainingAssignment) -> str:
    org = db.get(Organization, a.organization_id)
    return org.name if org else ""


@router.get("/public/training/{token}")
def public_learn(token: str, db: Session = Depends(get_db, scope="function")):
    a = _by_token(db, token, opened=True)
    return svc.player(db, a, _company(db, a))


@router.post("/public/training/{token}/check")
def public_check(token: str, body: CheckIn, request: Request, db: Session = Depends(get_db, scope="function")):
    limiter(request, "training_link", 120).check(f"{token}:{client_ip(request)}")
    a = _by_token(db, token)
    return svc.check(db, a, body.question_id, body.option_id, _company(db, a))


@router.post("/public/training/{token}/finish")
def public_finish(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    limiter(request, "training_link", 120).check(f"{token}:{client_ip(request)}")
    r, s = links.personal(db, token)
    a = mail_links.assignment_for(db, r, s)
    out = svc.finish(db, a)
    if out["passed"]:
        links.mark_completed(db, r)
    return out


@router.get("/public/training/{token}/certificate")
def public_certificate(token: str, db: Session = Depends(get_db, scope="function")):
    a = _by_token(db, token)
    return _pdf(svc.certificate_pdf(db, a), f"Certificate {a.certificate_no}.pdf")


# ---- file downloads of saved training records (/files/{id})
def file_access(db: Session, actor: Actor, f: FileObject) -> None:
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_REGISTER, org_id=f.organization_id)  # evidence on a company role, beside the register
        return
    if actor.organization.id != f.organization_id:
        raise NotFound()
    if access.may(db, actor, Action.VIEW_TRAINING):
        return
    authorize(db, actor, Action.VIEW_REGISTER, org_id=f.organization_id, list_view=True)


def _register_file_access() -> None:
    from app.files.router import FILE_ACCESS

    FILE_ACCESS["training_record"] = file_access


_register_file_access()
