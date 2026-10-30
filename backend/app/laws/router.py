import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.laws.importer import FEATURE_LABELS, FEATURES, ImportPreview, parse_workbook
from app.laws.models import LawImportPreview, MatrixVersion, Regulation
from app.laws.publish import plan_out, plan_publish, publish
from app.laws.service import add_law, edit_law, law_out, search_laws
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.models import Jurisdiction

router = APIRouter(tags=["laws"])


class PublishIn(BaseModel):
    edits: dict[str, str] = {}
    take_workbook: list[str] = []


class LawIn(BaseModel):
    jurisdiction_code: str | None = None
    short_name: str | None = None
    feature: str | None = None
    type: str | None = None
    enforcer: str | None = None
    trigger_text: str | None = None
    obligations_text: str | None = None
    developments_text: str | None = None
    most_affected: str | None = None
    full_text: str | None = None
    applies_to: str | None = None
    verify_flag: bool | None = None
    public_summary: bool | None = None
    effective_date_text: str | None = None
    status_text: str | None = None


def _preview_out(db: Session, pid: str, pv: ImportPreview) -> dict:
    regs = [r for r in pv.rows if r.kind == "regulation"]
    return {
        "preview_id": pid,
        **pv.to_json(),
        "plan": plan_out(plan_publish(db, pv, {})),
        "counts": {
            "regulations": len(regs),
            "notes": len(pv.rows) - len(regs),
            "jurisdictions": len({r.jurisdiction_code for r in regs}),
            "verify": sum(1 for r in regs if r.verify_flag),
            "developer_only": sum(1 for r in regs if r.applies_to == "developer"),
        },
    }


MAX_ROWS = 5000


@router.post("/admin/laws/import")
def import_preview(request: Request, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    limit = request.app.state.settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(f"The workbook is larger than {request.app.state.settings.max_upload_mb} MB.", [{"field": "file", "message": "File too large."}])
    if not data.startswith(b"PK"):
        raise Invalid("Upload the law matrix as an Excel workbook (.xlsx).", [{"field": "file", "message": "Not an .xlsx file."}])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / (Path(file.filename or "matrix.xlsx").name or "matrix.xlsx")
        path.write_bytes(data)
        try:
            pv = parse_workbook(path)
        except KeyError as exc:
            raise Invalid(f"This workbook is missing a sheet the importer needs: {exc}.")
        except Exception as exc:  # malformed workbook
            raise Invalid(f"The workbook could not be read: {exc}")
    if len(pv.rows) > MAX_ROWS:
        raise Invalid(f"The workbook has more than {MAX_ROWS} law rows. Check that the right file was chosen.")
    rec = LawImportPreview(payload=pv.to_json(), created_by=actor.id)
    db.add(rec)
    db.flush()
    return _preview_out(db, rec.id, pv)


@router.get("/admin/laws/import/{preview_id}")
def get_preview(preview_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    rec = db.get(LawImportPreview, preview_id)
    if rec is None:
        raise NotFound()
    return _preview_out(db, rec.id, ImportPreview.from_json(rec.payload))


@router.post("/admin/laws/import/{preview_id}/publish")
def publish_preview(preview_id: str, body: PublishIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    rec = db.get(LawImportPreview, preview_id)
    if rec is None:
        raise NotFound()
    if rec.published_version_id:
        raise Conflict("This preview has already been published. Upload the workbook again to make another version.")
    newer = db.scalar(select(MatrixVersion.id).where(MatrixVersion.origin == "import", MatrixVersion.published_at > rec.created_at).limit(1))
    if newer:
        raise Conflict("A newer import was published after this preview was made. Upload the workbook again.")
    v = publish(db, ImportPreview.from_json(rec.payload), actor.user, body.edits, take_workbook=body.take_workbook)
    rec.published_version_id = v.id
    return {"version_id": v.id, "label": v.label, "summary": v.summary}


@router.get("/admin/laws/versions")
def versions(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    rows = db.scalars(select(MatrixVersion).order_by(MatrixVersion.published_at.desc()).limit(200))
    return [{"id": v.id, "label": v.label, "origin": v.origin, "status": v.status, "status_date": v.status_date.isoformat() if v.status_date else None, "published_at": v.published_at.isoformat(), "warnings": v.warnings or []} for v in rows]


@router.get("/laws")
def list_laws(
    codes: str = "all",
    feature: str | None = None,
    q: str | None = None,
    exclude_developer: bool = False,
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    """Reference data, readable by any signed-in user. `codes` is a comma list of jurisdiction codes or 'all'."""
    code_list = None if codes == "all" else [c.strip().upper() for c in codes.split(",") if c.strip()]
    if feature and feature not in FEATURES:
        raise Invalid(errors=[{"field": "feature", "message": "Unknown feature."}])
    return search_laws(db, code_list, feature, q, exclude_developer)


@router.get("/laws/features")
def features(actor: Actor = Depends(current_actor)):
    return [{"value": f, "label": FEATURE_LABELS[f]} for f in FEATURES]


@router.get("/laws/{law_id}")
def get_law(law_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    r = db.get(Regulation, law_id)
    if r is None:
        raise NotFound()
    return law_out(r, db.get(Jurisdiction, r.jurisdiction_id))


@router.patch("/laws/{law_id}")
def patch_law(law_id: str, body: LawIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    new = edit_law(db, actor.user, law_id, body.model_dump(exclude_unset=True, exclude={"jurisdiction_code"}))
    return law_out(new, db.get(Jurisdiction, new.jurisdiction_id))


@router.post("/laws")
def post_law(body: LawIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_REFERENCE_DATA)
    if not body.jurisdiction_code:
        raise Invalid(errors=[{"field": "jurisdiction_code", "message": "Choose a jurisdiction."}])
    reg = add_law(db, actor.user, body.jurisdiction_code.upper(), body.model_dump(exclude_unset=True, exclude={"jurisdiction_code"}))
    return law_out(reg, db.get(Jurisdiction, reg.jurisdiction_id))


class DecideIn(BaseModel):
    accept: list[str] = []
    reject: list[str] = []


def _run_out(db: Session, run, with_proposals: bool = False) -> dict:
    from app.laws.models import RegulationProposal

    names = dict(db.execute(select(Jurisdiction.id, Jurisdiction.name).where(Jurisdiction.id.in_(run.jurisdiction_ids))).all())
    out = {
        "id": run.id, "status": run.status, "error": run.error, "warnings": run.warnings or [], "model": run.model,
        "jurisdictions": [names.get(j, j) for j in run.jurisdiction_ids],
        "created_at": run.created_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
    props = list(db.scalars(select(RegulationProposal).where(RegulationProposal.run_id == run.id)))
    out["counts"] = {"pending": sum(p.status == "pending" for p in props), "accepted": sum(p.status == "accepted" for p in props), "rejected": sum(p.status == "rejected" for p in props)}
    if with_proposals:
        items = []
        for p in props:
            cur = db.get(Regulation, p.regulation_id) if p.regulation_id else None
            items.append({
                "id": p.id, "change_type": p.change_type, "status": p.status, "jurisdiction": names.get(p.jurisdiction_id), "proposed": p.proposed,
                "rationale": p.rationale, "sources": p.sources, "current": law_out(cur, db.get(Jurisdiction, cur.jurisdiction_id)) if cur else None,
            })
        out["proposals"] = items
    return out


@router.post("/admin/laws/proposals/decide")
def decide(body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Earlier RegulationProposal rows only; new proposals are reviewed at /reg/changes."""
    from app.laws.refresh import accept_proposals

    authorize(db, actor, Action.RUN_LAW_REFRESH)
    v = accept_proposals(db, actor.user, body.accept, body.reject)
    return {"version_id": v.id if v else None}
