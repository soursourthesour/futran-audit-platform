"""Role home screens (spec §13.1). One thin read endpoint per home, each behind its own action, built from the data the
role's existing screens already show. The QA Reviewer also approves or returns the Chief Auditor's rating overrides here."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.audit_log.models import AuditLog
from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.engagements.gates import STAGE_NAMES
from app.engagements.models import Engagement, EngagementTeam
from app.findings.models import Finding
from app.inventory.models import AITool, UseCase
from app.policy.actions import Action
from app.policy.authorize import assigned_engagement_ids, authorize, departments_for
from app.policy.matrix import MATRIX, Scope
from app.policy.roles import CLIENT_ROLES, ROLE_LABELS, SIGN_OFF_ROLES, Role
from app.tenancy.models import Department, Organization, RoleAssignment, User
from app.tenancy.people import current_engagement

router = APIRouter(tags=["homes"])

DATA_LABELS = {"pii": "Personal data", "phi": "Health data", "client": "Client confidential", "confidential": "Company confidential", "none": "No sensitive data"}
ACCOUNT_LABELS = {"enterprise": "Company", "team": "Company (team)", "personal_paid": "Personal paid", "personal_free": "Personal free", "unknown": "Not known"}
UC_STATUS = {"draft": "Draft", "submitted": "Submitted", "dept_approved": "Approved", "returned": "Returned"}


def _eng_out(e: Engagement) -> dict:
    from app.engagements.client_router import stage_label, status_label
    from app.initiation.context import TYPE_LABELS

    return {"id": e.id, "audit_ref": e.audit_ref, "name": e.name, "type_label": TYPE_LABELS.get(e.type, e.type), "stage": e.stage,
            "stage_name": STAGE_NAMES.get(e.stage, ""), "stage_label": stage_label(e), "status": e.status, "status_label": status_label(e)}


def _names(db: Session, ids) -> dict[str, str]:
    ids = {i for i in ids if i}
    return dict(db.execute(select(User.id, User.name).where(User.id.in_(ids))).all()) if ids else {}


def _client_org(db: Session, actor: Actor, action: Action) -> Organization:
    if actor.is_futran:
        raise NotFound()
    authorize(db, actor, action, org_id=actor.organization.id, list_view=True)
    return db.get(Organization, actor.organization.id)


# ---- Futran Admin console
@router.get("/home/admin")
def admin_home(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Platform setup at a glance: Futran users, client organizations, the law matrix and templates."""
    authorize(db, actor, Action.VIEW_ADMIN_HOME)
    from app.laws.models import MatrixVersion
    from app.laws.publish import current_regulations
    from app.reference.models import DocumentTemplate
    from app.regmaster.models import ProposedChange

    staff = list(db.scalars(select(User).where(User.organization_id == actor.organization.id, User.deleted_at.is_(None), User.status != "disabled")))
    roles = db.execute(select(RoleAssignment.role, func.count(func.distinct(RoleAssignment.user_id))).where(
        RoleAssignment.user_id.in_([u.id for u in staff]), RoleAssignment.deleted_at.is_(None)).group_by(RoleAssignment.role)).all()
    clients = list(db.scalars(select(Organization).where(Organization.type == "client", Organization.deleted_at.is_(None))))
    engs = list(db.scalars(select(Engagement).where(Engagement.deleted_at.is_(None))))
    mv = db.scalar(select(MatrixVersion).where(MatrixVersion.status == "published").order_by(MatrixVersion.published_at.desc()).limit(1))
    regs = current_regulations(db)
    return {
        "users": {"total": len(staff), "active": sum(u.status == "active" for u in staff), "invited": sum(u.status == "invited" for u in staff),
                  "mfa": sum(bool(u.mfa_enabled) for u in staff if u.status == "active"), "by_role": {r: n for r, n in roles}},
        "clients": {"total": len(clients), "drafts": sum(e.status in ("draft", "pending_approval") for e in engs),
                    "in_progress": sum(e.status in ("initiated", "in_progress") for e in engs), "completed": sum(e.status in ("completed", "archived") for e in engs)},
        "law_matrix": {"label": mv.label if mv else None, "status_date": mv.status_date.isoformat() if mv and mv.status_date else None,
                       "published_at": mv.published_at.isoformat() if mv else None, "laws": len(regs),
                       "jurisdictions": len({r.jurisdiction_id for r in regs if getattr(r, "jurisdiction_id", None)})},
        "templates": db.scalar(select(func.count(DocumentTemplate.id)).where(DocumentTemplate.active.is_(True))) or 0,
        "pending_proposals": db.scalar(select(func.count(ProposedChange.id)).where(ProposedChange.status.in_(("pending", "held", "legal_review")))) or 0,
    }


# ---- Auditor: My work
def _my_engagements(db: Session, actor: Actor) -> list[Engagement]:
    ids = assigned_engagement_ids(db, actor.id)
    return list(db.scalars(select(Engagement).where(Engagement.deleted_at.is_(None), or_(Engagement.id.in_(ids), (Engagement.created_by == actor.id) & Engagement.status.in_(("draft", "pending_approval")))).order_by(Engagement.updated_at.desc())))


@router.get("/home/my-work")
def my_work(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """The engagements this person is assigned to or drafted, and what needs doing on them today."""
    authorize(db, actor, Action.VIEW_MY_WORK, list_view=True)
    from app.docrequests.models import DocumentRequest, EvidenceRequest
    from app.remediation.models import ManagementResponse, RemediationItem
    from app.systems.service import systems_for

    engs = _my_engagements(db, actor)
    orgs = {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_([e.client_id for e in engs])))} if engs else {}
    team = dict(db.execute(select(EngagementTeam.engagement_id, EngagementTeam.role).where(EngagementTeam.user_id == actor.id, EngagementTeam.deleted_at.is_(None))).all())
    today = date.today()
    rows, tasks = [], []

    def task(kind: str, e: Engagement, title: str, detail: str, link: str, *, overdue: bool = False, due: date | None = None):
        tasks.append({"kind": kind, "client": orgs.get(e.client_id), "client_id": e.client_id, "title": title, "detail": detail, "link": link, "overdue": overdue,
                      "due": due.isoformat() if due else None})

    for e in engs:
        base = f"/clients/{e.client_id}"
        draft = e.status in ("draft", "pending_approval")
        systems = [] if draft else systems_for(db, e)
        assessed = sum(s.status in ("scored", "locked") for s in systems)
        rows.append({**_eng_out(e), "client": orgs.get(e.client_id), "client_id": e.client_id, "my_role": ROLE_LABELS.get(team.get(e.id, ""), None),
                     "systems": len(systems), "systems_assessed": assessed,
                     "link": f"{base}/setup/company" if e.status == "draft" else f"{base}/setup/submit" if e.status == "pending_approval" else base})
        if draft:
            continue
        for f in db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None), Finding.author_id == actor.id, Finding.status.in_(("returned", "draft"))).order_by(Finding.ref)):
            if f.status == "returned":
                task("finding_returned", e, f"Finding {f.ref} returned", f"{f.title}. {f.review_comment or ''}".strip(), f"{base}/findings")
            else:
                task("finding_draft", e, f"Finding {f.ref} is still a draft", f.title, f"{base}/findings")
        for r in db.scalars(select(EvidenceRequest).where(EvidenceRequest.engagement_id == e.id, EvidenceRequest.deleted_at.is_(None), EvidenceRequest.requested_by == actor.id,
                                                          EvidenceRequest.status == "outstanding", EvidenceRequest.due_date < today).order_by(EvidenceRequest.due_date)):
            link = f"{base}/fieldwork/{r.use_case_id}" if r.use_case_id else f"{base}/documents"
            task("evidence_overdue", e, f"Evidence request {r.ref} is overdue", r.description, link, overdue=True, due=r.due_date)
        late_docs = db.scalar(select(func.count(DocumentRequest.id)).where(DocumentRequest.engagement_id == e.id, DocumentRequest.deleted_at.is_(None), DocumentRequest.status == "pending", DocumentRequest.due_at < today)) or 0
        if late_docs:
            task("documents_overdue", e, f"{late_docs} requested document{'s' if late_docs != 1 else ''} past due", "Chase the client or mark them not available.", f"{base}/documents", overdue=True)
        if e.stage == 5:
            open_sys = len(systems) - assessed
            if open_sys:
                task("systems_open", e, f"{open_sys} AI system{'s' if open_sys != 1 else ''} not yet scored", "Verify the answers and set the final domain scores.", f"{base}/systems")
            no_tier = db.scalar(select(func.count(UseCase.id)).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None), UseCase.status == "dept_approved", UseCase.final_tier.is_(None))) or 0
            if no_tier:
                task("tiers_open", e, f"{no_tier} use case{'s' if no_tier != 1 else ''} without a final tier", "Set the final tier and rationale on each.", f"{base}/inventory")
        if e.stage == 7:
            waiting = db.scalar(select(func.count(ManagementResponse.id)).where(ManagementResponse.engagement_id == e.id, ManagementResponse.deleted_at.is_(None), ManagementResponse.status == "answered")) or 0
            if waiting:
                task("responses_review", e, f"{waiting} management response{'s' if waiting != 1 else ''} to review", "Mark each response adequate or not adequate.", f"{base}/responses")
        verify = db.scalar(select(func.count(RemediationItem.id)).where(RemediationItem.engagement_id == e.id, RemediationItem.deleted_at.is_(None), RemediationItem.status == "awaiting_verification", RemediationItem.verified_by.is_(None))) or 0
        if verify:
            task("remediation_verify", e, f"{verify} remediation item{'s' if verify != 1 else ''} awaiting verification", "The client marked these done.", f"{base}/remediation")
    tasks.sort(key=lambda t: (not t["overdue"], t["due"] or "9999"))
    return {"engagements": rows, "tasks": tasks}


# ---- QA Reviewer: queue of Chief-Auditor-authored findings and rating overrides
def _qa_engagements(db: Session, actor: Actor) -> list[Engagement]:
    ids = set(db.scalars(select(EngagementTeam.engagement_id).where(EngagementTeam.user_id == actor.id, EngagementTeam.role == "qa_reviewer", EngagementTeam.deleted_at.is_(None))))
    return list(db.scalars(select(Engagement).where(Engagement.id.in_(ids), Engagement.deleted_at.is_(None)))) if ids else []


def _override_key(row) -> dict:
    return {"rating": row.override_rating, "rationale": row.override_rationale, "override_by": row.override_by}


def _override_reviewed(db: Session, system_id: str, row) -> bool:
    """A rating override is reviewed once a QA decision is recorded for this exact rating, rationale and author."""
    last = db.scalar(select(AuditLog).where(AuditLog.object_id == system_id, AuditLog.action.in_(("score.override_approve", "score.override_return"))).order_by(AuditLog.at.desc()).limit(1))
    if last is None or not last.after:
        return False
    return all(last.after.get(k) == v for k, v in _override_key(row).items())


def pending_overrides(db: Session, engagements: list[Engagement]) -> list[tuple[Engagement, object, object]]:
    from app.scoring.service import latest
    from app.systems.service import systems_for

    out = []
    for e in engagements:
        for s in systems_for(db, e):
            row = latest(db, s)
            if row is not None and row.override_rating and s.status != "locked" and not _override_reviewed(db, s.id, row):
                out.append((e, s, row))
    return out


@router.get("/home/qa")
def qa_queue(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize(db, actor, Action.VIEW_QA_QUEUE, list_view=True)
    engs = _qa_engagements(db, actor)
    orgs = {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_([e.client_id for e in engs])))} if engs else {}
    now = utcnow()
    fs = list(db.scalars(select(Finding).where(Finding.engagement_id.in_([e.id for e in engs]), Finding.deleted_at.is_(None), Finding.status == "submitted",
                                               Finding.review_role == "qa_reviewer").order_by(Finding.submitted_at))) if engs else []
    by_id = {e.id: e for e in engs}
    ovs = pending_overrides(db, engs)
    names = _names(db, [f.author_id for f in fs] + [r.override_by for _, _, r in ovs])
    findings = [{"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "description": f.description, "control_refs": f.control_refs or [],
                 "client": orgs.get(by_id[f.engagement_id].client_id), "client_id": by_id[f.engagement_id].client_id, "audit_ref": by_id[f.engagement_id].audit_ref,
                 "author": names.get(f.author_id), "submitted_at": f.submitted_at.isoformat() if f.submitted_at else None,
                 "waiting_days": (now - f.submitted_at).days if f.submitted_at else None, "can_review": actor.id not in {f.author_id, f.submitted_by, *(f.editor_ids or [])},
                 "link": f"/clients/{by_id[f.engagement_id].client_id}/findings"} for f in fs]
    overrides = [{"system_id": s.id, "reference_id": s.reference_id, "system": s.name, "client": orgs.get(e.client_id), "client_id": e.client_id, "audit_ref": e.audit_ref,
                  "rating": r.override_rating, "computed_rating": r.computed_rating, "rationale": r.override_rationale, "by": names.get(r.override_by),
                  "at": r.created_at.isoformat() if r.created_at else None, "waiting_days": (now - r.created_at).days if r.created_at else None,
                  "can_review": r.override_by != actor.id, "link": f"/systems/{s.id}/score"} for e, s, r in ovs]
    done = list(db.scalars(select(AuditLog).where(AuditLog.actor_id == actor.id, AuditLog.action.in_(("finding.approve", "finding.return", "score.override_approve", "score.override_return")))
                           .order_by(AuditLog.at.desc()).limit(20)))
    reviewed = [{"kind": "finding" if a.action.startswith("finding") else "override", "decision": "approved" if a.action.endswith("approve") else "returned",
                 "summary": a.summary, "at": a.at.isoformat()} for a in done]
    return {"findings": findings, "overrides": overrides, "reviewed": reviewed}


class OverrideReviewIn(BaseModel):
    decision: str
    comment: str | None = None


@router.post("/systems/{system_id}/score/override/review")
def review_override(system_id: str, body: OverrideReviewIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """The QA Reviewer approves or returns a rating override the Chief Auditor (the engagement's Lead Auditor) made, so
    no one approves their own judgment (spec §6 rule 2). The decision is kept in the audit log; returning notifies the
    Chief Auditor, and a changed override comes back to the queue."""
    from app.findings.service import team_role_holders
    from app.notifications.service import notify
    from app.scoring.service import latest
    from app.systems.service import get_system

    s = get_system(db, system_id)
    e = authorize(db, actor, Action.REVIEW_SCORE_OVERRIDE, engagement_id=s.engagement_id)
    if actor.id not in {u.id for u in team_role_holders(db, e, "qa_reviewer")}:
        raise Forbidden("Only the engagement's QA Reviewer reviews rating overrides.")
    if body.decision not in ("approve", "return"):
        raise Invalid(errors=[{"field": "decision", "message": "Choose approve or return."}])
    row = latest(db, s)
    if row is None or not row.override_rating or s.status == "locked" or _override_reviewed(db, s.id, row):
        raise Conflict("There is no rating override waiting for review on this system.")
    if row.override_by == actor.id:
        raise Forbidden("You made this override, so you cannot review it.")
    comment = " ".join(str(body.comment or "").split()) or None
    if body.decision == "return" and not comment:
        raise Invalid(errors=[{"field": "comment", "message": "Say what the Chief Auditor needs to change."}])
    verb = "Approved" if body.decision == "approve" else "Returned"
    audit.record(db, actor_id=actor.id, action=f"score.override_{body.decision}", obj=s, request=request, after={**_override_key(row), "comment": comment},
                 summary=f"{verb} the rating override for {s.reference_id} ({row.override_rating})")
    if body.decision == "return":
        notify(db, [db.get(User, row.override_by)] if row.override_by else [], "override_returned", f"{e.audit_ref}: rating override for {s.reference_id} was returned",
               comment, f"/systems/{s.id}/score", engagement=e, settings=request.app.state.settings)
    return {"ok": True, "decision": body.decision}


# ---- Client Admin home
@router.get("/home/client-admin")
def client_admin_home(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Who can sign in and how: users and invitations, departments and their leads, the email connection, SSO status and
    the role-change log. No audit content."""
    org = _client_org(db, actor, Action.VIEW_CLIENT_ADMIN_HOME)
    from app.invitations.models import Invitation
    from app.mail.onboarding import getting_started_items
    from app.tenancy.people import departments

    users = list(db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None))))
    by_id = {u.id: u for u in users}
    roles = list(db.scalars(select(RoleAssignment).where(RoleAssignment.user_id.in_(list(by_id)), RoleAssignment.deleted_at.is_(None))))
    soon = utcnow() + timedelta(days=2)
    invites = list(db.scalars(select(Invitation).where(Invitation.user_id.in_(list(by_id)), Invitation.status == "pending", Invitation.deleted_at.is_(None)).order_by(Invitation.expires_at)))
    expiring = [{"user": by_id[i.user_id].name, "roles": [ROLE_LABELS.get(r.role, r.role) for r in roles if r.user_id == i.user_id], "expires_at": i.expires_at.isoformat()}
                for i in invites if i.expires_at <= soon and by_id[i.user_id].status == "invited"]
    depts = departments(db, org)
    leads = {r.scope_id for r in roles if r.role == "dept_compliance_lead" and r.scope_type == "department"}
    items = [{"id": d.id, "name": d.name, "has_lead": d.id in leads, "in_scope": d.in_scope} for d in depts]
    without = [x for x in items if not x["has_lead"] and x["in_scope"]]
    e = current_engagement(db, org)
    email = (getting_started_items(db, actor) or [{"status": "Not started", "done": False, "link": "/admin/email"}])[0]
    logs = list(db.scalars(select(AuditLog).where(AuditLog.organization_id == org.id, AuditLog.action.in_(("role.assign", "role.remove", "role_holder.not_appointed")))
                           .order_by(AuditLog.at.desc()).limit(25)))
    changes = [{"summary": a.summary, "by": a.actor_name, "at": a.at.isoformat(),
                "sign_off_role": ((a.after or {}).get("role") or (a.before or {}).get("role")) in {str(r) for r in SIGN_OFF_ROLES}} for a in logs]
    todos = [{"kind": "assign_lead", "text": f"Assign a Department Compliance Lead for {d['name']}", "link": "/people/departments"} for d in without]
    for x in expiring:
        who = f"{x['user']} ({', '.join(x['roles'])})" if x["roles"] else x["user"]
        todos.append({"kind": "resend", "text": f"Resend the invitation to {who}; it expires soon", "link": "/people/users"})
    if not email.get("done"):
        todos.append({"kind": "connect_email", "text": "Connect your email system so requests go out from your own domain", "link": "/admin/email"})
    return {
        "organization": org.name,
        "engagement": _eng_out(e) if e else None,
        "users": {"total": len(users), "active": sum(u.status == "active" for u in users), "invited": sum(u.status == "invited" for u in users),
                  "disabled": sum(u.status == "disabled" for u in users)},
        "invitations": {"pending": sum(by_id[i.user_id].status == "invited" for i in invites), "expiring": expiring},
        "departments": {"total": len(items), "items": items, "without_lead": without, "blocks_stage": 2 if e is not None and e.stage == 2 and without else None},
        "email": {"status": email.get("status"), "done": bool(email.get("done")), "link": "/admin/email"},
        "sso": {"available": False},
        "role_changes": changes,
        "todos": todos,
    }


# ---- Executive Sponsor
@router.get("/home/sponsor")
def sponsor_home(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """The engagement summary and the sign-offs the Executive Sponsor approves (4 and 6)."""
    org = _client_org(db, actor, Action.VIEW_SPONSOR_HOME)
    from app.remediation.service import approved_findings
    from app.scoring.models import EngagementScorecard
    from app.signoffs.service import current, sign_off_out
    from app.systems.service import systems_for

    e = current_engagement(db, org)
    if e is None:
        return {"organization": org.name, "engagement": None, "signoffs": {}, "waiting": [], "findings": None, "rating": None, "systems": 0, "use_cases": 0}
    authorize(db, actor, Action.VIEW_SPONSOR_HOME, engagement_id=e.id)
    links = {4: "/review", 6: "/responses"}
    signoffs = {}
    for n in (4, 6):
        so = current(db, e, n)
        signoffs[str(n)] = {"sign_off": sign_off_out(db, actor, so) if so else None, "link": links[n]}
    waiting = [int(n) for n, b in signoffs.items() if b["sign_off"] and b["sign_off"]["can_sign"]]
    shared = e.stage >= 7
    findings = None
    if shared:
        fs = approved_findings(db, e)
        findings = {"total": len(fs), "by_severity": {sev: sum(f.severity == sev for f in fs) for sev in ("critical", "high", "medium", "low", "observation")}}
    sc = db.scalar(select(EngagementScorecard).where(EngagementScorecard.engagement_id == e.id)) if shared else None
    return {
        "organization": org.name, "engagement": _eng_out(e), "signoffs": signoffs, "waiting": waiting, "findings": findings,
        "rating": {"overall": sc.overall_rating, "maturity": sc.overall_maturity, "narrative": sc.narrative} if sc else None,
        "systems": len(systems_for(db, e)),
        "use_cases": db.scalar(select(func.count(UseCase.id)).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None), UseCase.status != "draft")) or 0,
        "final_report_released": e.stage >= 8,
    }


# ---- Data Protection Officer
def _individual_viewers() -> list[str]:
    return [ROLE_LABELS[str(r)] for r in Role if r in CLIENT_ROLES and MATRIX.get(r, {}).get(Action.VIEW_INDIVIDUAL_ATTESTATIONS, Scope.NONE) != Scope.NONE]


@router.get("/home/dpo")
def dpo_home(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Sign-off 3 (data categories for Tier 2 and 3 use cases) and how attestation answers are protected."""
    org = _client_org(db, actor, Action.VIEW_DPO_HOME)
    from app.attestation import service as att
    from app.signoffs import client_review
    from app.signoffs.service import current, sign_off_out

    privacy = {"min_group": att.MIN_AGGREGATE, "individuals_visible_to": _individual_viewers() + ["Assigned Futran auditors"]}
    e = current_engagement(db, org)
    if e is None:
        return {"organization": org.name, "engagement": None, "signoff3": None, "use_cases": [], "privacy": privacy, "campaign": None}
    authorize(db, actor, Action.VIEW_DPO_HOME, engagement_id=e.id)
    so = current(db, e, 3)
    unmet = client_review.signoff3_unmet(db, e) if e.stage == 4 else []
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org.id))}
    ucs = [u for u in db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None), UseCase.status != "draft").order_by(UseCase.name))
           if (u.final_tier or u.proposed_tier or 0) >= 2]
    tools = {t.id: t for t in db.scalars(select(AITool).where(AITool.id.in_([t for u in ucs for t in (u.tool_ids or [])])))} if ucs else {}
    rows = [{"id": u.id, "name": u.name, "department": depts.get(u.department_id), "tier": u.final_tier or u.proposed_tier, "data": u.data_categories or [],
             "data_labels": [DATA_LABELS.get(c, c) for c in u.data_categories or []],
             "accounts": sorted({ACCOUNT_LABELS.get(tools[t].account_type, tools[t].account_type) for t in u.tool_ids or [] if t in tools}),
             "personal_account": any(tools[t].account_type.startswith("personal") for t in u.tool_ids or [] if t in tools),
             "status": u.status, "status_label": UC_STATUS.get(u.status, u.status), "link": f"/inventory/{u.id}"} for u in ucs]
    rows.sort(key=lambda r: (-(r["tier"] or 0), r["name"]))
    c = att.current_campaign(db, e)
    campaign = {"status": "open" if att.is_open(c) else "closed", "closes_at": c.closes_at.isoformat(), "responses": len(att.current_answers(db, c.id))} if c else None
    privacy["notice_acknowledged"] = att.notice_acknowledged(db, e)
    return {"organization": org.name, "engagement": _eng_out(e), "signoff3": {"sign_off": sign_off_out(db, actor, so) if so else None, "unmet": unmet, "link": "/review"},
            "use_cases": rows, "privacy": privacy, "campaign": campaign}


# ---- Department Compliance Lead
@router.get("/home/department")
def department_home(department_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """Everything here is limited to the lead's own departments: approvals, attestation totals, findings and the register."""
    if actor.is_futran:
        raise NotFound()
    org = db.get(Organization, actor.organization.id)
    if department_id is not None:
        authorize(db, actor, Action.VIEW_DEPARTMENT_HOME, org_id=org.id, department_id=department_id)
        ids = {department_id}
    else:
        authorize(db, actor, Action.VIEW_DEPARTMENT_HOME, org_id=org.id, list_view=True)
        ids = departments_for(actor, Action.VIEW_DEPARTMENT_HOME) or set()
    from app.attestation import service as att
    from app.register.models import RegisterSystem
    from app.remediation import service as rem
    from app.signoffs import client_review
    from app.signoffs.service import current, sign_off_out

    depts = list(db.scalars(select(Department).where(Department.id.in_(ids), Department.organization_id == org.id, Department.deleted_at.is_(None)).order_by(Department.name)))
    e = current_engagement(db, org)
    c = att.current_campaign(db, e) if e else None
    shared = e is not None and e.stage >= 7
    approved = rem.approved_findings(db, e) if shared else []
    out = []
    for d in depts:
        ucs = list(db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.department_id == d.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name))) if e else []
        names = _names(db, [u.submitted_by or u.created_by for u in ucs])
        tiers = {t: sum((u.final_tier or u.proposed_tier) == t for u in ucs if u.status != "draft") for t in (1, 2, 3)}
        so = current(db, e, 2, d.id) if e else None
        att_out = None
        if c is not None and d.id in (c.department_ids or []):
            tr = att.tracker(db, actor, c, dept_scope={d.id}, individuals=False)
            row = tr["departments"][0] if tr["departments"] else {}
            att_out = {"responses": row.get("responses"), "headcount": row.get("headcount"), "status": tr["campaign"]["status"], "min_group": att.MIN_AGGREGATE}
        findings = None
        if shared:
            findings = []
            for f in approved:
                if rem.finding_department(db, f) != d.id:
                    continue
                r = rem.response_out(db, f, rem.response_for(db, f))
                findings.append({"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "response_status": r["status"], "due_date": r["due_date"], "link": "/responses"})
        reg = list(db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.department_id == d.id, RegisterSystem.deleted_at.is_(None)).order_by(RegisterSystem.reference)))
        out.append({
            "id": d.id, "name": d.name,
            "use_cases": [{"id": u.id, "name": u.name, "status": u.status, "status_label": UC_STATUS.get(u.status, u.status), "tier": u.final_tier or u.proposed_tier,
                           "by": names.get(u.submitted_by or u.created_by), "link": f"/inventory/{u.id}"} for u in ucs],
            "tiers": tiers, "awaiting_approval": sum(u.status == "submitted" for u in ucs),
            "signoff2": {"sign_off": sign_off_out(db, actor, so) if so else None, "unmet": client_review.department_unmet(db, e, d.id) if e and e.stage == 4 else [], "link": "/review"},
            "attestation": att_out or {"responses": None, "headcount": d.headcount, "status": None, "min_group": att.MIN_AGGREGATE},
            "findings": findings,
            "register": {"total": len(reg), "live": sum(s.stage == "live" for s in reg),
                         "items": [{"id": s.id, "reference": s.reference, "name": s.name, "stage": s.stage, "link": f"/register/{s.id}"} for s in reg[:8]]},
        })
    return {"organization": org.name, "engagement": _eng_out(e) if e else None, "departments": out, "findings_shared": shared}


# ---- Contributor
@router.get("/home/my-tasks")
def my_tasks(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    """What the contributor needs to do: returned items, evidence and document requests, drafts; and what they submitted."""
    org = _client_org(db, actor, Action.VIEW_MY_TASKS)
    from app.docrequests.router import mine as my_documents
    from app.docrequests.router import my_evidence_requests

    depts = departments_for(actor, Action.VIEW_MY_TASKS) or set()
    e = current_engagement(db, org)
    if e is None:
        return {"organization": org.name, "engagement": None, "returned": [], "drafts": [], "evidence": [], "documents": [], "entries": []}
    authorize(db, actor, Action.VIEW_MY_TASKS, engagement_id=e.id, list_view=True)
    ucs = list(db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None), UseCase.department_id.in_(depts)).order_by(UseCase.name))) if depts else []
    mine = [u for u in ucs if actor.id in {u.created_by, u.submitted_by, *(u.editor_ids or [])}]
    dnames = {d.id: d.name for d in db.scalars(select(Department).where(Department.id.in_(depts)))} if depts else {}

    def uc(u: UseCase) -> dict:
        return {"id": u.id, "name": u.name, "status": u.status, "status_label": UC_STATUS.get(u.status, u.status), "tier": u.final_tier or u.proposed_tier,
                "department": dnames.get(u.department_id), "comment": u.returned_comment, "from_attestation": bool(u.created_from_attestation_id), "link": f"/inventory/{u.id}"}

    drafts = [uc(u) for u in ucs if u.status == "draft" and (u in mine or u.created_from_attestation_id)]
    try:
        docs = [r for r in my_documents(actor, db)["requests"] if r.get("status") == "pending"]
    except (Forbidden, NotFound):
        docs = []
    evidence = [r for r in my_evidence_requests(actor, db)["requests"] if r.get("status") == "outstanding"]
    return {"organization": org.name, "engagement": _eng_out(e), "returned": [uc(u) for u in mine if u.status == "returned"], "drafts": drafts,
            "evidence": evidence, "documents": docs, "entries": [uc(u) for u in mine]}
