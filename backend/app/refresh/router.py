"""M3 refresh and review (spec §25.3) and the litigation refresh (§27.4). The run endpoints keep their earlier
paths (/admin/laws/refresh) and now drive the shared pipeline; earlier LawRefreshRun runs stay readable."""
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound
from app.laws.models import LawRefreshRun, Regulation
from app.litigation.models import Case
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.reference.models import Jurisdiction
from app.refresh.claude import client_for
from app.refresh.models import CHECKS, RefreshProposalMeta, RefreshRun
from app.refresh.pipeline import get_run_setting, host_of, jurisdictions_for, start_run
from app.refresh.review import ACTIONS, assign_reviewer, decide, kind_of, meta_for, second_review
from app.refresh.service import GROUP_LABELS, OPEN_STATUSES, run_summary
from app.regmaster.models import ChangeImpact, ClientGeography, LawVersion, ProposedChange, Source
from app.tenancy.models import Organization, User

router = APIRouter(tags=["refresh"])

CHANGE_LABELS = {
    "new_law": "New law", "amendment": "Amendment", "effective_date": "Effective date", "new_rule": "New rule", "guidance": "Guidance",
    "role_mapping": "Role mapping", "repeal": "Repeal", "enforcement": "Enforcement", "new_case": "New case", "case_update": "Case update",
}
CHECK_LABELS = {
    "new_laws": "New AI laws enacted", "amendments": "Amendments and effective-date changes", "rules_guidance": "New regulator rules, guidance and FAQs",
    "enforcement": "Enforcement actions", "new_cases": "New cases that interpret AI laws", "case_updates": "Stage and date changes in tracked cases",
}


def _run_action(kind: str) -> Action:
    return Action.MANAGE_LITIGATION if kind == "litigation" else Action.RUN_LAW_REFRESH


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def run_out(db: Session, run: RefreshRun, detail: bool = False) -> dict:
    names = dict(db.execute(select(Jurisdiction.id, Jurisdiction.name).where(Jurisdiction.id.in_(run.jurisdiction_ids or []))).all()) if run.jurisdiction_ids else {}
    s = run_summary(db, run)
    out = {
        "id": run.id, "legacy": False, "kind": run.kind, "trigger": run.trigger, "status": run.status, "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None, "started_by_name": _name(db, run.started_by) or "Schedule",
        "jurisdictions": [names.get(j, j) for j in run.jurisdiction_ids or []], "checks": run.checks or [], "source_set": run.source_set,
        "sources_read": run.sources_read, "records_compared": run.records_compared, "model_id": run.model_id, "prompt_version": run.prompt_version,
        "cost_usd": round(run.cost_usd or 0, 4), "cost_cap_usd": run.cost_cap_usd, "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
        "searches": run.searches, "proposals_created": run.proposals_created, "proposals_merged": run.proposals_merged, "warnings": run.warnings or [],
        "error": run.error, "alert_status": run.alert_status, "counts": s["counts"], "count_labels": GROUP_LABELS, "open": s["open"], "total": s["total"],
        "clients_affected": s["clients_affected"], "systems_affected": s["systems_affected"], "low_confidence": s["low_confidence"],
    }
    if detail:
        out["responses"] = run.responses or []
    return out


def _legacy_out(db: Session, run: LawRefreshRun, detail: bool = False) -> dict:
    from app.laws.router import _run_out

    out = _run_out(db, run, with_proposals=detail)
    return out | {"legacy": True, "kind": "law", "started_at": run.created_at.isoformat(), "trigger": "manual", "started_by_name": _name(db, run.requested_by)}


class RunIn(BaseModel):
    kind: str = "law"
    scope_mode: str = "chosen"
    jurisdiction_codes: list[str] = []
    checks: list[str] | None = None
    source_set: str | None = None
    alert_recipients: str = "setting"

    @field_validator("kind")
    @classmethod
    def _k(cls, v):
        if v not in CHECKS:
            raise ValueError("Choose law or litigation.")
        return v

    @field_validator("scope_mode")
    @classmethod
    def _s(cls, v):
        if v not in ("all", "client_geographies", "chosen"):
            raise ValueError("Choose all geographies, client geographies only, or chosen geographies.")
        return v

    @field_validator("source_set")
    @classmethod
    def _src(cls, v):
        if v is not None and v not in ("official", "with_secondary"):
            raise ValueError("Choose official sources only, or official sources plus law-firm alerts.")
        return v

    @field_validator("alert_recipients")
    @classmethod
    def _a(cls, v):
        if v not in ("setting", "me"):
            raise ValueError("Alert everyone in the settings, or only me.")
        return v


def run_in_background(app, run_id: str) -> None:
    from app.refresh.pipeline import execute_run

    db = app.state.sessionmaker()
    try:
        run = db.get(RefreshRun, run_id)
        client = client_for(app.state, app.state.settings)
        if client is None:
            run.status, run.error = "failed", "No Claude client is configured."
        else:
            execute_run(db, app.state.settings, run, client, commit=db.commit)
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(RefreshRun, run_id)
        if run is not None:
            run.status, run.error = "failed", str(exc)[:2000]
            db.commit()
    finally:
        db.close()


@router.post("/admin/laws/refresh")
def start(body: RunIn, background: BackgroundTasks, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, _run_action(body.kind))
    settings = request.app.state.settings
    if client_for(request.app.state, settings) is None:
        raise Conflict("Add an Anthropic API key in settings to use law updates.")
    if body.scope_mode == "chosen" and not body.jurisdiction_codes:
        raise Invalid(errors=[{"field": "jurisdiction_codes", "message": "Choose at least one geography."}])
    run = start_run(db, kind=body.kind, actor=actor.user, settings=settings, scope_mode=body.scope_mode, jurisdiction_codes=body.jurisdiction_codes,
                    checks=body.checks, source_set=body.source_set, alert_recipients=body.alert_recipients)
    if not run.jurisdiction_ids:
        raise Invalid(errors=[{"field": "jurisdiction_codes", "message": "No geography matches this choice."}])
    db.commit()
    background.add_task(run_in_background, request.app, run.id)
    return run_out(db, run)


@router.get("/admin/laws/refresh")
def list_runs(kind: str = "law", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_REG_CHANGES if kind == "law" else Action.VIEW_LITIGATION)
    from app.laws.refresh import fail_stale_runs

    _fail_stale(db)
    fail_stale_runs(db)
    db.flush()
    rows = [run_out(db, r) for r in db.scalars(select(RefreshRun).where(RefreshRun.kind == kind).order_by(RefreshRun.started_at.desc()).limit(50))]
    if kind == "law":
        rows += [_legacy_out(db, r) for r in db.scalars(select(LawRefreshRun).order_by(LawRefreshRun.created_at.desc()).limit(50))]
    return sorted(rows, key=lambda r: r["started_at"], reverse=True)


def _fail_stale(db: Session) -> None:
    from app.core.clock import utcnow

    cutoff = utcnow() - timedelta(hours=2)
    for run in db.scalars(select(RefreshRun).where(RefreshRun.status.in_(("queued", "running")), RefreshRun.started_at < cutoff)):
        run.status, run.error, run.finished_at = "failed", "The run was interrupted before it finished (the server restarted). Start it again.", utcnow()


@router.get("/admin/laws/refresh/{run_id}")
def get_run(run_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    run = db.get(RefreshRun, run_id)
    if run is not None:
        authorize(db, actor, Action.VIEW_REG_CHANGES if run.kind == "law" else Action.VIEW_LITIGATION)
        return run_out(db, run, detail=True)
    authorize(db, actor, Action.VIEW_REG_CHANGES)
    legacy = db.get(LawRefreshRun, run_id)
    if legacy is None:
        raise NotFound()
    return _legacy_out(db, legacy, detail=True)


def _setting_out(db: Session, kind: str) -> dict:
    from app.staffalerts.service import get_setting

    s = get_run_setting(db, kind)
    codes = dict(db.execute(select(Jurisdiction.id, Jurisdiction.code)).all())
    alert = get_setting(db, "litigation_refresh" if kind == "litigation" else "law_refresh")
    srcs = list(db.scalars(select(Source).where(Source.active.is_(True))))
    nxt = (s.last_scheduled_at + timedelta(days=s.every_days)) if s.last_scheduled_at else None
    return {
        "kind": kind, "schedule_enabled": s.schedule_enabled, "every_days": s.every_days, "scope_mode": s.scope_mode,
        "jurisdiction_codes": [codes.get(i, i) for i in s.jurisdiction_ids or []], "checks": s.checks or list(CHECKS[kind]), "source_set": s.source_set,
        "cost_cap_usd": s.cost_cap_usd, "last_scheduled_at": s.last_scheduled_at.isoformat() if s.last_scheduled_at else None, "next_due": nxt.isoformat() if nxt else None,
        "check_options": [{"value": c, "label": CHECK_LABELS[c]} for c in CHECKS[kind]],
        "counts": {"all": len(jurisdictions_for(db, kind, "all", None)), "client_geographies": len(jurisdictions_for(db, kind, "client_geographies", None)),
                   "official_sources": sum(x.kind == "official" for x in srcs), "secondary_sources": sum(x.kind == "secondary" for x in srcs)},
        "alert": {"recipients_rule": alert.recipients_rule, "cc_roles": alert.cc_roles or [], "channels": alert.channels or []},
    }


@router.get("/admin/laws/refresh-settings/{kind}")
def get_run_settings(kind: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if kind not in CHECKS:
        raise NotFound()
    authorize(db, actor, Action.VIEW_REG_CHANGES if kind == "law" else Action.VIEW_LITIGATION)
    return _setting_out(db, kind) | {"enabled": client_for(request.app.state, request.app.state.settings) is not None, "model": request.app.state.settings.claude_model}


class RunSettingIn(BaseModel):
    schedule_enabled: bool | None = None
    every_days: int | None = Field(default=None, ge=1, le=90)
    scope_mode: str | None = None
    jurisdiction_codes: list[str] | None = None
    checks: list[str] | None = None
    source_set: str | None = None
    cost_cap_usd: float | None = Field(default=None, ge=0.5, le=500)


@router.put("/admin/laws/refresh-settings/{kind}")
def put_run_settings(kind: str, body: RunSettingIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    if kind not in CHECKS:
        raise NotFound()
    authorize(db, actor, _run_action(kind))
    s = get_run_setting(db, kind)
    data = body.model_dump(exclude_unset=True)
    if "scope_mode" in data and data["scope_mode"] not in ("all", "client_geographies", "chosen"):
        raise Invalid(errors=[{"field": "scope_mode", "message": "Unknown scope."}])
    if "checks" in data:
        data["checks"] = [c for c in data["checks"] or [] if c in CHECKS[kind]]
    if "jurisdiction_codes" in data:
        codes = [c.upper() for c in data.pop("jurisdiction_codes") or []]
        s.jurisdiction_ids = list(db.scalars(select(Jurisdiction.id).where(Jurisdiction.code.in_(codes))))
    for k, v in data.items():
        setattr(s, k, v)
    s.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="refresh.settings", object_type="RefreshSetting", object_id=s.id, request=request, organization_id=actor.organization.id,
                 summary=f"Changed {kind} refresh settings")
    db.flush()
    return _setting_out(db, kind)


# ---- the review queue
def _subject(db: Session, c: ProposedChange, meta: RefreshProposalMeta | None) -> str:
    if c.regulation_id:
        r = db.get(Regulation, c.regulation_id)
        return r.short_name if r else ""
    if meta and meta.case_id:
        case = db.get(Case, meta.case_id)
        return case.name if case else ""
    if isinstance(c.new_value, dict):
        return c.new_value.get("short_name") or c.new_value.get("name") or "New"
    return "New"


def change_out(db: Session, c: ProposedChange, detail: bool = False) -> dict:
    meta = db.get(RefreshProposalMeta, c.id)
    impacts = list(db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == c.id)))
    j = db.get(Jurisdiction, c.jurisdiction_id) if c.jurisdiction_id else None
    needs = meta.needs_second_review if meta else (c.confidence == "low" or c.change_type == "new_law")
    out = {
        "id": c.id, "kind": meta.kind if meta else "law", "origin": c.origin, "change_type": c.change_type, "change_label": CHANGE_LABELS.get(c.change_type, c.change_type),
        "subject": _subject(db, c, meta), "regulation_id": c.regulation_id, "case_id": meta.case_id if meta else None, "jurisdiction": j.name if j else None,
        "field_path": c.field_path, "old_value": c.old_value, "new_value": c.new_value, "summary": c.summary, "source_url": c.source_url,
        "source_host": host_of(c.source_url) if c.source_url else None, "source_quote": c.source_quote, "confidence": c.confidence,
        "claude_confidence": meta.claude_confidence if meta else None, "off_allowlist": bool(meta and meta.off_allowlist), "needs_second_review": needs,
        "second_review": {"outcome": meta.second_review_outcome if meta else None, "note": meta.second_review_note if meta else None,
                          "by": _name(db, c.second_reviewer_id), "at": c.second_reviewed_at.isoformat() if c.second_reviewed_at else None},
        "assigned_reviewer": _name(db, meta.assigned_reviewer_id) if meta else None, "status": c.status, "review_note": c.review_note,
        "reviewer": _name(db, c.reviewer_id), "created_at": c.created_at.isoformat(), "seen_count": meta.seen_count if meta else 1,
        "run_ids": meta.run_ids if meta else ([c.refresh_run_id] if c.refresh_run_id else []),
        "impact": {"clients": len({i.organization_id for i in impacts}), "systems": len({s for i in impacts for s in (i.ai_system_ids or [])}),
                   "roles": sorted({r for i in impacts for r in (i.roles_affected or [])}), "letters": sum(bool(i.letter_update_needed) for i in impacts)},
        "notify_clients": meta.notify_clients if meta else True, "update_letters": meta.update_letters if meta else True,
    }
    if detail:
        from app.clientalerts.service import system_names

        out["impacts"] = [{"organization_id": i.organization_id, "organization_name": (db.get(Organization, i.organization_id) or Organization(name="")).name,
                           "systems": system_names(db, i.ai_system_ids or []), "roles": i.roles_affected or [], "letter_update_needed": i.letter_update_needed} for i in impacts]
        v = db.get(LawVersion, c.base_version_id) if c.base_version_id else None
        out["base_version_no"] = v.version_no if v else None
    return out


@router.get("/reg/changes")
def queue(kind: str = "law", status: str = "open", change_type: str | None = None, confidence: str | None = None, run_id: str | None = None,
          actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_REG_CHANGES if kind == "law" else Action.VIEW_LITIGATION)
    metas = {m.proposed_change_id: m for m in db.scalars(select(RefreshProposalMeta))}
    rows = [c for c in db.scalars(select(ProposedChange).order_by(ProposedChange.created_at.desc()).limit(1000)) if (metas[c.id].kind if c.id in metas else "law") == kind]
    counts = {"open": sum(c.status in OPEN_STATUSES for c in rows), "pending": sum(c.status == "pending" for c in rows), "held": sum(c.status == "held" for c in rows),
              "legal_review": sum(c.status == "legal_review" for c in rows), "decided": sum(c.status not in OPEN_STATUSES for c in rows)}
    if status == "open":
        rows = [c for c in rows if c.status in OPEN_STATUSES]
    elif status != "all":
        rows = [c for c in rows if c.status in status.split(",")]
    if change_type:
        rows = [c for c in rows if c.change_type in change_type.split(",")]
    if confidence:
        rows = [c for c in rows if c.confidence in confidence.split(",")]
    if run_id:
        rows = [c for c in rows if run_id in (metas[c.id].run_ids if c.id in metas else [c.refresh_run_id])]
    from app.staffalerts.service import futran_users_with

    return {"items": [change_out(db, c) for c in rows], "counts": counts,
            "reviewers": [{"id": u.id, "name": u.name} for u in futran_users_with(db, {"qa_reviewer", "legal_reviewer"})],
            "change_types": [{"value": k, "label": v} for k, v in CHANGE_LABELS.items() if (k in ("new_case", "case_update")) == (kind == "litigation")]}


def _change(db: Session, cid: str) -> ProposedChange:
    c = db.get(ProposedChange, cid)
    if c is None:
        raise NotFound()
    return c


@router.get("/reg/changes/{change_id}")
def get_change(change_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    c = _change(db, change_id)
    authorize(db, actor, Action.VIEW_REG_CHANGES if kind_of(db, c) == "law" else Action.VIEW_LITIGATION)
    return change_out(db, c, detail=True)


class DecideIn(BaseModel):
    action: str
    note: str | None = Field(default=None, max_length=1000)
    new_value: object | None = None
    notify_clients: bool | None = None
    update_letters: bool | None = None

    @field_validator("action")
    @classmethod
    def _a(cls, v):
        if v not in ACTIONS:
            raise ValueError("Approve, edit and approve, hold, reject or send to legal review.")
        return v


@router.post("/reg/changes/{change_id}/decide")
def decide_one(change_id: str, body: DecideIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.APPROVE_REG_CHANGE)
    c = _change(db, change_id)
    decide(db, request.app.state.settings, c, actor.user, body.action, new_value=body.new_value, note=body.note, notify_clients=body.notify_clients, update_letters=body.update_letters)
    return change_out(db, c, detail=True)


class SecondIn(BaseModel):
    outcome: str
    note: str = Field(min_length=1, max_length=1000)


@router.post("/reg/changes/{change_id}/second-review")
def second(change_id: str, body: SecondIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.SECOND_REVIEW_REG_CHANGE)
    c = _change(db, change_id)
    second_review(db, c, actor.user, body.outcome, body.note)
    return change_out(db, c, detail=True)


class AssignIn(BaseModel):
    user_id: str


@router.post("/reg/changes/{change_id}/assign")
def assign(change_id: str, body: AssignIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.APPROVE_REG_CHANGE)
    c = _change(db, change_id)
    from app.staffalerts.service import futran_users_with

    u = next((x for x in futran_users_with(db, {"qa_reviewer", "legal_reviewer"}) if x.id == body.user_id), None)
    if u is None:
        raise Invalid(errors=[{"field": "user_id", "message": "Choose a QA Reviewer or legal reviewer."}])
    assign_reviewer(db, c, actor.user, u)
    return change_out(db, c)


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    action: str
    note: str | None = Field(default=None, max_length=1000)


@router.post("/reg/changes/bulk")
def bulk(body: BulkIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.APPROVE_REG_CHANGE)
    if body.action not in ACTIONS or body.action == "edit_approve":
        raise Invalid(errors=[{"field": "action", "message": "Approve, hold, reject or send to legal review."}])
    results = []
    for cid in body.ids:
        c = db.get(ProposedChange, cid)
        if c is None:
            results.append({"id": cid, "ok": False, "error": "Not found."})
            continue
        try:
            with db.begin_nested():
                decide(db, request.app.state.settings, c, actor.user, body.action, note=body.note)
            results.append({"id": cid, "ok": True})
        except (Conflict, Invalid) as exc:
            results.append({"id": cid, "ok": False, "error": exc.detail})
    return {"results": results}
