"""Inventory snapshot (spec §7 stage 4, schematic §8a): locked when sign-off 4 is approved; later arrivals are addenda."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.engagements.models import Engagement
from app.inventory.models import AITool, InventorySnapshot, NamedUser, SnapshotAddendum, UseCase
from app.tenancy.models import Department

__all__ = ["InventorySnapshot", "SnapshotAddendum", "lock_snapshot", "current_snapshot", "add_snapshot_addendum", "snapshot_payload"]


def snapshot_payload(db: Session, e: Engagement) -> dict:
    from app.inventory.service import effective_tier, tools_for
    from app.questionnaire.models import Question, Response
    from app.systems.models import AISystem
    from app.systems.service import systems_for

    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == e.client_id))}
    tools = [{"id": t.id, "vendor": t.vendor, "product": t.product, "account_type": t.account_type, "approval_status": t.approval_status} for t in tools_for(db, e.client_id)]
    ucs = []
    for u in db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None)).order_by(UseCase.name)):
        named = db.scalars(select(NamedUser).where(NamedUser.use_case_id == u.id, NamedUser.deleted_at.is_(None)))
        ucs.append({"id": u.id, "name": u.name, "department": depts.get(u.department_id), "status": u.status, "proposed_tier": u.proposed_tier, "final_tier": u.final_tier, "tier": effective_tier(u),
                    "tool_ids": u.tool_ids, "data_categories": u.data_categories, "decision_impact": u.decision_impact,
                    "named_users": [{"name": n.person_name, "training_complete": n.training_complete, "policy_acknowledged": n.policy_acknowledged, "oversight_role_confirmed": n.oversight_role_confirmed, "unable_reason": n.unable_reason} for n in named]})
    systems = [{"id": s.id, "reference_id": s.reference_id, "name": s.name, "built_by": s.built_by, "depth": s.assessment_depth, "use_case_ids": s.use_case_ids} for s in systems_for(db, e)]
    codes = {q.id: q.code for q in db.scalars(select(Question))}
    refs = {s.id: s.reference_id for s in db.scalars(select(AISystem).where(AISystem.engagement_id == e.id))}
    responses = [{"system": refs.get(r.ai_system_id) if r.ai_system_id else None, "code": codes.get(r.question_id), "value": r.client_value, "status": r.client_status, "na_reason": r.client_na_reason}
                 for r in db.scalars(select(Response).where(Response.engagement_id == e.id, Response.deleted_at.is_(None), Response.client_status.is_not(None)))]
    return {"tools": tools, "use_cases": ucs, "systems": systems, "responses": responses}


def current_snapshot(db: Session, e: Engagement) -> InventorySnapshot | None:
    return db.scalar(select(InventorySnapshot).where(InventorySnapshot.engagement_id == e.id, InventorySnapshot.deleted_at.is_(None)).order_by(InventorySnapshot.version.desc()).limit(1))


def lock_snapshot(db: Session, e: Engagement, sign_off) -> InventorySnapshot:
    version = (db.scalar(select(func.max(InventorySnapshot.version)).where(InventorySnapshot.engagement_id == e.id)) or 0) + 1
    now = utcnow()
    snap = InventorySnapshot(organization_id=e.client_id, engagement_id=e.id, version=version, locked_at=now, sign_off_id=sign_off.id if sign_off else None, payload=snapshot_payload(db, e))
    db.add(snap)
    e.client_answers_locked_at = now
    db.flush()
    audit.record(db, actor_id=None, actor_name="System", action="inventory.snapshot_locked", obj=snap, engagement_id=e.id,
                 after={"version": version, "use_cases": len(snap.payload["use_cases"])}, summary=f"Locked inventory snapshot v{version} for {e.audit_ref}")
    return snap


def add_snapshot_addendum(db: Session, snap: InventorySnapshot, kind: str, payload: dict) -> SnapshotAddendum:
    add = SnapshotAddendum(organization_id=snap.organization_id, snapshot_id=snap.id, kind=kind, payload=payload, recorded_at=utcnow())
    db.add(add)
    db.flush()
    audit.record(db, actor_id=None, actor_name="System", action="inventory.snapshot_addendum", obj=add, engagement_id=snap.engagement_id, after={"kind": kind}, summary=f"Added a dated addendum to snapshot v{snap.version}: {kind.replace('_', ' ')}")
    return add
