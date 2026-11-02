"""Regulatory change alerts (spec §21 F4): curated updates, a second reviewer, matching to clients, impact per client,
the deadline calendar, client alerts through A1, advisory opportunities through S1, the law-change proposal (M3) and
the weekly digest."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.impact.assess import FEATURE_LABELS, project_features
from app.regupdates.models import CHANGE_TYPES, FEATURES, RegulatoryAlert, RegulatoryUpdate, UpdateDigestRun, UpdateDigestSetting
from app.tenancy.models import Organization, User

CHANGE_LABELS = {"new_law": "New law", "amendment": "Amendment", "effective_date": "Effective date", "enforcement_action": "Enforcement",
                 "guidance": "Guidance", "court_ruling": "Court ruling", "pending_bill": "Pending bill"}
STATUS_LABELS = {"draft": "Draft", "awaiting_review": "Awaiting review", "published": "Published", "withdrawn": "Withdrawn"}
# ProposedChange.change_type (M3) for "Propose the law change"; a pending bill is not a law yet
PC_TYPES = {"new_law": "new_law", "amendment": "amendment", "effective_date": "effective_date", "enforcement_action": "enforcement", "guidance": "guidance",
            "court_ruling": "amendment"}
LIBRARY_LABELS = {"new_rule": "New rule", "amendment": "Amendment", "effective_date": "Effective date", "guidance": "Guidance", "new_law": "New law",
                  "repeal": "Repeal", "role_mapping": "Role change", "enforcement": "Enforcement"}
IN_USE = ("in_development", "ready_for_go_live", "live")


# ---------------------------------------------------------------- entry and review
def next_reference(db: Session) -> str:
    refs = db.scalars(select(RegulatoryUpdate.reference))
    n = max((int(r[3:]) for r in refs if r and r[3:].isdigit()), default=0)
    return f"RU-{n + 1:03d}"


def clean(db: Session, data: dict, current: RegulatoryUpdate | None = None) -> dict:
    from app.laws.publish import current_version_of
    from app.reference.models import Jurisdiction

    errs: list[dict] = []
    out: dict = {}
    creating = current is None

    def has(k):
        return k in data or creating

    if has("change_type"):
        if data.get("change_type") not in CHANGE_TYPES:
            errs.append({"field": "change_type", "message": "Choose the type of change."})
        out["change_type"] = data.get("change_type")
    for k, limit, msg in (("title", 300, "Give the update a headline."), ("summary", 4000, "Say what changed and who it affects.")):
        if has(k):
            v = str(data.get(k) or "").strip()
            if not v:
                errs.append({"field": k, "message": msg})
            out[k] = v[:limit]
    for k, limit in (("law_name", 200), ("source_name", 200), ("verify_note", 600)):
        if k in data:
            out[k] = (" ".join(str(data.get(k) or "").split()))[:limit] or None
    for k in ("todo_text", "source_quote"):
        if k in data:
            out[k] = str(data.get(k) or "").strip()[:4000] or None
    if "source_url" in data:
        v = str(data.get("source_url") or "").strip()
        if v and not v.startswith(("https://", "http://")):
            errs.append({"field": "source_url", "message": "Enter the full web address, starting https://."})
        out["source_url"] = v[:600] or None
    if "effective_on" in data:
        v = data.get("effective_on") or None
        if v is not None:
            try:
                v = date.fromisoformat(str(v))
            except ValueError:
                errs.append({"field": "effective_on", "message": "Enter a date."})
        out["effective_on"] = v
    if "affected_features" in data:
        v = data.get("affected_features") or []
        if not isinstance(v, list) or any(f not in FEATURES for f in v):
            errs.append({"field": "affected_features", "message": "Choose from the list of AI features."})
        out["affected_features"] = list(dict.fromkeys(v)) if isinstance(v, list) else []
    if "watch" in data:
        out["watch"] = bool(data.get("watch"))
    if "regulation_id" in data:
        rid = data.get("regulation_id") or None
        reg = current_version_of(db, rid) if rid else None
        if rid and reg is None:
            errs.append({"field": "regulation_id", "message": "Choose a law from the law library."})
        out["regulation_id"] = reg.id if reg else None
        if reg is not None:
            out.setdefault("law_name", None)
            out["law_name"] = out["law_name"] or reg.short_name
            if not data.get("jurisdiction_id"):
                out["jurisdiction_id"] = reg.jurisdiction_id
    if "jurisdiction_id" in data and data.get("jurisdiction_id"):
        if db.get(Jurisdiction, data["jurisdiction_id"]) is None:
            errs.append({"field": "jurisdiction_id", "message": "Choose the jurisdiction."})
        out["jurisdiction_id"] = data["jurisdiction_id"]
    final_j = out.get("jurisdiction_id", current.jurisdiction_id if current else None)
    if not final_j and (creating or "jurisdiction_id" in data):
        errs.append({"field": "jurisdiction_id", "message": "Choose the jurisdiction, or the law it changes."})
    if errs:
        raise Invalid(errors=errs)
    return out


def create(db: Session, actor: User, data: dict) -> RegulatoryUpdate:
    v = clean(db, data)
    u = RegulatoryUpdate(reference=next_reference(db), status="draft", created_by=actor.id, updated_by=actor.id, affected_features=v.pop("affected_features", []), **v)
    db.add(u)
    db.flush()
    audit.record(db, actor_id=actor.id, action="regupdate.create", obj=u, organization_id=actor.organization_id, summary=f"Drafted regulatory update {u.reference}: {u.title}")
    return u


def update(db: Session, actor: User, u: RegulatoryUpdate, data: dict) -> RegulatoryUpdate:
    if u.status != "draft":
        raise Conflict("Only a draft can be edited. Ask the reviewer to send it back.")
    if actor.id != u.created_by:
        raise Forbidden("Only the author edits a draft. Send your changes to the author, or review it when it is submitted.")
    changes = clean(db, data, current=u)
    for k, val in changes.items():
        setattr(u, k, val)
    u.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="regupdate.edit", obj=u, organization_id=actor.organization_id, after={"fields": sorted(changes)},
                 summary=f"Edited regulatory update {u.reference}")
    return u


def preparers(db: Session, u: RegulatoryUpdate) -> set[str]:
    """Everyone who wrote, edited or submitted the update. None of them may review it (spec §6 rule 2)."""
    from app.audit_log.models import AuditLog

    ids = {u.created_by, u.submitted_by}
    ids |= set(db.scalars(select(AuditLog.actor_id).where(AuditLog.object_id == u.id, AuditLog.action.in_(("regupdate.create", "regupdate.edit", "regupdate.submit")))))
    return {i for i in ids if i}


def submit(db: Session, actor: User, u: RegulatoryUpdate) -> RegulatoryUpdate:
    from app.notifications.service import notify

    if u.status != "draft":
        raise Conflict("This update is not a draft.")
    if not u.source_url:
        raise Invalid("Add the source before sending it for review.", [{"field": "source_url", "message": "Link the official source the update rests on."}])
    u.status, u.submitted_by, u.submitted_at, u.updated_by = "awaiting_review", actor.id, utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="regupdate.submit", obj=u, organization_id=actor.organization_id, summary=f"Sent {u.reference} for review")
    notify(db, [x for x in _reviewers(db) if x.id != actor.id], "regupdate_review", f"Review regulatory update {u.reference}", u.title, "/reg/updates?tab=awaiting_review")
    return u


def _reviewers(db: Session) -> list[User]:
    from app.tenancy.models import RoleAssignment

    ids = set(db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.role.in_(("chief_auditor", "legal_reviewer")), RoleAssignment.deleted_at.is_(None))))
    return [u for u in (db.get(User, i) for i in ids) if u is not None and u.deleted_at is None and u.status != "disabled"]


def review(db: Session, settings, actor: User, u: RegulatoryUpdate, approve: bool, note: str | None) -> RegulatoryUpdate:
    """The expert in the loop: a second reviewer publishes or sends back. The author never publishes their own update."""
    if u.status != "awaiting_review":
        raise Conflict("This update is not waiting for review.")
    if actor.id in preparers(db, u):
        raise Forbidden("You wrote, edited or submitted this update, so another reviewer must publish it.")
    note = (note or "").strip() or None
    if not approve and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what needs to change."}])
    u.reviewed_by, u.reviewed_at, u.review_note, u.updated_by = actor.id, utcnow(), (note or "")[:1000] or None, actor.id
    if not approve:
        u.status = "draft"
        audit.record(db, actor_id=actor.id, action="regupdate.return", obj=u, organization_id=actor.organization_id, after={"note": note}, summary=f"Sent {u.reference} back: {note}"[:300])
        return u
    u.status, u.published_at = "published", utcnow()
    alerts = match(db, u)
    triggers = raise_triggers(db, u, alerts, actor.id)
    audit.record(db, actor_id=actor.id, action="regupdate.publish", obj=u, organization_id=actor.organization_id,
                 after={"clients": len(alerts), "triggers": len(triggers), "note": note}, summary=f"Published {u.reference}: {u.title}"[:300])
    return u


def withdraw(db: Session, actor: User, u: RegulatoryUpdate, reason: str | None) -> RegulatoryUpdate:
    reason = (reason or "").strip()
    if u.status != "published":
        raise Conflict("Only a published update can be withdrawn.")
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why it is withdrawn."}])
    u.status, u.withdrawn_by, u.withdrawn_at, u.withdrawn_reason = "withdrawn", actor.id, utcnow(), reason[:1000]
    cancelled = _cancel_alerts(db, actor, u)
    closed = _close_triggers(db, actor, u)
    audit.record(db, actor_id=actor.id, action="regupdate.withdraw", obj=u, organization_id=actor.organization_id,
                 after={"reason": reason, "alerts_cancelled": len(cancelled), "triggers_closed": len(closed)}, summary=f"Withdrew {u.reference}")
    return u


def _cancel_alerts(db: Session, actor: User, u: RegulatoryUpdate) -> list:
    """Client alerts for the update not yet sent are cancelled, so they can no longer be approved and sent."""
    from app.clientalerts.models import AlertSend

    out = []
    for s in db.scalars(select(AlertSend).where(AlertSend.change_ref == f"update:{u.id}", AlertSend.status.in_(("waiting_approval", "held")))):
        s.status = "cancelled"
        audit.record(db, actor_id=actor.id, action="client_alert.cancel", obj=s, organization_id=s.organization_id, after={"reason": u.withdrawn_reason},
                     summary=f"Cancelled client alert: {u.reference} was withdrawn"[:300])
        out.append(s)
    return out


def _close_triggers(db: Session, actor: User, u: RegulatoryUpdate) -> list:
    """Open reassessment triggers the update raised are dismissed with the withdrawal reason."""
    from app.impact.models import OPEN_TRIGGER, ReassessmentTrigger

    now, out = utcnow(), []
    note = f"Regulatory update {u.reference} withdrawn: {u.withdrawn_reason}"[:4000]
    for t in db.scalars(select(ReassessmentTrigger).where(ReassessmentTrigger.source == "regulatory_update", ReassessmentTrigger.source_ref == f"update:{u.id}",
                                                          ReassessmentTrigger.status.in_(OPEN_TRIGGER), ReassessmentTrigger.deleted_at.is_(None))):
        t.status, t.resolution_note, t.resolved_by, t.resolved_at, t.updated_by = "dismissed", note, actor.id, now, actor.id
        audit.record(db, actor_id=actor.id, action="reassessment.dismiss", obj=t, organization_id=t.organization_id, after={"status": t.status, "note": note},
                     summary=f"Reassessment trigger dismissed: {u.reference} was withdrawn"[:300])
        out.append(t)
    return out


# ---------------------------------------------------------------- matching
def system_features(db: Session, s) -> list[str]:
    from app.register.service import data_row
    from app.tenancy.models import Department

    d = data_row(db, s)
    dept = db.get(Department, s.department_id) if s.department_id else None
    return project_features({"project_name": s.name, "purpose": s.purpose, "department_name": dept.name if dept else "", "system_type": s.type,
                             "decision_impact": s.decision_impact, "data_categories": d.data_categories if d else [], "data_subjects": d.data_subjects if d else []})


def _law_ids(db: Session, regulation_id: str | None) -> list[str]:
    from app.laws.publish import chain_ids

    return (chain_ids(db, regulation_id) or [regulation_id]) if regulation_id else []


def match_org(db: Session, u: RegulatoryUpdate, org_id: str) -> tuple[list[str], str] | None:
    """(affected register system ids, reason) when the update concerns this client, else None."""
    from app.reference.models import Jurisdiction
    from app.register.models import RegisterSystem, RegisterSystemLaw
    from app.regmaster.engine import expand, geographies
    from app.regmaster.models import ClientLawApplicability

    geo = expand(db, {g.jurisdiction_id for g in geographies(db, org_id)})
    in_geo = bool(u.jurisdiction_id) and u.jurisdiction_id in geo
    law_ids = _law_ids(db, u.regulation_id)
    in_scope = bool(law_ids) and db.scalar(select(ClientLawApplicability.id).where(ClientLawApplicability.organization_id == org_id, ClientLawApplicability.regulation_id.in_(law_ids),
                                                                                   ClientLawApplicability.in_scope.is_(True), ClientLawApplicability.deleted_at.is_(None)).limit(1)) is not None
    wanted = set(u.affected_features or [])
    affected, feats = [], set()
    systems = db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None), RegisterSystem.stage != "retired").order_by(RegisterSystem.reference))
    for s in systems:
        on_law = bool(law_ids) and db.scalar(select(RegisterSystemLaw.id).where(RegisterSystemLaw.register_system_id == s.id, RegisterSystemLaw.regulation_id.in_(law_ids),
                                                                                RegisterSystemLaw.status == "active", RegisterSystemLaw.deleted_at.is_(None)).limit(1)) is not None
        hit = wanted & set(system_features(db, s)) if wanted else set()
        if on_law or ((in_geo or in_scope) and hit):
            affected.append(s.id)
            feats |= hit
    if not (affected or in_scope or (in_geo and not wanted)):
        return None
    j = db.get(Jurisdiction, u.jurisdiction_id) if u.jurisdiction_id else None
    parts = []
    if in_scope:
        parts.append(f"In scope of {u.law_name or 'the law'}")
    elif in_geo and j is not None:
        parts.append(f"Operates in {j.name}")
    if affected:
        n = len(affected)
        parts.append(f"{n} {'system' if n == 1 else 'systems'}" + (f" in {', '.join(FEATURE_LABELS[f].lower() for f in sorted(feats))}" if feats else " carry this law"))
    return affected, "; ".join(parts)[:600] or "Matches the client's AI use"


def match(db: Session, u: RegulatoryUpdate) -> list[RegulatoryAlert]:
    """One RegulatoryAlert per client the published update concerns. Watch items are never matched."""
    if u.watch or u.status != "published":
        return []
    have = {a.organization_id: a for a in db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == u.id))}
    out = []
    for org in db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None)).order_by(Organization.name)):
        hit = match_org(db, u, org.id)
        if hit is None:
            continue
        a = have.get(org.id) or RegulatoryAlert(organization_id=org.id, update_id=u.id)
        a.affected_system_ids, a.match_reason, a.deleted_at = hit[0], hit[1], None
        db.add(a)
        out.append(a)
    db.flush()
    return out


def raise_triggers(db: Session, u: RegulatoryUpdate, alerts: list[RegulatoryAlert], actor_id: str | None) -> list:
    """A published update that affects a system in use asks for its reassessment (F8). Pending bills are not law yet."""
    from app.impact.triggers import raise_trigger
    from app.register.models import RegisterSystem

    if u.change_type == "pending_bill":
        return []
    out = []
    for a in alerts:
        for sid in a.affected_system_ids or []:
            s = db.get(RegisterSystem, sid)
            if s is None or s.stage not in IN_USE:
                continue
            t = raise_trigger(db, sid, type="regulatory_update", source="regulatory_update", source_ref=f"update:{u.id}",
                              detail=f"{u.reference} {CHANGE_LABELS[u.change_type]}: {u.title}", actor_id=actor_id)
            if t is not None:
                out.append(t)
    return out


def alert_for(db: Session, u: RegulatoryUpdate, org_id: str) -> RegulatoryAlert:
    a = db.scalar(select(RegulatoryAlert).where(RegulatoryAlert.update_id == u.id, RegulatoryAlert.organization_id == org_id, RegulatoryAlert.deleted_at.is_(None)))
    if a is None:
        raise Conflict("This update does not match that client.")
    return a


# ---------------------------------------------------------------- impact for one client
def todos(db: Session, u: RegulatoryUpdate) -> list[dict]:
    from app.laws.models import Regulation
    from app.regmaster.models import Requirement

    out = [{"code": str(i), "text": line.strip(" -•\t"), "deadline": u.effective_on.isoformat() if u.effective_on else None, "law": u.law_name or ""}
           for i, line in enumerate((u.todo_text or "").splitlines(), start=1) if line.strip(" -•\t")]
    reg = db.get(Regulation, u.regulation_id) if u.regulation_id else None
    if reg is not None and reg.current_version_id and not out:
        for r in db.scalars(select(Requirement).where(Requirement.law_version_id == reg.current_version_id).order_by(Requirement.order, Requirement.code)):
            out.append({"code": r.code, "text": r.text, "deadline": u.effective_on.isoformat() if u.effective_on else None, "law": reg.short_name})
    return out


def impact(db: Session, org_id: str, system_ids: list[str]) -> dict:
    """Affected register systems, open findings on them (from any engagement) and the remediation dates (screen 26)."""
    from app.engagements.models import Engagement
    from app.findings.models import Finding
    from app.register.models import RegisterSystem
    from app.remediation.models import RemediationItem
    from app.remediation.service import OPEN
    from app.systems.models import AISystem
    from app.tenancy.models import Department

    systems = []
    for sid in system_ids or []:
        s = db.get(RegisterSystem, sid)
        if s is None or s.organization_id != org_id or s.deleted_at is not None:
            continue
        dept = db.get(Department, s.department_id) if s.department_id else None
        systems.append({"id": s.id, "reference": s.reference, "name": s.name, "risk_tier": s.risk_tier, "stage": s.stage, "department": dept.name if dept else None})
    ids = [s["id"] for s in systems]
    findings = []
    if ids:
        rows = db.execute(select(Finding, AISystem, Engagement).join(AISystem, AISystem.id == Finding.ai_system_id).join(Engagement, Engagement.id == Finding.engagement_id)
                          .where(AISystem.register_system_id.in_(ids), Finding.deleted_at.is_(None), Finding.status.in_(("submitted", "approved")), Engagement.deleted_at.is_(None))
                          .order_by(Finding.ref)).all()
        for f, s, e in rows:
            items = list(db.scalars(select(RemediationItem).where(RemediationItem.finding_id == f.id, RemediationItem.deleted_at.is_(None))))
            if items and all(i.status == "closed" for i in items):
                continue
            due = min((i.due_date for i in items if i.status in OPEN + ("awaiting_verification",) and i.due_date), default=None)
            findings.append({"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "engagement": e.name, "system_reference": s.reference_id,
                             "register_system_id": s.register_system_id, "remediation_due": due.isoformat() if due else None,
                             "remediation_status": "Not started" if not items else ("Overdue" if due and due < utcnow().date() else "Open")})
    return {"systems": systems, "findings": findings}


# ---------------------------------------------------------------- A1, S1 and M3
def queue_alert(db: Session, settings, actor: User, u: RegulatoryUpdate, org_id: str):
    """"Send alert to client": one A1 send for this client, waiting for the Chief Auditor's approval in Client alerts."""
    from app.clientalerts.service import _queue, rule_for

    if u.status != "published" or u.watch:
        raise Conflict("Only a published update that is not a watch item can be sent to clients.")
    a = alert_for(db, u, org_id)
    rule = rule_for(db, "regulatory_update")
    if rule is None or not rule.active:
        raise Conflict("The client alert rule for regulatory updates is paused. Turn it on in Client alerts.")
    s = _queue(db, settings, rule, org_id, f"update:{u.id}", f"{CHANGE_LABELS[u.change_type]}: {u.law_name or ''}: {u.title}".replace(": :", ":")[:300],
               list(a.affected_system_ids or []), todos(db, u), u.effective_on, actor_id=actor.id)
    if s.intro is None and u.summary:
        s.intro = u.summary[:4000]
    a.alert_send_id = s.id
    audit.record(db, actor_id=actor.id, action="regupdate.alert_queued", obj=u, organization_id=org_id, after={"alert_send_id": s.id},
                 summary=f"Queued {u.reference} for the client in Client alerts")
    return s


def open_opportunity(db: Session, actor: User, u: RegulatoryUpdate, org_id: str, service_kind: str, service: str | None = None):
    """"Create advisory opportunity": an S1 opportunity under the independence rule (§27.5)."""
    from app.sales.models import SERVICE_KINDS
    from app.sales.service import open_from_trigger

    if u.status != "published":
        raise Conflict("Publish the update first.")
    if service_kind not in SERVICE_KINDS:
        raise Invalid(errors=[{"field": "service_kind", "message": "Choose the kind of service."}])
    a = alert_for(db, u, org_id)
    o = open_from_trigger(db, org_id, "regulatory_update", u.id, service=(service or f"{u.law_name or 'Regulatory'} advisory: {u.title}")[:200], service_kind=service_kind,
                          why_now=f"{u.reference} {CHANGE_LABELS[u.change_type]}" + (f", effective {u.effective_on.day} {u.effective_on:%B %Y}" if u.effective_on else ""),
                          system_ids=list(a.affected_system_ids or []), created_by=actor.id)
    a.opportunity_id = o.id
    audit.record(db, actor_id=actor.id, action="regupdate.opportunity", obj=u, organization_id=org_id, after={"opportunity_id": o.id, "service_kind": service_kind},
                 summary=f"Opened an opportunity from {u.reference}")
    return o


def propose_law_change(db: Session, actor, u: RegulatoryUpdate, field_path: str, new_value, summary: str | None):
    """"Propose the law change": a published update that changes a law's facts goes to M3, so the law library stays
    the single source. The Chief Auditor approves it there (never the person who proposed it)."""
    from app.regmaster.changes import propose

    if u.status != "published":
        raise Conflict("Publish the update first.")
    if not u.regulation_id:
        raise Conflict("Link the update to a law in the law library first; a new law is proposed from the law library.")
    if u.change_type not in PC_TYPES:
        raise Conflict("A pending bill does not change the law library. Keep it as a watch item.")
    if not str(field_path or "").startswith(("law.", "requirement.", "role_map.", "scope_test.", "committee.")):
        raise Invalid(errors=[{"field": "field_path", "message": "Choose what changes in the law record."}])
    origin = "admin_edit" if actor.role_names & {"chief_auditor", "admin"} else "auditor_suggestion"
    pc = propose(db, actor_id=actor.id, regulation_id=u.regulation_id, field_path=field_path, new_value=new_value, summary=(summary or u.title), origin=origin,
                 change_type=PC_TYPES[u.change_type], reason=f"From regulatory update {u.reference}: {u.title}"[:1000], source_url=u.source_url,
                 source_quote=u.source_quote or u.summary)
    u.proposed_change_id = pc.id
    audit.record(db, actor_id=actor.id, action="regupdate.law_change", obj=u, organization_id=actor.organization.id, after={"proposed_change_id": pc.id, "field_path": field_path},
                 summary=f"Proposed the law change from {u.reference} for review in Refresh and review")
    return pc


# ---------------------------------------------------------------- deadline calendar
def calendar(db: Session, org_ids: list[str] | None, on: date | None = None, horizon_days: int = 730) -> list[dict]:
    """Upcoming effective and compliance dates per client: law versions in scope (M5) and published updates matched to
    the client. One row per law and date, with the clients it applies to."""
    from app.laws.models import Regulation
    from app.regmaster.models import ClientLawApplicability, LawVersion

    on = on or utcnow().date()
    until = on + timedelta(days=horizon_days)
    rows: dict[tuple, dict] = {}

    def add(key_law: str, d: date, label: str, org_id: str, source: str, ref: str | None):
        if not (on <= d <= until):
            return
        r = rows.setdefault((key_law, d, label), {"law": key_law, "date": d.isoformat(), "what": label, "source": source, "ref": ref, "organization_ids": []})
        if org_id not in r["organization_ids"]:
            r["organization_ids"].append(org_id)

    stmt = select(ClientLawApplicability, Regulation, LawVersion).join(Regulation, Regulation.id == ClientLawApplicability.regulation_id) \
        .join(LawVersion, LawVersion.id == ClientLawApplicability.law_version_id) \
        .where(ClientLawApplicability.in_scope.is_(True), ClientLawApplicability.deleted_at.is_(None))
    if org_ids is not None:
        stmt = stmt.where(ClientLawApplicability.organization_id.in_(org_ids))
    for cla, reg, v in db.execute(stmt).all():
        name = reg.short_name
        if v.compliance_on and v.compliance_on != v.effective_on:
            add(name, v.compliance_on, "Compliance date", cla.organization_id, "law_library", reg.id)
        if v.effective_on:
            add(name, v.effective_on, "Takes effect", cla.organization_id, "law_library", reg.id)
    ustmt = select(RegulatoryAlert, RegulatoryUpdate).join(RegulatoryUpdate, RegulatoryUpdate.id == RegulatoryAlert.update_id) \
        .where(RegulatoryUpdate.status == "published", RegulatoryUpdate.effective_on.is_not(None), RegulatoryAlert.deleted_at.is_(None))
    if org_ids is not None:
        ustmt = ustmt.where(RegulatoryAlert.organization_id.in_(org_ids))
    for a, u in db.execute(ustmt).all():
        add(u.law_name or u.title, u.effective_on, CHANGE_LABELS[u.change_type], a.organization_id, "update", u.id)
    return sorted(rows.values(), key=lambda r: (r["date"], r["law"]))


# ---------------------------------------------------------------- weekly digest
def digest_enabled(db: Session, org_id: str) -> bool:
    s = db.scalar(select(UpdateDigestSetting).where(UpdateDigestSetting.organization_id == org_id, UpdateDigestSetting.deleted_at.is_(None)))
    return bool(s and s.enabled)


def set_digest(db: Session, actor: User, org_id: str, enabled: bool) -> UpdateDigestSetting:
    s = db.scalar(select(UpdateDigestSetting).where(UpdateDigestSetting.organization_id == org_id))
    if s is None:
        s = UpdateDigestSetting(organization_id=org_id, created_by=actor.id)
        db.add(s)
    s.enabled, s.updated_by, s.deleted_at = bool(enabled), actor.id, None
    db.flush()
    audit.record(db, actor_id=actor.id, action="regupdate.digest_setting", obj=s, organization_id=org_id, after={"enabled": s.enabled},
                 summary=f"{'Turned on' if s.enabled else 'Turned off'} the weekly regulatory digest")
    return s


def _claim_week(db: Session, org_id: str, week_start: date) -> UpdateDigestRun | None:
    """The claim: insert this client's row for the week. A run that finds the row already there sends nothing."""
    try:
        with db.begin_nested():
            run = UpdateDigestRun(organization_id=org_id, week_start=week_start, status="sending", update_ids=[])
            db.add(run)
            db.flush()
        return run
    except IntegrityError:
        return None


def run_weekly_digest(db: Session, settings, now: datetime) -> int:
    """Daily job: once per week (Monday's week), email each client that has the digest turned on a list of the updates
    published for it since the last digest. Returns the number of digests sent."""
    from app.mail.service import send
    from app.impact.service import _with_role

    today = now.date() if isinstance(now, datetime) else now
    week_start = today - timedelta(days=today.weekday())
    sent = 0
    for s in db.scalars(select(UpdateDigestSetting).where(UpdateDigestSetting.enabled.is_(True), UpdateDigestSetting.deleted_at.is_(None))):
        if db.scalar(select(UpdateDigestRun.id).where(UpdateDigestRun.organization_id == s.organization_id, UpdateDigestRun.week_start == week_start)):
            continue
        run = _claim_week(db, s.organization_id, week_start)
        if run is None:
            continue
        pairs = db.execute(select(RegulatoryAlert, RegulatoryUpdate).join(RegulatoryUpdate, RegulatoryUpdate.id == RegulatoryAlert.update_id)
                           .where(RegulatoryAlert.organization_id == s.organization_id, RegulatoryAlert.digested_at.is_(None), RegulatoryAlert.deleted_at.is_(None),
                                  RegulatoryUpdate.status == "published").order_by(RegulatoryUpdate.published_at)).all()
        if not pairs:
            run.status = "nothing_new"
            continue
        people = _with_role(db, s.organization_id, "caico")
        if not people:
            run.status = "no_recipients"
            continue
        lines = [f"- {CHANGE_LABELS[u.change_type]}: {u.law_name + ': ' if u.law_name else ''}{u.title}" + (f" (from {u.effective_on.day} {u.effective_on:%B %Y})" if u.effective_on else "")
                 for _a, u in pairs]
        n = len(pairs)
        paragraphs = ["Hi there,", f"{n} regulatory {'update' if n == 1 else 'updates'} published by Futran this week concern your AI systems:", "\n".join(lines),
                      "Open the platform to see which systems are affected and what to do.", "[Link]",
                      "From Futran Solutions, your independent AI governance auditor. General information, not legal advice."]
        msg = send(db, settings, "client_alert", to=[p.email for p in people], organization_id=s.organization_id, related=run,
                   context={"subject": f"Weekly regulatory digest: {n} {'update' if n == 1 else 'updates'}", "paragraphs": paragraphs,
                            "link": f"{settings.base_url}/updates", "button": "See what this means for you"})
        for a, _u in pairs:
            a.digested_at = now
        run.status, run.sent_at, run.update_ids, run.recipient_count, run.outbox_message_id = "sent", now, [u.id for _a, u in pairs], len(people), msg.id
        sent += 1
    db.flush()
    return sent
