"""What happened in each engagement stage, for the stage detail panel on the client page (Futran staff only).

A stage's time window runs from the audit log entry that moved the engagement into it to the one that moved it on.
"""
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit_log.models import AuditLog
from app.core.clock import utcnow
from app.engagements.gates import STAGE_NAMES, gate_status
from app.engagements.models import Engagement
from app.policy.roles import ROLE_LABELS
from app.signoffs.models import SIGN_OFF_TITLES, Signature, SignOff
from app.tenancy.models import Department, User

# What each stage is for, and what ends it (spec §7).
STAGE_INFO = {
    1: ("The Chief Auditor approves the draft and sends the initiation package. The client's Chief AI Compliance Officer accepts the invitation and signs the engagement letter.",
        "Sign-off 1: the client's Chief AI Compliance Officer and the Chief Auditor sign the engagement letter and scope."),
    2: ("The client sets up its departments and users, names its role holders and confirms the department list.",
        "The client confirms the department list and every department in scope has a Department Compliance Lead."),
    3: ("The client runs the staff AI use attestation, describes its AI governance structure and records its AI use cases.",
        "The attestation campaign is closed, the governance structure is submitted and no use case is left in draft."),
    4: ("The client reviews and signs its AI inventory: each department, the data categories and the management representation.",
        "Sign-off 2 for every department in scope, sign-off 3 and sign-off 4 are approved. The inventory snapshot is then locked."),
    5: ("Futran assesses each AI system in scope, requests evidence, scores the systems and records findings.",
        "Every Tier 3 use case maps to a system, every system is assessed and scored, and every finding is submitted."),
    6: ("The Chief Auditor reviews the findings and risk tiers, and Futran releases the draft report (v1.0) to the client.",
        "Sign-off 5 is approved and the client draft report (v1.0) is released."),
    7: ("The client responds to each finding and agrees a remediation plan. Futran reviews the responses.",
        "Sign-off 6: the client accepts the management responses and remediation plan."),
    8: ("Futran issues the final report (v1.1). The client acknowledges it and, where a law requires one, a public summary is approved.",
        "Sign-off 7 is approved, the client acknowledges the final report and, where required, sign-off 8 is approved."),
    9: ("The client completes the remediation items and Futran verifies and closes each one.",
        "Every remediation item is closed. The engagement is then completed."),
}
SIGNOFF_STAGE = {1: 1, 2: 4, 3: 4, 4: 4, 5: 6, 6: 7, 7: 8, 8: 8}
SIGNERS = {1: ("caico", "chief_auditor"), 2: ("dept_compliance_lead",), 3: ("dpo", "caico"), 4: ("dpo", "exec_sponsor"), 5: ("chief_auditor",), 6: ("caico", "exec_sponsor"), 7: ("chief_auditor",), 8: ("caico",)}
# Key events: milestones, approvals, invitations and documents sent. Working edits, file views and individual attestation answers are left out.
KEY_ACTIONS = (
    "engagement.", "package.", "signoff.", "invitation.", "department.confirm", "role_holder.", "attestation.launch", "attestation.close",
    "governance.request", "governance.setup", "governance.submit", "inventory.submit", "inventory.approve", "inventory.snapshot", "inventory.final_tier",
    "documents.issue", "documents.receive", "documents.not_available", "evidence_request.create", "system.addition", "prefill.submit",
    "finding.submit", "finding.approve", "finding.return", "finding.dismiss", "score.lock", "report.", "response.adequacy", "response.verify",
    "remediation.", "team.conflict_confirmed",
)
LINKS = {
    1: [],
    2: [("Departments", "/people/departments"), ("Users", "/people/users")],
    3: [("Employee attestation", "/attestation"), ("AI governance structure", "/governance"), ("AI inventory and tiers", "/inventory")],
    4: [("AI inventory and tiers", "/inventory")],
    5: [("AI systems in scope", "/systems"), ("Document requests", "/documents"), ("Findings", "/findings")],
    6: [("Findings", "/findings"), ("Report", "/report")],
    7: [("Responses", "/responses")],
    8: [("Report", "/report")],
    9: [("Remediation", "/remediation")],
}


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def stage_state(e: Engagement, n: int) -> str:
    if e.status in ("completed", "archived"):
        return "done"
    if e.status in ("draft", "pending_approval"):
        return "not_started"
    return "done" if n < e.stage else "current" if n == e.stage else "upcoming"


def windows(db: Session, e: Engagement) -> dict[int, tuple[datetime | None, datetime | None]]:
    """Start and end of each stage from the audit log: creation opens stage 1, each advance closes one and opens the next."""
    rows = list(db.scalars(select(AuditLog).where(AuditLog.engagement_id == e.id, AuditLog.action.in_(["engagement.create", "engagement.advance", "engagement.completed"])).order_by(AuditLog.at, AuditLog.id)))
    start: dict[int, datetime] = {1: next((a.at for a in rows if a.action == "engagement.create"), e.created_at)}
    end: dict[int, datetime] = {}
    for a in rows:
        if a.action == "engagement.advance":
            frm, to = (a.before or {}).get("stage"), (a.after or {}).get("stage")
            if isinstance(frm, int) and isinstance(to, int):
                end.setdefault(frm, a.at)
                start.setdefault(to, a.at)
        elif a.action == "engagement.completed":
            end.setdefault(9, a.at)
    return {n: (start.get(n), end.get(n)) for n in STAGE_NAMES}


def _signer_rows(db: Session, so: SignOff) -> list[dict]:
    sigs = {s.role: s for s in db.scalars(select(Signature).where(Signature.sign_off_id == so.id))}
    names = dict(db.execute(select(User.id, User.name).where(User.id.in_([s.user_id for s in sigs.values()]))).all()) if sigs else {}
    return [{"role": r, "role_label": ROLE_LABELS.get(r, r), "signed_by": names.get(sigs[r].user_id) if r in sigs else None,
             "signed_at": _iso(sigs[r].signed_at) if r in sigs else None} for r in so.required_approver_roles]


def _status_label(so: SignOff, replaced_by: int | None) -> str:
    if replaced_by:
        return f"Replaced by version {replaced_by}"
    if so.status == "approved":
        return "Approved"
    if so.status == "returned":
        return "Withdrawn" if (so.comment or "").startswith("Withdrawn by the preparer") else "Returned"
    return "Waiting for signatures"


def sign_offs_in(db: Session, e: Engagement, n: int) -> list[dict]:
    numbers = [k for k, v in SIGNOFF_STAGE.items() if v == n]
    if not numbers:
        return []
    rows = list(db.scalars(select(SignOff).where(SignOff.engagement_id == e.id, SignOff.number.in_(numbers), SignOff.deleted_at.is_(None)).order_by(SignOff.number, SignOff.scope_ref, SignOff.version)))
    replaced = {so.supersedes_id: so.version for so in rows if so.supersedes_id}
    depts = dict(db.execute(select(Department.id, Department.name).where(Department.id.in_([so.scope_ref for so in rows if so.scope_ref]))).tuples().all()) if rows else {}
    people = dict(db.execute(select(User.id, User.name).where(User.id.in_([so.preparer_id for so in rows if so.preparer_id]))).tuples().all()) if rows else {}
    out = []
    for so in rows:
        out.append({
            "id": so.id, "number": so.number, "title": so.title, "scope_label": depts.get(so.scope_ref) if so.scope_ref else None, "version": so.version,
            "status": so.status, "status_label": _status_label(so, replaced.get(so.id)), "preparer": people.get(so.preparer_id),
            "sent_at": _iso(so.created_at), "approved_at": _iso(so.approved_at), "signers": _signer_rows(db, so),
            "reason": so.comment if so.status == "returned" else None, "correction_reason": so.correction_reason,
        })
    return out


def events_in(db: Session, e: Engagement, start: datetime | None, end: datetime | None, limit: int = 150) -> list[dict]:
    if start is None:
        return []
    stmt = select(AuditLog).where(
        AuditLog.organization_id == e.client_id,
        or_(AuditLog.engagement_id == e.id, AuditLog.engagement_id.is_(None)),
        or_(*[AuditLog.action.startswith(p) for p in KEY_ACTIONS]),
        AuditLog.at >= start,
    )
    if end is not None:
        stmt = stmt.where(AuditLog.at <= end)
    return [{"at": _iso(a.at), "actor": a.actor_name or "System", "action": a.action, "summary": a.summary} for a in db.scalars(stmt.order_by(AuditLog.at, AuditLog.id).limit(limit))]


def stage_detail(db: Session, e: Engagement, n: int) -> dict:
    state = stage_state(e, n)
    start, end = windows(db, e)[n]
    if state in ("upcoming", "not_started") and n != 1:
        start = end = None
    summary, exit_text = STAGE_INFO[n]
    open_items = gate_status(db, e).unmet if state == "current" or (state == "not_started" and n == 1) else []
    expected = [{"number": k, "title": SIGN_OFF_TITLES[k], "signers": [ROLE_LABELS.get(r, r) for r in SIGNERS[k]]} for k, v in SIGNOFF_STAGE.items() if v == n]
    base = f"/clients/{e.client_id}"
    return {
        "number": n, "name": STAGE_NAMES[n], "state": state, "summary": summary, "exit": exit_text,
        "entered_at": _iso(start) if state != "not_started" else None, "exited_at": _iso(end) if state == "done" else None,
        "sign_offs": sign_offs_in(db, e, n) if state != "upcoming" else [],
        "expected_sign_offs": expected,
        "events": events_in(db, e, start, end if state == "done" else None) if state in ("done", "current") or n == 1 else [],
        "open": open_items,
        "links": [{"label": label, "to": base + path} for label, path in LINKS[n] if path] or [{"label": "Client overview", "to": base}],
        "as_of": _iso(utcnow()),
    }
