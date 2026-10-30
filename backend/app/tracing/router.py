"""Tracing add-on endpoints (client app): R7 `/register/{id}/tracing…` and R8 `/addons…` (spec §27.3, §27.8).
The tenant is always the signed-in user's organization; every endpoint calls `authorize` (through app.tracing.access)."""
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.register.models import HistoryEntry, RegisterSystem
from app.tenancy.models import User
from app.tracing import addons, incidents as inc_svc, traces as tr_svc
from app.tracing import deadlines as D
from app.tracing.guardrail import mode as guardrail_mode
from app.tracing.access import check, client_org, load_system, may, state_for

router = APIRouter(tags=["tracing"])


class DecideIn(BaseModel):
    approve: bool
    comment: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


class BulkIn(BaseModel):
    ids: list[str]
    owner_id: str | None = None


# ---------------------------------------------------------------- R8: unlock (the Add-ons page and dialog)
def _has(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action, org_id=client_org(actor).id)
        return True
    except (Forbidden, NotFound):
        return False


@router.get("/addons/tracing")
def get_addons(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_ADDONS, org_id=org.id)
    return addons.page(db, org.id, can_request=_has(db, actor, Action.REQUEST_ADDON), can_approve=_has(db, actor, Action.APPROVE_ADDON))


@router.post("/addons/tracing/requests")
def post_request(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = client_org(actor)
    authorize(db, actor, Action.REQUEST_ADDON, org_id=org.id)
    return addons.request_out(db, addons.request(db, settings, actor, data))


@router.post("/addons/requests/{sub_id}/decide")
def post_decide(sub_id: str, body: DecideIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = client_org(actor)
    addons._load(db, actor, sub_id)  # 404 outside the tenant before 403
    authorize(db, actor, Action.APPROVE_ADDON, org_id=org.id)
    return addons.request_out(db, addons.decide(db, settings, actor, sub_id, body.approve, body.comment))


@router.post("/addons/requests/{sub_id}/cancel")
def post_cancel(sub_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = client_org(actor)
    addons._load(db, actor, sub_id)
    authorize(db, actor, Action.APPROVE_ADDON, org_id=org.id)
    return addons.request_out(db, addons.cancel(db, settings, actor, sub_id, body.reason))


# ---------------------------------------------------------------- R7: the Tracing tab
def _system(db: Session, actor: Actor, system_id: str, action: Action = Action.VIEW_TRACING) -> RegisterSystem:
    s = load_system(db, actor, system_id)
    check(db, actor, action, s)
    return s


def _active(db: Session, s: RegisterSystem) -> None:
    if state_for(db, s)[0] != "active":
        raise Conflict("Unlock the tracing add-on for this system first.")


def _people(db: Session, org_id: str) -> list[dict]:
    users = db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name))
    return [{"id": u.id, "name": u.name, "job_title": u.job_title} for u in users]


@router.get("/register/{system_id}/tracing")
def get_tracing(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    from app.register.history import tracing_reasons

    s = _system(db, actor, system_id)
    state, sub = state_for(db, s)
    reasons = tracing_reasons(db, s)
    out = {
        "system": {"id": s.id, "reference": s.reference, "name": s.name, "type": s.type, "stage": s.stage, "risk_tier": s.risk_tier, "guardrail_policy_ref": s.guardrail_policy_ref},
        "state": state, "recommended": bool(reasons), "reasons": reasons,
        "subscription": addons.request_out(db, sub) if sub else None,
        "law_families": inc_svc.law_families(db, s), "family_labels": D.FAMILY_LABELS,
        "can_record_traces": may(db, actor, Action.RECORD_TRACES, s), "can_manage_incidents": may(db, actor, Action.MANAGE_INCIDENTS, s),
        "can_request": _has(db, actor, Action.REQUEST_ADDON),
        "incidents": [], "traces": [], "kpis": None, "people": [], "history_incidents": [],
    }
    now = utcnow()
    held = inc_svc.incidents_of(db, s)
    out["kept"] = {"incidents": len(held), "traces": tr_svc.kpis(db, s)["total"]}  # records kept while locked (after a cancellation)
    if state != "active":
        return out
    out["incidents"] = [inc_svc.incident_out(db, i, now) for i in held]
    out["traces"] = [tr_svc.trace_out(t) for t in tr_svc.query(db, s, period="24h")]
    out["kpis"] = {**tr_svc.kpis(db, s), "open_incidents": sum(1 for i in held if i.status != "closed"), "deadlines_missed": inc_svc.missed_count(db, s, now)}
    out["people"] = _people(db, s.organization_id)
    linked = {i.history_entry_id for i in held}
    out["history_incidents"] = [{"id": e.id, "occurred_on": e.occurred_on.isoformat(), "summary": e.summary} for e in db.scalars(
        select(HistoryEntry).where(HistoryEntry.register_system_id == s.id, HistoryEntry.type == "incident", HistoryEntry.deleted_at.is_(None)).order_by(HistoryEntry.occurred_on.desc()))
        if e.id not in linked]
    out["guardrail_connected"] = tr_svc.guardrail_feed(db, settings, s.organization_id) is not None
    out["guardrail_needs_token"] = guardrail_mode(settings) == "live" and not out["guardrail_connected"]
    out["can_set_guardrail_token"] = _has(db, actor, Action.REQUEST_ADDON) and not actor.is_futran
    return out


class GuardRailTokenIn(BaseModel):
    token: str = Field(min_length=8, max_length=2000)


def _token_org(db: Session, actor: Actor):
    org = client_org(actor)
    if actor.is_futran:
        raise Forbidden()
    authorize(db, actor, Action.REQUEST_ADDON, org_id=org.id)  # Client Admin or CAICO, own organisation only
    return org


@router.put("/tracing/guardrail-token")
def put_guardrail_token(body: GuardRailTokenIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    """The organisation's own GuardRail access token, stored encrypted and never shown again."""
    from app.audit_log import service as audit
    from app.mail.tokens import seal
    from app.tracing.models import TracingOrgSettings

    org = _token_org(db, actor)
    token = body.token.strip()
    if any(c.isspace() for c in token):
        raise Invalid(errors=[{"field": "token", "message": "Paste the token exactly as GuardRail shows it, without spaces."}])
    row = db.scalar(select(TracingOrgSettings).where(TracingOrgSettings.organization_id == org.id))
    if row is None:
        row = TracingOrgSettings(organization_id=org.id, created_by=actor.id)
        db.add(row)
    row.guardrail_token_ref, row.guardrail_token_encrypted = seal(settings, token)
    row.guardrail_token_set_at, row.updated_by, row.deleted_at = utcnow(), actor.id, None
    db.flush()
    audit.record(db, actor_id=actor.id, action="tracing.guardrail_token_set", object_type="TracingOrgSettings", object_id=row.id, organization_id=org.id,
                 summary="Set the organisation's GuardRail access token")
    return {"guardrail_token_set": True}


@router.delete("/tracing/guardrail-token")
def delete_guardrail_token(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.audit_log import service as audit
    from app.tracing.models import TracingOrgSettings

    org = _token_org(db, actor)
    row = db.scalar(select(TracingOrgSettings).where(TracingOrgSettings.organization_id == org.id))
    if row is not None and row.guardrail_token_encrypted:
        row.guardrail_token_encrypted, row.guardrail_token_ref, row.updated_by = None, None, actor.id
        audit.record(db, actor_id=actor.id, action="tracing.guardrail_token_removed", object_type="TracingOrgSettings", object_id=row.id, organization_id=org.id,
                     summary="Removed the organisation's GuardRail access token")
    return {"guardrail_token_set": False}


@router.get("/register/{system_id}/tracing/traces")
def get_traces(system_id: str, decision: str | None = None, period: str = "24h", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id)
    _active(db, s)
    return {"rows": [tr_svc.trace_out(t) for t in tr_svc.query(db, s, decision=decision or None, period=period)]}


@router.post("/register/{system_id}/tracing/traces")
def post_trace(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.RECORD_TRACES)
    _active(db, s)
    return tr_svc.trace_out(tr_svc.add_manual(db, actor, s, data))


@router.post("/register/{system_id}/tracing/traces/import")
async def post_import(system_id: str, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.RECORD_TRACES)
    _active(db, s)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise Invalid(errors=[{"field": "file", "message": "The file is over 20 MB. Split it and import each part."}])
    imp = tr_svc.import_file(db, actor, s, file.filename or "", data)
    return {"added": imp.added, "skipped": imp.skipped}


@router.post("/register/{system_id}/tracing/guardrail-sync")
def post_guardrail_sync(system_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    s = _system(db, actor, system_id, Action.RECORD_TRACES)
    _active(db, s)
    imp = tr_svc.guardrail_sync(db, settings, actor, s)
    return {"added": imp.added, "skipped": imp.skipped}


@router.get("/register/{system_id}/tracing/export")
def get_export(system_id: str, what: str = "incidents", actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.audit_log import service as audit

    s = _system(db, actor, system_id)
    if what == "traces":
        text = tr_svc.export_traces(db, s)
    elif what == "incidents":
        text = _incidents_csv(db, s)
    else:
        raise Invalid(errors=[{"field": "what", "message": "Choose traces or incidents."}])
    audit.record(db, actor_id=actor.id, action=f"tracing.exported_{what}", obj=s, summary=f"Exported the {what} of {s.name}")
    name = f"{s.reference}-{what}-{utcnow():%Y%m%d}.csv"
    return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _incidents_csv(db: Session, s: RegisterSystem) -> str:
    header = ["Incident", "Found", "What happened", "Severity", "Serious incident", "People affected", "Cause", "Containment", "Fix", "Status", "Closed",
              "Notice to", "Law", "Citation", "Period", "Due", "Binding", "Notice status", "Made on", "Reference", "Reason not applicable"]
    rows = []
    for i in inc_svc.incidents_of(db, s):
        o = inc_svc.incident_out(db, i)
        base = [o["code"], o["found_at"], o["description"], o["severity_label"], o["serious_label"], o["people_affected"], o["cause"], o["containment"], o["fix"], o["status_label"], o["closed_on"]]
        dls = [d for d in o["deadlines"] if d["status"] != "withdrawn"] or [None]
        for d in dls:
            rows.append(base + ([d["recipient"], d["law"], d["citation"], d["period_text"], d["due_at"], "Yes" if d["binding"] else "Not yet", d["status_label"], d["done_at"], d["reference"], d["na_reason"]]
                                if d else ["", "", "", "", "", "", "", "", "", ""]))
    return tr_svc.csv_text(header, rows)


@router.post("/register/{system_id}/tracing/incidents")
def post_incident(system_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    s = _system(db, actor, system_id, Action.MANAGE_INCIDENTS)
    _active(db, s)
    return inc_svc.incident_out(db, inc_svc.create(db, settings, actor, s, data))


@router.patch("/register/{system_id}/tracing/incidents/{incident_id}")
def patch_incident(system_id: str, incident_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    s = _system(db, actor, system_id, Action.MANAGE_INCIDENTS)
    _active(db, s)
    return inc_svc.incident_out(db, inc_svc.update(db, settings, actor, s, inc_svc.load(db, s, incident_id), data))


@router.post("/register/{system_id}/tracing/incidents/{incident_id}/close")
def post_close(system_id: str, incident_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.MANAGE_INCIDENTS)
    _active(db, s)
    return inc_svc.incident_out(db, inc_svc.close(db, actor, s, inc_svc.load(db, s, incident_id), data))


@router.post("/register/{system_id}/tracing/incidents/bulk")
def post_bulk(system_id: str, body: BulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    s = _system(db, actor, system_id, Action.MANAGE_INCIDENTS)
    _active(db, s)
    rows = [inc_svc.load(db, s, i) for i in dict.fromkeys(body.ids)]
    if not rows:
        raise Invalid(errors=[{"field": "ids", "message": "Choose at least one incident."}])
    n = 0
    for inc in rows:
        if inc.status != "closed":
            inc_svc.update(db, settings, actor, s, inc, {"owner_id": body.owner_id})
            n += 1
    return {"updated": n}


@router.post("/register/{system_id}/tracing/deadlines/{deadline_id}")
def post_deadline(system_id: str, deadline_id: str, data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    s = _system(db, actor, system_id, Action.MANAGE_INCIDENTS)
    _active(db, s)
    return inc_svc.incident_out(db, inc_svc.act_on_deadline(db, actor, s, inc_svc.load_deadline(db, s, deadline_id), data))

