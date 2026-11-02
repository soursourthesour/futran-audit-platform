"""Screen 26: regulatory change alerts (Futran `/reg/updates`) and "What this means for you" (client `/updates`)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound
from app.impact.assess import FEATURE_LABELS
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for, visible_org_ids
from app.regupdates import service as svc
from app.regupdates.models import RegulatoryAlert, RegulatoryUpdate
from app.tenancy.models import Organization, User

router = APIRouter(tags=["regulatory updates"])


class ReviewIn(BaseModel):
    approve: bool
    note: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


class AlertsIn(BaseModel):
    organization_ids: list[str]


class OpportunityIn(BaseModel):
    organization_id: str
    service_kind: str = "advisory"
    service: str | None = None


class LawChangeIn(BaseModel):
    field_path: str
    new_value: object | None = None
    summary: str | None = None


class DigestIn(BaseModel):
    enabled: bool


def _can(db: Session, actor: Actor, action: Action) -> bool:
    try:
        authorize(db, actor, action)
        return True
    except (Forbidden, NotFound):
        return False


def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def _jname(db: Session, jid: str | None) -> str | None:
    from app.reference.models import Jurisdiction

    j = db.get(Jurisdiction, jid) if jid else None
    return j.name if j else None


def _visible(db: Session, actor: Actor, org_ids: list[str]) -> list[str]:
    allowed = visible_org_ids(db, actor)
    return [o for o in org_ids if allowed is None or o in allowed]


def _org_names(db: Session, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        o = db.get(Organization, i)
        if o is not None:
            out.append({"id": o.id, "name": o.name})
    return sorted(out, key=lambda x: x["name"])


def update_out(db: Session, actor: Actor, u: RegulatoryUpdate) -> dict:
    alerts = list(db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == u.id, RegulatoryAlert.deleted_at.is_(None))))
    orgs = _visible(db, actor, [a.organization_id for a in alerts])
    manage = _can(db, actor, Action.MANAGE_REG_UPDATES)
    act = _can(db, actor, Action.ACT_ON_REG_UPDATES)
    return {
        "kind": "update", "id": u.id, "reference": u.reference, "change_type": u.change_type, "change_label": svc.CHANGE_LABELS[u.change_type],
        "jurisdiction_id": u.jurisdiction_id, "jurisdiction_name": _jname(db, u.jurisdiction_id), "regulation_id": u.regulation_id, "law_name": u.law_name,
        "title": u.title, "summary": u.summary, "todo_text": u.todo_text, "effective_on": u.effective_on.isoformat() if u.effective_on else None,
        "source_url": u.source_url, "source_name": u.source_name, "source_quote": u.source_quote, "affected_features": u.affected_features or [],
        "feature_labels": [FEATURE_LABELS[f] for f in u.affected_features or []], "watch": u.watch, "verify_note": u.verify_note, "status": u.status,
        "status_label": svc.STATUS_LABELS[u.status], "author_name": _name(db, u.created_by), "reviewed_by_name": _name(db, u.reviewed_by), "review_note": u.review_note,
        "published_at": u.published_at.isoformat() if u.published_at else None, "created_at": u.created_at.isoformat(),
        "client_count": len(orgs), "clients": _org_names(db, orgs), "proposed_change_id": u.proposed_change_id, "read_only": False,
        "can_edit": manage and u.status == "draft", "can_submit": manage and u.status == "draft",
        "can_review": manage and u.status == "awaiting_review" and actor.id not in {u.created_by, u.submitted_by},
        "can_act": act and u.status == "published" and not u.watch, "can_propose_law_change": act and u.status == "published" and bool(u.regulation_id) and u.change_type in svc.PC_TYPES,
        "can_withdraw": manage and u.status == "published",
    }


def library_out(db: Session, actor: Actor, pc) -> dict:
    from app.laws.models import Regulation
    from app.regmaster.models import ChangeImpact

    reg = db.get(Regulation, pc.regulation_id) if pc.regulation_id else None
    orgs = _visible(db, actor, list(dict.fromkeys(db.scalars(select(ChangeImpact.organization_id).where(ChangeImpact.proposed_change_id == pc.id)))))
    name = reg.short_name if reg else ((pc.new_value or {}).get("short_name") if isinstance(pc.new_value, dict) else None)
    return {
        "kind": "law_library", "id": pc.id, "reference": None, "change_type": pc.change_type, "change_label": svc.LIBRARY_LABELS.get(pc.change_type, pc.change_type),
        "jurisdiction_name": _jname(db, pc.jurisdiction_id or (reg.jurisdiction_id if reg else None)), "law_name": name, "title": pc.summary, "summary": pc.reason or pc.summary,
        "effective_on": None, "source_url": pc.source_url, "status": "published", "status_label": "From the law library", "watch": False, "feature_labels": [],
        "reviewed_by_name": _name(db, pc.reviewer_id), "published_at": pc.reviewed_at.isoformat() if pc.reviewed_at else pc.created_at.isoformat(),
        "client_count": len(orgs), "clients": _org_names(db, orgs), "read_only": True, "can_edit": False, "can_review": False, "can_act": False,
    }


def _library(db: Session, limit: int = 50) -> list:
    from app.regmaster.models import ProposedChange

    return list(db.scalars(select(ProposedChange).where(ProposedChange.status.in_(("approved", "edited_approved"))).order_by(ProposedChange.reviewed_at.desc(), ProposedChange.created_at.desc()).limit(limit)))


def load(db: Session, actor: Actor, uid: str) -> RegulatoryUpdate:
    authorize(db, actor, Action.VIEW_REG_UPDATES)
    u = db.get(RegulatoryUpdate, uid)
    if u is None:
        raise NotFound()
    return u


# ---------------------------------------------------------------- Futran
@router.get("/reg/updates")
def list_updates(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_REG_UPDATES)
    ups = list(db.scalars(select(RegulatoryUpdate).where(RegulatoryUpdate.status != "withdrawn").order_by(RegulatoryUpdate.created_at.desc())))
    rows = [update_out(db, actor, u) for u in ups] + [library_out(db, actor, pc) for pc in _library(db)]
    rows.sort(key=lambda r: (r["status"] != "awaiting_review", -(_ts(r))))
    counts = {"all": len(rows), "awaiting_review": sum(r["status"] == "awaiting_review" for r in rows), "published": sum(r["status"] == "published" for r in rows)}
    allowed = visible_org_ids(db, actor)
    clients = [o for o in db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name))
               if allowed is None or o.id in allowed]
    return {"rows": rows, "counts": counts, "can_add": _can(db, actor, Action.MANAGE_REG_UPDATES), "can_manage_digest": _can(db, actor, Action.MANAGE_UPDATE_DIGEST),
            "clients": [{"id": o.id, "name": o.name} for o in clients], "features": [{"value": k, "label": v} for k, v in FEATURE_LABELS.items()],
            "change_types": [{"value": k, "label": v} for k, v in svc.CHANGE_LABELS.items()]}


def _ts(r: dict) -> float:
    from datetime import datetime

    v = r.get("published_at") or r.get("created_at")
    return datetime.fromisoformat(v).timestamp() if v else 0


@router.get("/reg/updates/calendar")
def futran_calendar(organization_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_REG_UPDATES)
    allowed = visible_org_ids(db, actor)
    ids = None if allowed is None else sorted(allowed)
    if organization_id:
        if allowed is not None and organization_id not in allowed:
            raise NotFound()
        ids = [organization_id]
    rows = svc.calendar(db, ids)
    for r in rows:
        r["clients"] = _org_names(db, _visible(db, actor, r.pop("organization_ids")))
    return {"rows": [r for r in rows if r["clients"]]}


@router.get("/reg/updates/digest")
def digest_settings(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_UPDATE_DIGEST)
    from app.regupdates.models import UpdateDigestRun

    out = []
    for o in db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name)):
        last = db.scalar(select(UpdateDigestRun).where(UpdateDigestRun.organization_id == o.id, UpdateDigestRun.status == "sent").order_by(UpdateDigestRun.week_start.desc()).limit(1))
        out.append({"organization_id": o.id, "name": o.name, "enabled": svc.digest_enabled(db, o.id), "last_sent_at": last.sent_at.isoformat() if last and last.sent_at else None})
    return {"rows": out}


@router.put("/reg/updates/digest/{org_id}")
def set_digest(org_id: str, body: DigestIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_UPDATE_DIGEST, org_id=org_id)
    o = db.get(Organization, org_id)
    if o is None or o.type != "client":
        raise NotFound()
    s = svc.set_digest(db, actor.user, org_id, body.enabled)
    return {"organization_id": org_id, "enabled": s.enabled}


@router.get("/reg/updates/law-library/{pc_id}/impact/{org_id}")
def library_impact(pc_id: str, org_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.regmaster.models import ChangeImpact

    authorize(db, actor, Action.VIEW_REG_UPDATES, org_id=org_id)
    ids: list[str] = []
    for imp in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc_id, ChangeImpact.organization_id == org_id)):
        ids += [i for i in imp.ai_system_ids or [] if i not in ids]
    o = db.get(Organization, org_id)
    return {"organization_id": org_id, "client_name": o.name if o else "", **svc.impact(db, org_id, ids), "todos": [], "match_reason": None}


@router.post("/reg/updates")
def add_update(body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_REG_UPDATES)
    return update_out(db, actor, svc.create(db, actor.user, body))


@router.get("/reg/updates/{uid}")
def get_update(uid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    return update_out(db, actor, load(db, actor, uid))


@router.patch("/reg/updates/{uid}")
def edit_update(uid: str, body: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.MANAGE_REG_UPDATES)
    return update_out(db, actor, svc.update(db, actor.user, u, body))


@router.post("/reg/updates/{uid}/submit")
def submit_update(uid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.MANAGE_REG_UPDATES)
    return update_out(db, actor, svc.submit(db, actor.user, u))


@router.post("/reg/updates/{uid}/review")
def review_update(uid: str, body: ReviewIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.MANAGE_REG_UPDATES)
    return update_out(db, actor, svc.review(db, request.app.state.settings, actor.user, u, body.approve, body.note))


@router.post("/reg/updates/{uid}/withdraw")
def withdraw_update(uid: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.MANAGE_REG_UPDATES)
    return update_out(db, actor, svc.withdraw(db, actor.user, u, body.reason))


@router.get("/reg/updates/{uid}/impact/{org_id}")
def update_impact(uid: str, org_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.VIEW_REG_UPDATES, org_id=org_id)
    a = svc.alert_for(db, u, org_id)
    o = db.get(Organization, org_id)
    from app.clientalerts.models import AlertSend

    send = db.get(AlertSend, a.alert_send_id) if a.alert_send_id else None
    return {"organization_id": org_id, "client_name": o.name if o else "", "match_reason": a.match_reason, **svc.impact(db, org_id, a.affected_system_ids or []),
            "todos": svc.todos(db, u), "alert_status": send.status if send else None, "opportunity_id": a.opportunity_id}


@router.post("/reg/updates/{uid}/alerts")
def send_alerts(uid: str, body: AlertsIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.ACT_ON_REG_UPDATES)
    out = []
    for org_id in body.organization_ids:
        authorize(db, actor, Action.ACT_ON_REG_UPDATES, org_id=org_id)
        s = svc.queue_alert(db, request.app.state.settings, actor.user, u, org_id)
        out.append({"organization_id": org_id, "alert_send_id": s.id, "status": s.status})
    return {"queued": out}


@router.post("/reg/updates/{uid}/opportunity")
def create_opportunity(uid: str, body: OpportunityIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.ACT_ON_REG_UPDATES, org_id=body.organization_id)
    o = svc.open_opportunity(db, actor.user, u, body.organization_id, body.service_kind, body.service)
    return {"opportunity_id": o.id, "needs_ca_approval": o.needs_ca_approval}


@router.post("/reg/updates/{uid}/law-change")
def law_change(uid: str, body: LawChangeIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    u = load(db, actor, uid)
    authorize(db, actor, Action.ACT_ON_REG_UPDATES)
    pc = svc.propose_law_change(db, actor, u, body.field_path, body.new_value, body.summary)
    return {"proposed_change_id": pc.id, "status": pc.status}


# ---------------------------------------------------------------- client: "What this means for you"
@router.get("/updates")
def client_updates(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    from app.register.models import RegisterSystem

    if actor.is_futran:
        raise NotFound()
    org = actor.organization
    authorize(db, actor, Action.VIEW_CLIENT_UPDATES, org_id=org.id, list_view=True)
    depts = departments_for(actor, Action.VIEW_CLIENT_UPDATES)
    items = []
    pairs = db.execute(select(RegulatoryAlert, RegulatoryUpdate).join(RegulatoryUpdate, RegulatoryUpdate.id == RegulatoryAlert.update_id)
                       .where(RegulatoryAlert.organization_id == org.id, RegulatoryAlert.deleted_at.is_(None), RegulatoryUpdate.status.in_(("published", "withdrawn")),
                              RegulatoryUpdate.published_at.is_not(None), RegulatoryUpdate.watch.is_(False))
                       .order_by(RegulatoryUpdate.published_at.desc())).all()
    for a, u in pairs:
        systems = []
        for sid in a.affected_system_ids or []:
            s = db.get(RegisterSystem, sid)
            if s is None or s.deleted_at is not None or (depts is not None and not s.company_wide and s.department_id not in depts):
                continue
            systems.append({"id": s.id, "reference": s.reference, "name": s.name, "risk_tier": s.risk_tier})
        if depts is not None and not systems:
            continue  # a Department Compliance Lead sees the updates that touch their department's systems
        withdrawn = u.status == "withdrawn"  # a client that was shown the update sees it withdrawn, with the reason, rather than losing it
        items.append({"id": u.id, "kind": "update", "change_label": svc.CHANGE_LABELS[u.change_type], "law_name": u.law_name, "jurisdiction_name": _jname(db, u.jurisdiction_id),
                      "title": u.title, "summary": u.summary, "effective_on": u.effective_on.isoformat() if u.effective_on else None, "source_url": u.source_url,
                      "published_at": u.published_at.isoformat() if u.published_at else None, "systems": systems, "todos": [] if withdrawn else svc.todos(db, u),
                      "why": a.match_reason, "status": u.status, "withdrawn_at": u.withdrawn_at.isoformat() if withdrawn and u.withdrawn_at else None,
                      "withdrawn_reason": u.withdrawn_reason if withdrawn else None})
    items += _sent_law_changes(db, org.id, depts)
    cal = svc.calendar(db, [org.id])
    for r in cal:
        r.pop("organization_ids", None)
    return {"items": items, "calendar": cal}


def _sent_law_changes(db: Session, org_id: str, depts) -> list[dict]:
    """Law-library changes the Chief Auditor sent to this client through Client alerts (A1)."""
    from app.clientalerts.models import AlertSend
    from app.register.models import RegisterSystem

    out = []
    for s in db.scalars(select(AlertSend).where(AlertSend.organization_id == org_id, AlertSend.status == "sent", AlertSend.change_ref.like("change:%")).order_by(AlertSend.sent_at.desc()).limit(20)):
        systems = [x for x in (db.get(RegisterSystem, i) for i in s.affected_system_ids or []) if x is not None and x.deleted_at is None
                   and (depts is None or x.company_wide or x.department_id in depts)]
        if depts is not None and not systems:
            continue
        out.append({"id": s.id, "kind": "law_library", "change_label": "Law change", "law_name": None, "jurisdiction_name": None, "title": s.headline, "summary": s.intro,
                    "effective_on": s.deadline.isoformat() if s.deadline else None, "source_url": None, "published_at": s.sent_at.isoformat() if s.sent_at else None,
                    "systems": [{"id": x.id, "reference": x.reference, "name": x.name, "risk_tier": x.risk_tier} for x in systems], "todos": s.todo_items or [], "why": None})
    return out
