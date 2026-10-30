"""Required roles, the go-live gate and go-live approval (spec §24.2, §24.3, §27.2).

The required set for a system is computed from the laws on it (LawRoleMap in the regulatory master), never stored.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid
from app.register.models import RegisterSystem
from app.tenancy.models import User


CATALOGUE_MISSING = "The governance role catalogue has not loaded. Ask Futran to check the platform."


def catalogue_missing(db: Session) -> bool:
    """With no role catalogue every system has zero required roles, so the gate would pass on nothing (start-up seed
    failed); go-live is refused until it loads."""
    from app.regmaster.models import RoleCatalog

    return db.scalar(select(RoleCatalog.id).limit(1)) is None


def role_summary(db: Session, s: RegisterSystem) -> dict:
    from app.register.roles import role_rows

    rows = role_rows(db, s)
    required = [r for r in rows if r["requirement"] == "required"]
    due = [r for r in required if r["due_for_gate"]]
    filled = [r for r in required if r["filled"]]
    return {
        "required": len(required), "filled": len(filled), "recommended": sum(1 for r in rows if r["requirement"] == "recommended"),
        "no_such_person": sum(1 for r in required if r["status"] == "no_such_person"),
        "pending_committee": sum(1 for r in required if r["status"] == "pending_committee"),
        "not_answered": sum(1 for r in required if r["status"] is None),
        "not_yet_due": sum(1 for r in required if not r["filled"] and not r["due_for_gate"]),
        "blocking": [r["name"] + (f" ({r['status_label'].lower()})" if r["status"] else " (not answered)") + (", company-wide" if r["level"] == "company" else "")
                     for r in due if not r["filled"]],
    }


def requirement_blockers(db: Session, s: RegisterSystem) -> list[str]:
    from app.register.requirements import gate_blockers

    return gate_blockers(db, s)


def gate_for(db: Session, s: RegisterSystem, roles: dict | None = None) -> dict:
    roles = roles if roles is not None else role_summary(db, s)
    reqs = requirement_blockers(db, s)
    blockers = {"roles": roles["blocking"], "requirements": reqs}
    n_roles, n_reqs = len(roles["blocking"]), len(reqs)
    parts = [f"{n_roles} role{'s' if n_roles != 1 else ''}"] if n_roles else []
    parts += [f"{n_reqs} requirement{'s' if n_reqs != 1 else ''}"] if n_reqs else []
    if s.stage == "retired":
        return {"state": "retired", "label": "Retired", **blockers}
    if s.stage == "live":
        return {"state": "live_finding" if parts else "live_clear", "label": "Live · finding raised" if parts else "Live · clear", **blockers}
    if s.stage in ("proposed", "in_development"):
        return {"state": "not_due", "label": "Not yet due", **blockers}
    if catalogue_missing(db):
        return {"state": "blocked", "label": CATALOGUE_MISSING, **blockers}
    if parts:
        return {"state": "blocked", "label": "Blocked: " + " and ".join(parts), **blockers}
    if s.go_live_requested_at:
        return {"state": "awaiting_approval", "label": "Waiting for go-live approval", **blockers}
    return {"state": "ready", "label": "Ready for approval", **blockers}


def _assert_clear(db: Session, s: RegisterSystem) -> None:
    if catalogue_missing(db):
        raise Conflict(CATALOGUE_MISSING, errors=[{"field": "gate", "message": CATALOGUE_MISSING}])
    roles = role_summary(db, s)
    reqs = requirement_blockers(db, s)
    if roles["blocking"] or reqs:
        items = roles["blocking"] + reqs
        raise Conflict("Go-live is blocked until these are resolved: " + "; ".join(items) + ".", errors=[{"field": "gate", "message": i} for i in items])


def submit_go_live(db: Session, actor: User, s: RegisterSystem) -> RegisterSystem:
    from app.register.service import compliance_officers, log_change
    from app.notifications.service import notify

    if s.stage not in ("in_development", "ready_for_go_live"):
        raise Conflict("Only a system in development or ready for go-live can be submitted.")
    if s.go_live_requested_at:
        raise Conflict("This system is already waiting for go-live approval.")
    _assert_clear(db, s)
    old = s.stage
    s.stage, s.go_live_requested_by, s.go_live_requested_at, s.updated_by = "ready_for_go_live", actor.id, utcnow(), actor.id
    if old != s.stage:
        log_change(db, actor, s, "stage", old, s.stage, "Submitted for go-live approval.")
    log_change(db, actor, s, "go_live", None, "Submitted for approval", None, raw=True)
    audit.record(db, actor_id=actor.id, action="register.go_live_submit", obj=s, summary=f"Submitted {s.reference} {s.name} for go-live approval")
    notify(db, compliance_officers(db, s.organization_id, exclude=actor.id), "register_go_live", f"Approve go-live: {s.name}", f"Submitted by {actor.name}.", f"/register/{s.id}/roles")
    return s


def decide_go_live(db: Session, actor: User, s: RegisterSystem, approve: bool, comment: str | None) -> RegisterSystem:
    from app.register.service import log_change
    from app.notifications.service import notify
    from app.policy.sod import assert_not_self_approval

    if not s.go_live_requested_at or s.stage != "ready_for_go_live":
        raise Conflict("This system has not been submitted for go-live approval.")
    assert_not_self_approval(actor.id, s.go_live_requested_by)
    comment = " ".join(str(comment or "").split()) or None
    requester = db.get(User, s.go_live_requested_by) if s.go_live_requested_by else None
    if approve:
        _assert_clear(db, s)
        s.stage, s.go_live_approved_by, s.go_live_approved_at, s.live_since = "live", actor.id, utcnow(), utcnow().date()
        log_change(db, actor, s, "stage", "ready_for_go_live", "live", comment or "Go-live approved.")
        log_change(db, actor, s, "go_live", "Submitted for approval", "Approved", comment, raw=True)
    else:
        if not comment:
            raise Invalid(errors=[{"field": "comment", "message": "Say what needs to change before go-live."}])
        s.go_live_requested_by = s.go_live_requested_at = None
        log_change(db, actor, s, "go_live", "Submitted for approval", "Returned", comment, raw=True)
    s.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="register.go_live_decided", obj=s, after={"approved": approve, "comment": comment},
                 summary=f"{'Approved' if approve else 'Returned'} go-live for {s.reference} {s.name}")
    if requester:
        notify(db, [requester], "register_go_live_decided", f"Go-live {'approved' if approve else 'returned'}: {s.name}", comment, f"/register/{s.id}")
    return s
