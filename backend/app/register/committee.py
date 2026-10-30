"""The AI Governance Committee and its members (spec §24.6, R5)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.register import service as svc
from app.register.models import COMMITTEE_ROLES, CommitteeMember, GovernanceCommittee, GovernanceRoleAssignment, RegisterSystem
from app.tenancy.models import Organization, RoleAssignment, User

COMMITTEE_ROLE_LABELS = {"chair": "Chair", "secretary": "Secretary", "legal": "Legal member", "technical": "Technical member", "business": "Business member",
                         "external_advisor_non_voting": "External advisor, non-voting"}
CADENCES = {"monthly": "Monthly", "quarterly": "Quarterly", "as_needed": "As needed"}
APPROVAL_SCOPES = {"tier3_and_exceptions": "Tier 3 systems and exceptions", "all_new_systems": "All new AI systems"}


def committee_for(db: Session, org: Organization, actor: User | None = None, *, create: bool = True) -> GovernanceCommittee | None:
    c = db.scalar(select(GovernanceCommittee).where(GovernanceCommittee.organization_id == org.id, GovernanceCommittee.deleted_at.is_(None)))
    if c is None and create:
        c = GovernanceCommittee(organization_id=org.id, status="not_formed", created_by=actor.id if actor else None)
        db.add(c)
        db.flush()
    return c


def members(db: Session, c: GovernanceCommittee) -> list[CommitteeMember]:
    return list(db.scalars(select(CommitteeMember).where(CommitteeMember.committee_id == c.id, CommitteeMember.deleted_at.is_(None)).order_by(CommitteeMember.created_at)))


def save_settings(db: Session, actor: User, c: GovernanceCommittee, data: dict) -> GovernanceCommittee:
    errs: list[dict] = []
    v: dict = {}
    if "target_date" in data:
        v["target_date"] = svc._date(data.get("target_date"), "target_date", errs)
    if "meeting_cadence" in data:
        v["meeting_cadence"] = svc._choice(data.get("meeting_cadence"), CADENCES, "meeting_cadence", "Choose how often it meets.", errs)
    if "approval_scope" in data:
        v["approval_scope"] = svc._choice(data.get("approval_scope"), APPROVAL_SCOPES, "approval_scope", "Choose what it approves.", errs)
    if "charter_note" in data:
        v["charter_note"] = svc._text(data.get("charter_note"), 300)
    if "charter_evidence_id" in data:
        v["charter_evidence_id"] = svc._file(db, c.organization_id, data.get("charter_evidence_id"), "charter_evidence_id", errs)
    if errs:
        raise Invalid(errors=errs)
    before = {k: getattr(c, k) for k in v}
    for k, val in v.items():
        setattr(c, k, val)
    c.updated_by = actor.id
    changed = {k: (str(before[k]) if before[k] is not None else None, str(getattr(c, k)) if getattr(c, k) is not None else None) for k in v if before[k] != getattr(c, k)}
    if changed:
        audit.record(db, actor_id=actor.id, action="committee.save", obj=c, before={k: o for k, (o, _) in changed.items()}, after={k: n for k, (_, n) in changed.items()},
                     summary="Saved the AI Governance Committee draft")
    return c


def _clean_member(db: Session, c: GovernanceCommittee, data: dict, current: CommitteeMember | None = None) -> dict:
    errs: list[dict] = []
    merged = ({"user_id": current.user_id, "external_party": current.external_party, "committee_role": current.committee_role, "covers_role_id": current.covers_role_id} if current else {}) | data
    uid = svc._user(db, c.organization_id, merged.get("user_id"), "user_id", errs)
    ext = svc._text(merged.get("external_party"), 200)
    if not uid and not ext and not errs:
        errs.append({"field": "user_id", "message": "Choose a person, or name the external party."})
    role = svc._choice(merged.get("committee_role"), COMMITTEE_ROLES, "committee_role", "Choose the committee role.", errs, required=True)
    covers = merged.get("covers_role_id") or None
    if covers and role == "external_advisor_non_voting":
        errs.append({"field": "covers_role_id", "message": "An external, non-voting advisor does not cover a governance role. This keeps audit independence."})
    if covers:
        from app.register.roles import catalog_role

        if catalog_role(db, covers) is None and not any(e["field"] == "covers_role_id" for e in errs):
            errs.append({"field": "covers_role_id", "message": "Choose a governance role."})
    if errs:
        raise Invalid(errors=errs)
    if uid:
        dup = [m for m in members(db, c) if m.user_id == uid and (current is None or m.id != current.id)]
        if dup:
            raise Conflict("This person is already on the committee.")
    if role == "chair" and any(m.committee_role == "chair" and (current is None or m.id != current.id) for m in members(db, c)):
        raise Conflict("The committee already has a chair.")
    return {"user_id": uid, "external_party": None if uid else ext, "committee_role": role, "covers_role_id": covers}


def add_member(db: Session, actor: User, c: GovernanceCommittee, data: dict) -> CommitteeMember:
    v = _clean_member(db, c, data)
    m = CommitteeMember(organization_id=c.organization_id, committee_id=c.id, created_by=actor.id, **v)
    db.add(m)
    db.flush()
    audit.record(db, actor_id=actor.id, action="committee.member_add", obj=c, after={"member": member_name(db, m), "role": m.committee_role}, summary=f"Added {member_name(db, m)} to the AI Governance Committee")
    return m


def update_member(db: Session, actor: User, c: GovernanceCommittee, m: CommitteeMember, data: dict) -> CommitteeMember:
    v = _clean_member(db, c, data, current=m)
    before = {k: getattr(m, k) for k in v}
    for k, val in v.items():
        setattr(m, k, val)
    m.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="committee.member_edit", obj=c, before=before, after=v, summary=f"Edited committee member {member_name(db, m)}")
    return m


def remove_member(db: Session, actor: User, c: GovernanceCommittee, m: CommitteeMember) -> None:
    m.deleted_at, m.updated_by = utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="committee.member_remove", obj=c, before={"member": member_name(db, m)}, summary=f"Removed {member_name(db, m)} from the AI Governance Committee")


def get_member(db: Session, c: GovernanceCommittee, member_id: str) -> CommitteeMember:
    m = db.get(CommitteeMember, member_id)
    if m is None or m.deleted_at is not None or m.committee_id != c.id:
        raise NotFound()
    return m


def member_name(db: Session, m: CommitteeMember) -> str:
    if m.user_id:
        u = db.get(User, m.user_id)
        return u.name if u else "Unknown"
    return f"{m.external_party} (external)"


def record_formed(db: Session, settings, actor: User, c: GovernanceCommittee, data: dict) -> GovernanceCommittee:
    if c.status == "formed":
        raise Conflict("The committee is already recorded as formed.")
    save_settings(db, actor, c, {k: data[k] for k in ("meeting_cadence", "approval_scope", "charter_note", "charter_evidence_id", "target_date") if k in data})
    errs: list[dict] = []
    formed_on = svc._date(data.get("formed_on"), "formed_on", errs)
    if formed_on is None and not errs:
        errs.append({"field": "formed_on", "message": "Enter the date the committee was formed."})
    if formed_on and formed_on > utcnow().date():
        errs.append({"field": "formed_on", "message": "The date formed cannot be in the future. Save a draft with a target date instead."})
    if not c.charter_evidence_id and not c.charter_note:
        errs.append({"field": "charter", "message": "Upload the charter or name the approved charter document."})
    ms = members(db, c)
    if not any(m.committee_role == "chair" for m in ms):
        errs.append({"field": "members", "message": "Add the committee members, including a chair."})
    if errs:
        raise Invalid(errors=errs)
    c.status, c.formed_on, c.recorded_by, c.updated_by = "formed", formed_on, actor.id, actor.id
    audit.record(db, actor_id=actor.id, action="committee.formed", obj=c, after={"formed_on": formed_on.isoformat(), "members": [member_name(db, m) for m in ms]},
                 summary="Recorded the AI Governance Committee as formed")
    _notify_pending(db, settings, actor, c)
    return c


def _notify_pending(db: Session, settings, actor: User, c: GovernanceCommittee) -> None:
    """Department Heads (and the AI Compliance Officers for company-wide roles) pick a member for each role marked "Pending committee"."""
    pending = list(db.scalars(select(GovernanceRoleAssignment).where(GovernanceRoleAssignment.organization_id == c.organization_id, GovernanceRoleAssignment.status == "pending_committee",
                                                                     GovernanceRoleAssignment.deleted_at.is_(None))))
    by_user: dict[str, int] = {}
    for a in pending:
        s = db.get(RegisterSystem, a.register_system_id) if a.register_system_id else None
        if s is not None and s.deleted_at is None and s.department_id and not s.company_wide:
            heads = db.scalars(select(RoleAssignment.user_id).where(RoleAssignment.role == "dept_compliance_lead", RoleAssignment.scope_type == "department",
                                                                    RoleAssignment.scope_id == s.department_id, RoleAssignment.deleted_at.is_(None)))
            targets = list(heads)
        else:
            targets = [u.id for u in svc.compliance_officers(db, c.organization_id)]
        for uid in targets:
            by_user[uid] = by_user.get(uid, 0) + 1
    from app.notifications.service import notify

    for uid, n in by_user.items():
        u = db.get(User, uid)
        if u is None:
            continue
        notify(db, [u], "register_committee_formed", "The AI Governance Committee is formed",
               f"{n} role{'s' if n != 1 else ''} marked Pending committee on your AI systems can now be given to a committee member.", "/register?roles=pending_committee", settings=settings)


def committee_out(db: Session, c: GovernanceCommittee) -> dict:
    rec = db.get(User, c.recorded_by) if c.recorded_by else None
    return {"id": c.id, "status": c.status, "target_date": c.target_date.isoformat() if c.target_date else None, "formed_on": c.formed_on.isoformat() if c.formed_on else None,
            "charter_evidence_id": c.charter_evidence_id, "charter_note": c.charter_note, "meeting_cadence": c.meeting_cadence, "approval_scope": c.approval_scope,
            "recorded_by": rec.name if rec else None}


def member_out(db: Session, m: CommitteeMember) -> dict:
    from app.register.roles import catalog_role
    from app.tenancy.models import Department

    u = db.get(User, m.user_id) if m.user_id else None
    dept = db.get(Department, u.department_id) if u and u.department_id else None
    cov = catalog_role(db, m.covers_role_id) if m.covers_role_id else None
    return {"id": m.id, "user_id": m.user_id, "name": member_name(db, m), "job_title": u.job_title if u else None, "external_party": m.external_party,
            "committee_role": m.committee_role, "committee_role_label": COMMITTEE_ROLE_LABELS.get(m.committee_role, m.committee_role),
            "covers_role_id": m.covers_role_id, "covers_role": cov["name"] if cov else None, "department": dept.name if dept else None}


def member_user_ids(db: Session, org_id: str) -> list[str]:
    """Platform users on the organization's committee. External members have no mailbox here and are left out."""
    c = db.scalar(select(GovernanceCommittee).where(GovernanceCommittee.organization_id == org_id, GovernanceCommittee.deleted_at.is_(None)))
    return [m.user_id for m in members(db, c) if m.user_id] if c is not None else []


def _register_mail_resolver() -> None:
    from app.mail.groups import COMMITTEE_RESOLVERS

    if member_user_ids not in COMMITTEE_RESOLVERS:
        COMMITTEE_RESOLVERS.append(member_user_ids)


_register_mail_resolver()
