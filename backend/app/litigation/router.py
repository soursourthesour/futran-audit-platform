"""L1 litigation tracker and L2 case record (spec §27.4). Chief Auditor edits; Auditors and Sales Team read."""
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import today
from app.core.db import get_db
from app.core.errors import NotFound
from app.core.models import column_snapshot
from app.litigation.models import STAGE_LABELS, STAGES, Case, CaseClientMatch, CaseFollow
from app.litigation.service import add_timeline, case_out, match_case, touch
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.models import Jurisdiction
from app.tenancy.models import Organization

router = APIRouter(tags=["litigation"])


class SourceIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl


class MatchRuleIn(BaseModel):
    types: list[str] = []
    sourcing: list[str] = []
    vendors: list[str] = []
    uses: list[str] = []


class CaseIn(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=300)
    geography: str | None = Field(default=None, max_length=120)
    jurisdiction_code: str | None = None
    area: str | None = Field(default=None, min_length=2, max_length=160)
    court: str | None = Field(default=None, max_length=200)
    docket_ref: str | None = Field(default=None, max_length=120)
    description: str | None = None
    why_matters: str | None = None
    stage: str | None = None
    stage_note: str | None = Field(default=None, max_length=200)
    last_update_on: date | None = None
    regulation_ids: list[str] | None = None
    talking_points_futran: str | None = None
    talking_points_client: str | None = None
    sources: list[SourceIn] | None = None
    match_rule: MatchRuleIn | None = None

    @field_validator("stage")
    @classmethod
    def _stage(cls, v):
        if v is not None and v not in STAGES:
            raise ValueError(f"Choose a stage: {', '.join(STAGES)}.")
        return v


def _apply(db: Session, case: Case, body: CaseIn) -> None:
    data = body.model_dump(exclude_unset=True)
    code = data.pop("jurisdiction_code", None)
    if code:
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == code.upper()))
        case.jurisdiction_id = j.id if j else None
    if "sources" in data:
        data["sources"] = [{"title": s.title, "url": str(s.url)} for s in body.sources or []]
    if "match_rule" in data:
        data["match_rule"] = body.match_rule.model_dump() if body.match_rule else {}
    for k, v in data.items():
        setattr(case, k, v)


def _following(db: Session, case_id: str, user_id: str) -> bool:
    return db.scalar(select(CaseFollow.id).where(CaseFollow.case_id == case_id, CaseFollow.user_id == user_id)) is not None


def _get(db: Session, case_id: str) -> Case:
    c = db.get(Case, case_id)
    if c is None or c.deleted_at is not None:
        raise NotFound()
    return c


def _visible(db: Session, *, stage=None, area=None, geography=None, client_id=None, q=None, ids=None) -> list[Case]:
    stmt = select(Case).where(Case.deleted_at.is_(None))
    if stage:
        stmt = stmt.where(Case.stage.in_(stage.split(",")))
    if area:
        stmt = stmt.where(Case.area == area)
    if geography:
        stmt = stmt.where(Case.geography == geography)
    if ids:
        stmt = stmt.where(Case.id.in_(ids))
    if client_id:
        stmt = stmt.where(Case.id.in_(select(CaseClientMatch.case_id).where(CaseClientMatch.organization_id == client_id)))
    rows = list(db.scalars(stmt.order_by(Case.last_update_on.desc().nulls_last(), Case.name)))
    if q:
        needle = q.casefold()
        rows = [c for c in rows if needle in f"{c.name} {c.area} {c.court or ''} {c.description or ''}".casefold()]
    return rows


@router.get("/litigation")
def list_cases(stage: str | None = None, area: str | None = None, geography: str | None = None, client_id: str | None = None, q: str | None = None,
               actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    rows = _visible(db, stage=stage, area=area, geography=geography, client_id=client_id, q=q)
    follows = set(db.scalars(select(CaseFollow.case_id).where(CaseFollow.user_id == actor.id)))
    every = list(db.scalars(select(Case).where(Case.deleted_at.is_(None))))
    client_ids = set(db.scalars(select(CaseClientMatch.organization_id)))
    clients = [{"id": o.id, "name": o.name} for o in db.scalars(select(Organization).where(Organization.id.in_(client_ids)).order_by(Organization.name))] if client_ids else []
    from app.refresh.service import last_run_summary

    return {
        "items": [case_out(db, c, following=c.id in follows) for c in rows],
        "filters": {
            "areas": sorted({c.area for c in every}), "geographies": sorted({c.geography for c in every if c.geography}),
            "stages": [{"value": s, "label": STAGE_LABELS[s]} for s in STAGES], "clients": clients,
        },
        "last_refresh": last_run_summary(db, "litigation"),
        "can_edit": _can(db, actor, Action.MANAGE_LITIGATION),
    }


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except Exception:
        return False


@router.get("/litigation/export.csv")
def export(ids: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    rows = _visible(db, ids=ids.split(",") if ids else None)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Geography", "Law or area", "Case", "Court", "Docket", "What it is about", "Stage", "Last update", "Clients with similar AI", "Sources"])
    for c in rows:
        o = case_out(db, c)
        w.writerow([c.geography or "", c.area, c.name, c.court or "", c.docket_ref or "", c.description or "", o["stage_label"] + (f" · {c.stage_note}" if c.stage_note else ""),
                    o["last_update_on"] or "", o["clients_count"], " ".join(s["url"] for s in c.sources or [])])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="litigation-tracker.csv"'})


@router.post("/litigation")
def create_case(body: CaseIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_LITIGATION)
    from app.core.errors import Invalid

    missing = [f for f in ("name", "area", "stage") if not getattr(body, f)]
    if missing:
        raise Invalid(errors=[{"field": f, "message": "Required."} for f in missing])
    c = Case(created_by=actor.id, updated_by=actor.id, last_update_on=today(), timeline=[])
    _apply(db, c, body)
    if not c.timeline:
        add_timeline(c, c.stage, c.stage_note)
    db.add(c)
    db.flush()
    match_case(db, c)
    audit.record(db, actor_id=actor.id, action="case.create", obj=c, after=column_snapshot(c), request=request, organization_id=actor.organization.id, summary=f"Added case {c.name}")
    return case_out(db, c, detail=True)


@router.get("/litigation/{case_id}")
def get_case(case_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    c = _get(db, case_id)
    out = case_out(db, c, following=_following(db, c.id, actor.id), detail=True)
    out["can_edit"] = _can(db, actor, Action.MANAGE_LITIGATION)
    return out


@router.patch("/litigation/{case_id}")
def update_case(case_id: str, body: CaseIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.MANAGE_LITIGATION)
    c = _get(db, case_id)
    before = column_snapshot(c)
    old_stage = c.stage
    _apply(db, c, body)
    if c.stage != old_stage or ("stage_note" in body.model_fields_set and body.stage_note):
        add_timeline(c, c.stage, c.stage_note)
        c.last_update_on = today()
    touch(c, actor.id)
    db.flush()
    match_case(db, c)
    audit.record(db, actor_id=actor.id, action="case.update", obj=c, before=before, after=column_snapshot(c), request=request, organization_id=actor.organization.id, summary=f"Edited case {c.name}")
    return case_out(db, c, following=_following(db, c.id, actor.id), detail=True)


@router.post("/litigation/{case_id}/rematch")
def rematch(case_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    c = _get(db, case_id)
    match_case(db, c)
    return case_out(db, c, following=_following(db, c.id, actor.id), detail=True)


@router.post("/litigation/{case_id}/follow")
def follow(case_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    c = _get(db, case_id)
    if not _following(db, c.id, actor.id):
        db.add(CaseFollow(case_id=c.id, user_id=actor.id))
    return {"following": True}


@router.post("/litigation/{case_id}/unfollow")
def unfollow(case_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    c = _get(db, case_id)
    for f in db.scalars(select(CaseFollow).where(CaseFollow.case_id == c.id, CaseFollow.user_id == actor.id)):
        db.delete(f)
    return {"following": False}


class BulkFollowIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    follow: bool = True


@router.post("/litigation/bulk/follow")
def bulk_follow(body: BulkFollowIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_LITIGATION)
    n = 0
    for cid in body.ids:
        c = db.get(Case, cid)
        if c is None or c.deleted_at is not None:
            continue
        mine = db.scalar(select(CaseFollow).where(CaseFollow.case_id == c.id, CaseFollow.user_id == actor.id))
        if body.follow and mine is None:
            db.add(CaseFollow(case_id=c.id, user_id=actor.id))
            n += 1
        elif not body.follow and mine is not None:
            db.delete(mine)
            n += 1
    return {"changed": n}


@router.get("/laws/{law_id}/cases")
def cases_for_law(law_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Cases that interpret a law, for the law record (M2). Earlier versions of the law count as the same law."""
    authorize(db, actor, Action.VIEW_LITIGATION)
    from app.laws.models import Regulation

    ids = {law_id}
    reg = db.get(Regulation, law_id)
    if reg is not None:
        # every version in the superseded chain is the same law
        older = list(db.scalars(select(Regulation.id).where(Regulation.superseded_by_id.in_(ids))))
        while older:
            ids |= set(older)
            older = [i for i in db.scalars(select(Regulation.id).where(Regulation.superseded_by_id.in_(older))) if i not in ids]
        nxt = reg
        while nxt is not None and nxt.superseded_by_id:
            ids.add(nxt.superseded_by_id)
            nxt = db.get(Regulation, nxt.superseded_by_id)
    rows = [c for c in db.scalars(select(Case).where(Case.deleted_at.is_(None)).order_by(Case.name)) if ids & set(c.regulation_ids or [])]
    return [case_out(db, c) for c in rows]
