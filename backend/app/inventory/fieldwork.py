"""Auditor fieldwork on one use case (screen 16): final tier, AEDT determination, evidence requests, null-compliance check."""
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import ClientRequirement, Engagement
from app.inventory.models import NamedUser, UseCase
from app.inventory.service import effective_tier
from app.questionnaire.models import Question, Response
from app.systems.models import AISystem

NULL_COMPLIANCE_MESSAGE = ("The client reports no applicant demographic data is collected. A bias audit could be run with no categories to test, "
                           "which meets the form of LL144 but gives no real transparency. Flag it in the report.")


@dataclass
class NullComplianceResult:
    applies: bool
    message: str | None = None
    systems: list[str] = field(default_factory=list)
    suggested_finding: dict | None = None


def _systems_for(db: Session, uc: UseCase) -> list[AISystem]:
    return [s for s in db.scalars(select(AISystem).where(AISystem.engagement_id == uc.engagement_id, AISystem.deleted_at.is_(None))) if uc.id in (s.use_case_ids or [])]


def null_compliance_check(db: Session, uc: UseCase) -> NullComplianceResult:
    """Addendum 5.1a: a Tier 3 hiring use case (an AEDT in scope) whose system's answer to 5.1a.01 is "no"."""
    if effective_tier(uc) != 3 or uc.aedt_determination != "in_scope":
        return NullComplianceResult(False)
    q = db.scalar(select(Question).where(Question.code == "5.1a.01").limit(1))
    hits = []
    for s in _systems_for(db, uc):
        r = db.scalar(select(Response).where(Response.ai_system_id == s.id, Response.question_id == q.id, Response.deleted_at.is_(None))) if q else None
        if r is not None and (r.status == "not_yet_in_place" or (r.status == "answered" and str(r.value).casefold() == "no")):
            hits.append(s)
    if not hits:
        return NullComplianceResult(False)
    return NullComplianceResult(True, NULL_COMPLIANCE_MESSAGE, [f"{s.reference_id} {s.name}" for s in hits], {
        "title": f"Null-compliance risk: no demographic data for {uc.name}", "severity": "high", "null_compliance_flag": True, "use_case_ids": [uc.id],
        "ai_system_id": hits[0].id, "template_section": "5.1a", "control_refs": ["NYC LL144 · bias audit requirement"],
        "description": "Condition: the organization collects no applicant demographic data, so a bias audit of this tool has no categories to test.\n"
                       "Criteria: NYC Local Law 144 requires an independent bias audit with impact ratios by sex and race/ethnicity.\n"
                       "Effect: an audit could meet the form of the law while giving no real transparency to candidates.",
        "recommended_remediation": "Start voluntary demographic data collection for applicants, or use representative test data, and document the choice.",
    })


def control_options(db: Session, e: Engagement) -> list[str]:
    """Laws and frameworks in scope, offered as control references for findings."""
    from app.laws.models import Regulation

    regs = db.scalars(select(Regulation.short_name).join(ClientRequirement, ClientRequirement.regulation_id == Regulation.id)
                      .where(ClientRequirement.engagement_id == e.id, ClientRequirement.in_scope.is_(True), ClientRequirement.deleted_at.is_(None)))
    return sorted({r for r in regs if r})


def fieldwork_view(db: Session, uc: UseCase) -> dict:
    from app.docrequests.evidence_requests import request_out
    from app.docrequests.models import EvidenceRequest
    from app.findings.models import Finding
    from app.findings.service import finding_out
    from app.tenancy.models import Department, User

    e = db.get(Engagement, uc.engagement_id)
    named = list(db.scalars(select(NamedUser).where(NamedUser.use_case_id == uc.id, NamedUser.deleted_at.is_(None))))
    dept = db.get(Department, uc.department_id)
    submitter = db.get(User, uc.submitted_by) if uc.submitted_by else None
    reqs = db.scalars(select(EvidenceRequest).where(EvidenceRequest.use_case_id == uc.id, EvidenceRequest.deleted_at.is_(None)).order_by(EvidenceRequest.ref))
    findings = [f for f in db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None)).order_by(Finding.ref)) if uc.id in (f.use_case_ids or [])]
    return {
        "use_case": {"id": uc.id, "name": uc.name, "department": dept.name if dept else None, "purpose": uc.purpose, "data_categories": uc.data_categories, "decision_impact": uc.decision_impact,
                     "proposed_tier": uc.proposed_tier, "final_tier": uc.final_tier, "final_tier_rationale": uc.final_tier_rationale, "aedt_determination": uc.aedt_determination, "status": uc.status,
                     "submitted_by": submitter.name if submitter else None},
        "named_users": {"count": len(named), "not_trained": sum(1 for n in named if n.training_complete is False), "unconfirmed": sum(1 for n in named if n.training_complete is None and not n.unable_reason)},
        "systems": [{"id": s.id, "reference_id": s.reference_id, "name": s.name} for s in _systems_for(db, uc)],
        "evidence_requests": [request_out(db, r, True) for r in reqs],
        "findings": [finding_out(db, f) for f in findings],
        "null_compliance": asdict(null_compliance_check(db, uc)),
        "control_options": control_options(db, e),
        "client_id": e.client_id, "audit_ref": e.audit_ref, "stage": e.stage,
    }
