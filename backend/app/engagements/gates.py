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
    return _result([f"{x.name} has no Department Compliance Lead." for x in depts if x.id not in led])


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
    """Move on automatically when the current stage's exit gate is met (called after the events that can meet it)."""
    if e is not None and e.status in ("initiated", "in_progress") and e.stage < 9 and gate_status(db, e).ready:
        advance_stage(db, actor, e)
