"""JSON shapes for the register screens."""
from sqlalchemy.orm import Session

from app.auth.deps import Actor
from app.register import service as svc
from app.register.models import RegisterSystem
from app.systems.models import Vendor
from app.tenancy.models import Department, User


def person(db: Session, uid: str | None) -> dict | None:
    if not uid:
        return None
    u = db.get(User, uid)
    return {"id": u.id, "name": u.name, "job_title": u.job_title} if u else None


def system_out(db: Session, s: RegisterSystem, actor: Actor | None, *, full: bool = False) -> dict:
    from app.policy.actions import Action
    from app.register.gate import gate_for, role_summary
    from app.register.router import may

    dept = db.get(Department, s.department_id) if s.department_id else None
    vendor = db.get(Vendor, s.vendor_id) if s.vendor_id else None
    d = svc.data_row(db, s)
    consent_label, consent_missing = svc.consent_status(d)
    laws = []
    for link in svc.law_links(db, s):
        reg = svc.current_regulation(db, link.regulation_id)
        laws.append({"id": link.id, "regulation_id": reg.id if reg else link.regulation_id, "short_name": reg.short_name if reg else "Law no longer in the library",
                     "source": link.source, "status": link.status, "removal_reason": link.removal_reason,
                     "removal_requested_by": person(db, link.removal_requested_by)["name"] if link.removal_requested_by and person(db, link.removal_requested_by) else None})
    roles = role_summary(db, s)
    out = {
        "id": s.id, "reference": s.reference, "name": s.name, "type": s.type, "type_label": svc.TYPE_LABELS.get(s.type, s.type),
        "sourcing": s.sourcing, "sourcing_label": svc.SOURCING_LABELS.get(s.sourcing, s.sourcing), "stage": s.stage, "stage_label": svc.STAGE_LABELS.get(s.stage, s.stage),
        "department": {"id": dept.id, "name": dept.name} if dept else None, "company_wide": s.company_wide, "purpose": s.purpose,
        "users_scope": s.users_scope, "users_description": s.users_description, "user_count": s.user_count, "owner": person(db, s.owner_user_id),
        "vendor": {"id": vendor.id, "name": vendor.legal_name} if vendor else None, "ai_provider": s.ai_provider, "ai_provider_label": svc.AI_PROVIDERS.get(s.ai_provider or ""),
        "model_name": s.model_name, "model_version": s.model_version, "algorithm_type": s.algorithm_type, "algorithm_label": svc.ALGORITHM_TYPES.get(s.algorithm_type or ""),
        "hosting": s.hosting, "vendor_trains_on_data": s.vendor_trains_on_data, "vendor_documents": s.vendor_documents or [], "autonomy": s.autonomy,
        "guardrail_policy_ref": s.guardrail_policy_ref, "agentassure_status": s.agentassure_status, "decision_impact": s.decision_impact,
        "risk_tier": s.risk_tier, "risk_tier_reason": s.risk_tier_reason, "bias_next_due": s.bias_next_due.isoformat() if s.bias_next_due else None,
        "origin": s.origin, "live_since": s.live_since.isoformat() if s.live_since else None,
        "data": {"data_categories": d.data_categories or [], "data_subjects": d.data_subjects or [], "consent_basis": d.consent_basis, "consent_ref": d.consent_ref,
                 "consent_evidence_id": d.consent_evidence_id, "retention_period": d.retention_period, "cross_border": d.cross_border} if d else
                {"data_categories": [], "data_subjects": [], "consent_basis": None, "consent_ref": None, "consent_evidence_id": None, "retention_period": None, "cross_border": None},
        "actions": [{"action_code": a.action_code, "label": svc.ACTION_CODES.get(a.action_code, a.action_code), "description": a.description} for a in svc.actions_of(db, s)],
        "laws": laws, "bias": svc.bias_status(db, s), "consent": {"label": consent_label, "missing": consent_missing},
        "roles": roles, "gate": gate_for(db, s, roles),
        "go_live": {"requested_by": person(db, s.go_live_requested_by), "requested_at": s.go_live_requested_at.isoformat() if s.go_live_requested_at else None,
                    "approved_by": person(db, s.go_live_approved_by), "approved_at": s.go_live_approved_at.isoformat() if s.go_live_approved_at else None},
        "updated_at": s.updated_at.isoformat() if s.updated_at else None, "updated_by": person(db, s.updated_by),
        "retired_reason": s.retired_reason,
    }
    if actor is not None:
        out["can_edit"] = may(db, actor, Action.EDIT_REGISTER, s)
        out["can_add_law"] = may(db, actor, Action.ADD_SYSTEM_LAW, s)
        out["can_remove_law"] = may(db, actor, Action.REMOVE_SYSTEM_LAW, s)
        out["can_fill_roles"] = may(db, actor, Action.FILL_SYSTEM_ROLES, s)
        out["can_record_history"] = may(db, actor, Action.RECORD_SYSTEM_HISTORY, s)
        out["can_submit_go_live"] = may(db, actor, Action.SUBMIT_GO_LIVE, s)
        out["can_approve_go_live"] = may(db, actor, Action.APPROVE_GO_LIVE, s)
    if full:
        from app.register.history import history_summary

        out["history"] = history_summary(db, s)
        out["suggested_laws"] = svc.suggested_laws(db, s)
    return out
