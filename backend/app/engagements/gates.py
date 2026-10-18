"""Stage exit gates (spec §7). Each stage registers a check returning what is still missing."""
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today
from app.core.errors import Conflict
from app.engagements.models import Engagement
from app.tenancy.models import Department, RoleAssignment, User

STAGE_NAMES = {1: "Onboarding", 2: "Setup", 3: "Discovery", 4: "Client review", 5: "Fieldwork", 6: "Futran QA", 7: "Response", 8: "Final report", 9: "Remediation"}


@dataclass
class GateResult:
    ready: bool
    unmet: list[str] = field(default_factory=list)


GATES: dict[int, Callable[[Session, Engagement], GateResult]] = {}


def register(stage: int):
    def deco(fn):
        GATES[stage] = fn
        return fn

    return deco


def _result(unmet: list[str]) -> GateResult:
    return GateResult(ready=not unmet, unmet=unmet)


def signoff_approved(db: Session, engagement: Engagement, number: int) -> bool:
    try:
        from app.signoffs.service import is_approved  # added with sign-offs (Task 17)
    except ImportError:
        return False
    return is_approved(db, engagement, number)


@register(1)
def _stage1(db: Session, e: Engagement) -> GateResult:
    return _result([] if signoff_approved(db, e, 1) else ["Sign-off 1 (engagement letter and scope) is not approved yet."])


@register(2)
def _stage2(db: Session, e: Engagement) -> GateResult:
    depts = list(db.scalars(select(Department).where(Department.organization_id == e.client_id, Department.in_scope.is_(True), Department.deleted_at.is_(None)).order_by(Department.name)))
    if not depts:
        return _result(["Set up the client's departments."])
    d = today()
    rows = db.execute(
        select(RoleAssignment.scope_id, RoleAssignment.start_date, RoleAssignment.end_date)
        .join(User, User.id == RoleAssignment.user_id)
        .where(
            RoleAssignment.role == "dept_compliance_lead",
            RoleAssignment.scope_type == "department",
            RoleAssignment.scope_id.in_([x.id for x in depts]),
            RoleAssignment.deleted_at.is_(None),
            User.deleted_at.is_(None),
            User.status != "disabled",
        )
    )
    led = {sid for sid, start, end in rows if (start is None or start <= d) and (end is None or end >= d)}
    unmet = [] if e.departments_confirmed_at else ["The client has not confirmed the department list."]
    return _result(unmet + [f"{x.name} has no Department Compliance Lead." for x in depts if x.id not in led])


@register(3)
def _stage3(db: Session, e: Engagement) -> GateResult:
    """Discovery ends when the attestation campaign is closed and the governance request is submitted (spec §7)."""
    from app.attestation.service import current_campaign, is_open
    from app.governance.service import current_request

    unmet = []
    c = current_campaign(db, e)
    if c is None or is_open(c):
        unmet.append("Run and close the employee attestation campaign.")
    req = current_request(db, e)
    if req is None or req.status == "open":
        unmet.append("The client has not submitted the AI governance structure.")
    from app.inventory.models import UseCase

    drafts = db.scalar(select(func.count()).select_from(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None), UseCase.status.in_(["draft", "returned"])))
    if drafts:
        unmet.append(f"{drafts} use case{' is' if drafts == 1 else 's are'} still a draft or returned. Submit {'it' if drafts == 1 else 'them'} or delete {'it' if drafts == 1 else 'them'}.")
    return _result(unmet)


def gate_status(db: Session, engagement: Engagement) -> GateResult:
    if engagement.status in ("draft", "pending_approval"):
        return GateResult(False, ["The engagement has not been approved and sent to the client yet."])
    if engagement.status in ("completed", "archived"):
        return GateResult(False, ["The engagement is closed."])
    check = GATES.get(engagement.stage)
    if check is None:
        return GateResult(False, [f"Stage {engagement.stage} ({STAGE_NAMES.get(engagement.stage, '')}) has no exit check yet."])
    return check(db, engagement)


def advance_stage(db: Session, actor: User, engagement: Engagement) -> Engagement:
    """Move to the next stage when the current stage's gate is met; stage 9 completes the engagement."""
    result = gate_status(db, engagement)
    if not result.ready:
        raise Conflict(f"Stage {engagement.stage} ({STAGE_NAMES.get(engagement.stage)}) is not finished.", [{"field": "stage", "message": u} for u in result.unmet])
    if engagement.stage >= 9:
        from app.engagements.service import transition

        return transition(db, actor, engagement, "completed")
    frm = engagement.stage
    engagement.stage = frm + 1
    if engagement.status == "initiated":
        engagement.status = "in_progress"
    engagement.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="engagement.advance", obj=engagement, before={"stage": frm}, after={"stage": engagement.stage}, summary=f"{engagement.audit_ref}: stage {frm} → {engagement.stage} ({STAGE_NAMES[engagement.stage]})")
    return engagement


def advance_if_ready(db: Session, actor: User, e: Engagement | None) -> None:
    """Move on automatically while the current stage's exit gate is met (called after the events that can meet it).
    Several stages can complete at once (sign-offs 2–4 approved during discovery), and stage 9 completes the engagement."""
    for _ in range(len(STAGE_NAMES)):
        if e is None or e.status not in ("initiated", "in_progress") or not gate_status(db, e).ready:
            return
        advance_stage(db, actor, e)


@register(4)
def _stage4(db: Session, e: Engagement) -> GateResult:
    """Client review ends when sign-offs 2 (every department), 3 and 4 are approved; the snapshot is then locked (spec §7)."""
    from app.signoffs.client_review import in_scope_departments
    from app.signoffs.service import current

    unmet = []
    for d in in_scope_departments(db, e):
        so = current(db, e, 2, d.id)
        if so is None or so.status != "approved":
            unmet.append(f"Sign-off 2 for {d.name} is not approved yet.")
    for n, label in ((3, "Sign-off 3 (data categories for Tier 2–3 use cases)"), (4, "Sign-off 4 (management representation)")):
        so = current(db, e, n)
        if so is None or so.status != "approved":
            unmet.append(f"{label} is not approved yet.")
    return _result(unmet)


@register(5)
def _stage5(db: Session, e: Engagement) -> GateResult:
    """Fieldwork ends when every Tier 3 use case maps to a system, every system's assessment is complete and scored,
    and every finding is submitted (schematic §8a)."""
    from app.findings.models import Finding
    from app.questionnaire.service import Target, questions_for, _responses
    from app.scoring.service import latest
    from app.systems.service import systems_for, unmapped_tier3

    unmet = [f"{u.name} (Tier 3) is not mapped to a system." for u in unmapped_tier3(db, e)]
    for s in systems_for(db, e):
        t = Target(e, s)
        rs = _responses(db, t)
        missing = [q for q in questions_for(db, t, True) if q.required and (q.id not in rs or rs[q.id].status == "unanswered")]
        if missing:
            unmet.append(f"{s.reference_id} {s.name} has {len(missing)} required question{'s' if len(missing) != 1 else ''} unanswered.")
        row = latest(db, s)
        if row is None or row.inherent is None or row.maturity is None:
            unmet.append(f"{s.reference_id} {s.name} is not scored yet.")
    for f in db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None), Finding.status.in_(["draft", "returned"])).order_by(Finding.ref)):
        unmet.append(f"{f.ref} {f.title} is {'still a draft' if f.status == 'draft' else 'returned to its author'}. Submit it or dismiss it.")
    return _result(unmet)


@register(6)
def _stage6(db: Session, e: Engagement) -> GateResult:
    """Futran QA ends when sign-off 5 is approved and the client draft report (v1.0) is released."""
    from app.reports.service import latest

    unmet = [] if signoff_approved(db, e, 5) else ["Sign-off 5 (final risk tiers and findings) is not approved yet."]
    if latest(db, e, "v1.0", released=True) is None:
        unmet.append("Release the client draft report (v1.0).")
    return _result(unmet)


@register(8)
def _stage8(db: Session, e: Engagement) -> GateResult:
    """The final report stage ends with sign-off 7, the client's acknowledgement and, when a law needs one, sign-off 8."""
    from app.reports.service import declarations_for, latest, requires_public_summary

    unmet = [] if signoff_approved(db, e, 7) else ["Sign-off 7 (final report) is not approved yet."]
    final = latest(db, e, "v1.1")
    if final is None or final.status != "final" or not any(d.kind == "client_acknowledgement" for d in declarations_for(db, final)):
        unmet.append("The client has not acknowledged the final report.")
    if requires_public_summary(db, e) and not signoff_approved(db, e, 8):
        unmet.append("Sign-off 8 (public summary) is not approved yet.")
    return _result(unmet)


@register(7)
def _stage7(db: Session, e: Engagement) -> GateResult:
    """Response ends when the client accepts the remediation plan (sign-off 6)."""
    return _result([] if signoff_approved(db, e, 6) else ["Sign-off 6 (management responses and remediation plan) is not approved yet."])


@register(9)
def _stage9(db: Session, e: Engagement) -> GateResult:
    """Remediation ends when every item is closed; the engagement is then completed."""
    from app.remediation.service import items_for

    return _result([f"Not closed yet: {i.action[:80]}" for i in items_for(db, e) if i.status != "closed"])
