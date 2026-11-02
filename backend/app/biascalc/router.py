"""Screen 29: the bias test calculator on an audited AI system, and the client's raw-data choice."""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.biascalc import register  # noqa: F401  retention job and monitoring checks
from app.biascalc import service as svc
from app.biascalc.models import BiasTestRun
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.engagements.models import Engagement
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.systems.service import get_system

router = APIRouter(tags=["bias calculator"])


class JustificationIn(BaseModel):
    justification: str | None = None


class KeepIn(BaseModel):
    keep: bool


def _may(db: Session, actor: Actor, action: Action, engagement_id: str) -> bool:
    try:
        authorize(db, actor, action, engagement_id=engagement_id)
        return True
    except (Forbidden, NotFound):
        return False


def _futran_run(db: Session, actor: Actor, run_id: str, action: Action = Action.RUN_BIAS_TEST) -> BiasTestRun:
    run = svc.get_run(db, run_id)
    authorize(db, actor, action, engagement_id=run.engagement_id)
    return run


@router.get("/systems/{system_id}/bias-tests")
def list_runs(system_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.reports.service import requires_public_summary

    s = get_system(db, system_id)
    e = authorize(db, actor, Action.VIEW_BIAS_TESTS, engagement_id=s.engagement_id)
    settings = request.app.state.settings
    from app.tenancy.models import Organization

    org = db.get(Organization, e.client_id)
    return {"system": {"id": s.id, "reference_id": s.reference_id, "name": s.name, "client_id": e.client_id, "client_name": org.name if org else None,
                       "register_system_id": s.register_system_id, "engagement_id": e.id, "audit_ref": e.audit_ref},
            "settings": svc.bias_settings(db, s), "public_summary_required": requires_public_summary(db, e), "can_run": _may(db, actor, Action.RUN_BIAS_TEST, e.id),
            "engagement_files": _engagement_files(db, e) if _may(db, actor, Action.RUN_BIAS_TEST, e.id) else [],
            "runs": [svc.run_out(db, settings, r) for r in svc.runs_for(db, s)]}


def _engagement_files(db: Session, e: Engagement) -> list[dict]:
    """CSV files on this engagement the client or auditors uploaded (for example in answer to an evidence request)."""
    from app.files.models import FileObject

    rows = db.scalars(select(FileObject).where(FileObject.engagement_id == e.id, FileObject.deleted_at.is_(None), FileObject.filename.ilike("%.csv"),
                                               (FileObject.linked_type.is_(None)) | (FileObject.linked_type != "bias_dataset")).order_by(FileObject.created_at.desc()).limit(50))
    return [{"id": f.id, "filename": f.filename, "uploaded_at": f.created_at.isoformat()} for f in rows]


@router.post("/systems/{system_id}/bias-tests")
async def post_run(system_id: str, request: Request, file: UploadFile | None = File(None), method: str | None = Form(None), data_source: str | None = Form(None),
                   file_id: str | None = Form(None), exclude_small: str | None = Form(None), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = get_system(db, system_id)
    authorize(db, actor, Action.RUN_BIAS_TEST, engagement_id=s.engagement_id)
    data = await file.read() if file is not None else None
    settings = request.app.state.settings
    run = svc.run_test(db, settings, actor.user, s, data=data, filename=file.filename if file is not None else None, file_id=file_id, method=method,
                       data_source=data_source, exclude_small=exclude_small)
    return svc.run_out(db, settings, run)


@router.get("/bias-tests/{run_id}")
def get_run(run_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    run = _futran_run(db, actor, run_id, Action.VIEW_BIAS_TESTS)
    return svc.run_out(db, request.app.state.settings, run)


@router.post("/bias-tests/{run_id}/apply-answers")
def post_apply(run_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.apply_answers(db, actor.user, _futran_run(db, actor, run_id))


@router.post("/bias-tests/{run_id}/draft-findings")
def post_findings(run_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return {"created": svc.draft_findings(db, actor.user, _futran_run(db, actor, run_id))}


@router.post("/bias-tests/{run_id}/public-summary")
def post_summary(run_id: str, body: JustificationIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return svc.use_in_public_summary(db, actor.user, _futran_run(db, actor, run_id), body.justification)


@router.post("/bias-tests/{run_id}/record")
def post_record(run_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return {"bias_test_id": svc.record_as_bias_test(db, actor.user, _futran_run(db, actor, run_id))}


# ---- client: raw data kept or deleted at the end of the retention period
@router.get("/bias-data")
def client_list(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.KEEP_BIAS_DATA, org_id=actor.organization.id)
    runs = db.scalars(select(BiasTestRun).where(BiasTestRun.organization_id == actor.organization.id, BiasTestRun.deleted_at.is_(None)).order_by(BiasTestRun.run_at.desc()))
    return {"runs": [svc.client_run_out(db, request.app.state.settings, r) for r in runs]}


@router.put("/bias-tests/{run_id}/keep-raw-data")
def put_keep(run_id: str, body: KeepIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    run = svc.get_run(db, run_id)
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_BIAS_TESTS, engagement_id=run.engagement_id)  # 404 when not visible, then:
        raise Forbidden("The client decides whether to keep its raw data.")
    if run.organization_id != actor.organization.id:
        raise NotFound()
    authorize(db, actor, Action.KEEP_BIAS_DATA, org_id=run.organization_id)
    return svc.client_run_out(db, request.app.state.settings, svc.set_keep(db, actor.user, run, body.keep))


# ---- GenAI guardrail tests (Phase 4): fake adapter unless GUARDRAIL_TESTS_LIVE and the client's written permission
class DecisionIn(BaseModel):
    decision: str | None = None
    note: str | None = None


@router.get("/systems/{system_id}/guardrail-tests")
def list_guardrail(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.biascalc import guardrails

    s = get_system(db, system_id)
    authorize(db, actor, Action.VIEW_BIAS_TESTS, engagement_id=s.engagement_id)
    return {"runs": [guardrails.run_out(db, r) for r in guardrails.runs_for(db, s)], "prompt_set_version": str(guardrails.prompt_set()["version"])}


@router.post("/systems/{system_id}/guardrail-tests")
def post_guardrail(system_id: str, body: dict, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.biascalc import guardrails

    s = get_system(db, system_id)
    authorize(db, actor, Action.RUN_BIAS_TEST, engagement_id=s.engagement_id)
    return guardrails.run_out(db, guardrails.run(db, request.app.state.settings, actor.user, s, body))


@router.post("/guardrail-tests/{run_id}/decision")
def post_guardrail_decision(run_id: str, body: DecisionIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.biascalc import guardrails

    r = guardrails.get(db, run_id)
    authorize(db, actor, Action.RUN_BIAS_TEST, engagement_id=r.engagement_id)
    return guardrails.decide(db, actor.user, r, body.decision, body.note)
