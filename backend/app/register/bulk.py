"""Bulk edit of register systems (R2, spec §24.4).

Only the fields sent are applied ("Keep current" sends nothing). A reason is required and goes to every row's change
history. "Live" is never set in bulk. Role conflicts (role already filled) are resolved per role: keep, replace or add.
Everything is checked before anything is written, so a request either applies to every selected system or to none.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Conflict, Invalid
from app.register import service as svc
from app.register.models import RegisterSystem
from app.tenancy.models import Organization, User

BULK_FIELDS = {"department_id", "stage", "owner_user_id", "bias_next_due", "purpose", "decision_impact", "ai_provider", "hosting", "vendor_trains_on_data", "type", "sourcing", "vendor_id"}


def bulk_edit(db: Session, actor: User, systems: list[RegisterSystem], body: dict, *, can_remove_law_directly: bool, rights=None) -> dict:
    """`rights` is the signed-in Actor, used for the per-role checks."""
    reason = " ".join(str(body.get("reason") or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Give a reason for the change. It is saved to each system's change history."}])
    changes = {k: v for k, v in (body.get("changes") or {}).items() if k in BULK_FIELDS}
    if changes.get("stage") == "live":
        raise Conflict("Live cannot be set in bulk. Each system needs its own go-live approval.")
    add_ids = [x for x in body.get("add_regulation_ids") or [] if isinstance(x, str)]
    remove_ids = [x for x in body.get("remove_regulation_ids") or [] if isinstance(x, str)]
    roles = body.get("roles") or []
    bias_req = body.get("request_bias_test") if isinstance(body.get("request_bias_test"), dict) else None
    bias_due: date | None = None
    if bias_req is not None:
        errs: list = []
        bias_due = svc._date(bias_req.get("due"), "request_bias_test.due", errs)
        if errs or bias_due is None:
            raise Invalid(errors=[{"field": "request_bias_test.due", "message": "Enter the date the test is due."}])

    org = db.get(Organization, systems[0].organization_id)
    cleaned = {s.id: svc.clean(db, org, changes, current=s) for s in systems} if changes else {}
    from app.register.roles import plan_bulk_roles

    role_plan = plan_bulk_roles(db, rights, systems, roles) if roles else []
    preview = bool(body.get("preview"))
    batch = svc.new_batch_id()
    per: list[dict] = []
    total = 0
    from app.core.db import hold_transaction

    hold_transaction(db)  # so the savepoint below cannot commit on its own (sqlite3 driver)
    sp = db.begin_nested()
    try:
        for s in systems:
            n = 0
            if s.id in cleaned:
                n += len(svc.update_system(db, actor, s, changes, reason=reason, batch_id=batch, cleaned=dict(cleaned[s.id])))
            for rid in add_ids:
                if svc.add_law(db, actor, s, rid, reason=reason, batch_id=batch) is not None:
                    n += 1
            for rid in remove_ids:
                target = svc.current_regulation(db, rid)
                for link in svc.law_links(db, s):
                    cur = svc.current_regulation(db, link.regulation_id)
                    if target is not None and cur is not None and cur.id == target.id and link.status == "active":
                        svc.remove_law(db, actor, s, link, reason=reason, direct=can_remove_law_directly, batch_id=batch)
                        n += 1
            if bias_due is not None and s.bias_next_due != bias_due:
                old = s.bias_next_due
                s.bias_next_due = bias_due
                svc.log_change(db, actor, s, "bias_next_due", old, bias_due, reason, batch_id=batch)
                n += 1
            from app.register.roles import apply_bulk_roles

            n += apply_bulk_roles(db, actor, s, [p for p in role_plan if p["system_id"] == s.id], reason, batch)
            per.append({"id": s.id, "name": s.name, "changes": n, "conflicts": [p for p in role_plan if p["system_id"] == s.id and p["conflict"]]})
            total += n
        if preview:
            sp.rollback()
        else:
            sp.commit()
    except Exception:
        sp.rollback()
        raise
    if preview:
        db.expire_all()
    else:
        if bias_due is not None:
            from app.notifications.service import notify

            for s in systems:
                owner = db.get(User, s.owner_user_id) if s.owner_user_id else None
                if owner:
                    notify(db, [owner], "register_bias_test_requested", f"Bias test requested: {s.name}", f"Due {bias_due.isoformat()}. Asked by {actor.name}. Reason: {reason}", f"/register/{s.id}/history")
        audit.record(db, actor_id=actor.id, action="register.bulk_edit", organization_id=org.id, object_type="RegisterSystem", object_id=batch,
                     after={"systems": [s.reference for s in systems], "changes": changes, "add_laws": add_ids, "remove_laws": remove_ids, "reason": reason},
                     summary=f"Bulk edited {len(systems)} AI systems ({total} changes)")
    return {"preview": preview, "batch_id": None if preview else batch, "change_count": total, "systems_changed": sum(1 for p in per if p["changes"]), "systems": per}
