"""Screens 18–19: the final report workspace (Futran) and the report page (client)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.files.router import FILE_ACCESS
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.policy.sod import assert_not_admin_judgment
from app.reports import public_summary as ps
from app.reports import register  # noqa: F401  sign-offs 7 and 8
from app.reports import service as svc
from app.reports.models import FUTRAN_DECLARATIONS, Report, RoadmapItem
from app.tenancy.models import Organization
from app.tenancy.people import current_engagement

router = APIRouter(tags=["reports"])


def _report_file_access(db: Session, actor: Actor, f: FileObject) -> None:
    """Futran sees every version. The client sees only the versions released to it (v1.0 and the final v1.1)."""
    r = db.get(Report, f.linked_id) if f.linked_id else None
    if r is None or r.deleted_at is not None or f.id not in (r.docx_file_id, r.pdf_file_id):
        raise NotFound()
    if not actor.is_futran and r.released_to_client_at is None:
        raise NotFound()
    authorize(db, actor, Action.VIEW_FINAL_REPORT, engagement_id=r.engagement_id)


FILE_ACCESS["report"] = _report_file_access


def _engagement(db: Session, actor: Actor, client_id: str, action: Action) -> Engagement:
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    e = current_engagement(db, org)
    if e is None:
        raise NotFound()
    authorize(db, actor, action, engagement_id=e.id)
    return e


def _can(db: Session, actor: Actor, action: Action, e: Engagement) -> bool:
    try:
        authorize(db, actor, action, engagement_id=e.id)
        return True
    except Forbidden:
        return False


def _client_view(db: Session, actor: Actor, e: Engagement) -> dict:
    from app.findings.service import findings_for
    from app.signoffs.service import current, sign_off_out

    released = [r for r in svc.reports_for(db, e) if r.released_to_client_at is not None]
    final = svc.latest(db, e, "v1.1")
    rows = {d.kind: d for d in svc.declarations_for(db, final)} if final is not None and final.status == "final" else {}
    ack, com = rows.get("client_acknowledgement"), rows.get("client_remediation_commitment")
    so8 = current(db, e, 8)
    return {
        "audit_ref": e.audit_ref, "client": db.get(Organization, e.client_id).name, "stage": e.stage,
        "reports": [svc.report_out(db, r, futran=False) for r in released],
        "acknowledgement": {
            "notice": svc.ACK_NOTICE, "text": svc.declaration_text(db, e, "client_acknowledgement")[0], "commitments": svc.COMMITMENT_TEXT,
            "can_sign": not svc.acknowledgement_unmet(db, e) and _can(db, actor, Action.SIGN_DECLARATION, e),
            "signed_by": ack.typed_name if ack else None, "signed_at": ack.signed_at.isoformat() if ack else None,
            "commitment": com.commitment if com else None, "commitment_text": com.text if com else None, "disputed_refs": com.disputed_finding_refs if com else [],
            "my_name": actor.user.name,
        },
        "findings": [{"ref": f.ref, "title": f.title, "severity": f.severity} for f in findings_for(db, e) if f.status == "approved"] if released else [],
        "public_summary": ({"required": True, "text": so8.statement, "sign_off": sign_off_out(db, actor, so8)} if so8 is not None else {"required": svc.requires_public_summary(db, e), "text": None, "sign_off": None}),
    }


def _futran_view(db: Session, actor: Actor, e: Engagement) -> dict:
    from app.findings.service import findings_for
    from app.signoffs.service import current, sign_off_out

    n = svc.narrative(db, e)
    v02 = svc.latest(db, e, "v0.2")
    signed = {d.kind: d for d in svc.declarations_for(db, v02)} if v02 else {}
    released = svc.latest(db, e, "v1.0", released=True) is not None
    declarations = []
    for kind in svc.required_declarations(db, e):
        holders = svc.team_holders(db, e, svc.DECLARATION_ROLE[kind])
        d = signed.get(kind)
        declarations.append({"kind": kind, "label": FUTRAN_DECLARATIONS[kind], "holders": [u.name for u in holders], "signed_by": d.typed_name if d else None,
                             "signed_at": d.signed_at.isoformat() if d else None,
                             "can_sign": d is None and v02 is not None and not released and actor.id in {u.id for u in holders} and all(x.user_id != actor.id for x in signed.values())})
    so7, so8 = current(db, e, 7), current(db, e, 8)
    can_edit = _can(db, actor, Action.RECORD_FINDINGS, e) and not released
    release_unmet = svc.release_unmet(db, e) if not released else []
    summary = ps.summary_out(db, e)
    final_unmet = [m for m in svc.final_unmet(db, e) if "Prepare the final" not in m]
    return {
        "audit_ref": e.audit_ref, "client": db.get(Organization, e.client_id).name, "stage": e.stage, "me": actor.id, "my_name": actor.user.name,
        "reports": [svc.report_out(db, r, futran=True) for r in svc.reports_for(db, e)],
        "narrative": {"most_significant_finding_id": n.most_significant_finding_id if n else None, "most_significant_text": n.most_significant_text if n else None,
                      "strengths": n.strengths if n else None, "immediate_actions": n.immediate_actions if n else None, "narrative": n.narrative if n else None},
        "roadmap": [svc.roadmap_out(db, r) for r in svc.roadmap(db, e)],
        "findings": [{"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "status": f.status} for f in findings_for(db, e)],
        "can_edit": can_edit, "can_generate": can_edit and e.stage >= 5,
        "lead_review": {"report_id": v02.id if v02 else None, "declarations": declarations, "lead_auditor_text": svc.declaration_text(db, e, "lead_auditor")[0], "no_qa": "quality_reviewer" not in svc.required_declarations(db, e)},
        "release": {"released": released, "unmet": release_unmet, "can_release": not release_unmet and _can(db, actor, Action.ADVANCE_STAGE, e)},
        "final": {"sign_off": sign_off_out(db, actor, so7) if so7 else None, "unmet": final_unmet,
                  "can_prepare": not final_unmet and _can(db, actor, Action.RECORD_FINDINGS, e) and (so7 is None or so7.status == "returned")},
        "public_summary": summary | {"sign_off": sign_off_out(db, actor, so8) if so8 else None, "unmet": ps.summary_unmet(db, e) if summary["required"] else [],
                                     "can_edit": summary["required"] and _can(db, actor, Action.RECORD_FINDINGS, e) and (so8 is None or so8.status == "returned")},
    }


@router.get("/clients/{client_id}/report")
def get_report(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.VIEW_FINAL_REPORT)
    return _futran_view(db, actor, e) if actor.is_futran else _client_view(db, actor, e)


class GenerateIn(BaseModel):
    version: str


@router.put("/clients/{client_id}/report/summary")
def put_summary(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    svc.save_narrative(db, actor.user, e, data)
    return {"saved": True}


@router.post("/clients/{client_id}/report/roadmap")
def add_roadmap(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    return svc.roadmap_out(db, svc.add_roadmap_item(db, actor.user, e, data))


def _item(db: Session, actor: Actor, item_id: str) -> RoadmapItem:
    item = db.get(RoadmapItem, item_id)
    if item is None or item.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.RECORD_FINDINGS, engagement_id=item.engagement_id)
    return item


@router.patch("/roadmap-items/{item_id}")
def patch_roadmap(item_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    return svc.roadmap_out(db, svc.update_roadmap_item(db, actor.user, _item(db, actor, item_id), data))


@router.delete("/roadmap-items/{item_id}")
def delete_roadmap(item_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    svc.delete_roadmap_item(db, actor.user, _item(db, actor, item_id))
    return {"deleted": True}


@router.post("/clients/{client_id}/report/generate")
def generate(client_id: str, body: GenerateIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    return svc.report_out(db, svc.generate(db, request.app.state.settings, actor.user, e, body.version), futran=True)


class DeclareIn(BaseModel):
    kind: str
    typed_name: str


@router.post("/reports/{report_id}/declarations")
def declare(report_id: str, body: DeclareIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, Action.SIGN_DECLARATION, engagement_id=r.engagement_id)
    if not actor.is_futran:
        raise Forbidden("Futran declarations are signed by the Futran team.")
    svc.declare(db, actor.user, r, body.kind, body.typed_name, request)
    return svc.report_out(db, r, futran=True)


@router.post("/clients/{client_id}/report/release")
def release(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    e = _engagement(db, actor, client_id, Action.ADVANCE_STAGE)
    return svc.report_out(db, svc.release_client_draft(db, request.app.state.settings, actor.user, e), futran=True)


@router.post("/clients/{client_id}/report/final")
def prepare_final(client_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    from app.signoffs.service import sign_off_out

    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    r, so = svc.prepare_final(db, request.app.state.settings, actor, e)
    return {"report": svc.report_out(db, r, futran=True), "sign_off": sign_off_out(db, actor, so)}


class AckIn(BaseModel):
    typed_name: str
    commitment: str | None = None
    disputed_refs: list[str] | None = None


@router.post("/clients/{client_id}/report/acknowledge")
def acknowledge(client_id: str, body: AckIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if actor.is_futran:
        raise Forbidden("The client's authorized representative acknowledges the report.")
    e = _engagement(db, actor, client_id, Action.SIGN_DECLARATION)
    svc.acknowledge(db, request.app.state.settings, actor, e, body.typed_name, body.commitment, body.disputed_refs, request)
    return _client_view(db, actor, e)


@router.get("/clients/{client_id}/public-summary")
def get_summary(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    from app.signoffs.service import current

    e = _engagement(db, actor, client_id, Action.VIEW_FINAL_REPORT)
    if not actor.is_futran and current(db, e, 8) is None:  # the client sees it when it is sent for sign-off 8
        return {"required": svc.requires_public_summary(db, e), "summary": None, "text": None}
    return ps.summary_out(db, e)


@router.put("/clients/{client_id}/public-summary")
def put_summary_public(client_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    assert_not_admin_judgment(actor)
    e = _engagement(db, actor, client_id, Action.RECORD_FINDINGS)
    ps.save_summary(db, actor.user, e, data)
    return ps.summary_out(db, e)
