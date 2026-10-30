"""Impact of a proposed law change (spec §25.3 step 5). Delegates to the regulatory master's computation when it is
available (app.regmaster.impact.compute_impacts); otherwise records the clients the law applies to, their register
systems linked to the law, the roles the change touches and whether a sent intro letter used the law."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.register.models import RegisterSystemLaw
from app.regmaster.models import ChangeImpact, ClientGeography, ClientLawApplicability, IntroLetter, LawRoleMap, ProposedChange, RoleCatalog


def compute(db: Session, change: ProposedChange) -> list[ChangeImpact]:
    try:
        from app.regmaster.impact import compute_impacts
    except ImportError:
        compute_impacts = None
    if compute_impacts is not None:
        return list(compute_impacts(db, change))
    for old in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == change.id)):
        db.delete(old)
    if change.change_type == "new_law" or change.regulation_id is None:
        orgs = sorted(set(db.scalars(select(ClientGeography.organization_id).where(ClientGeography.jurisdiction_id == change.jurisdiction_id, ClientGeography.deleted_at.is_(None)))))
    else:
        orgs = sorted(set(db.scalars(select(ClientLawApplicability.organization_id).where(ClientLawApplicability.regulation_id == change.regulation_id, ClientLawApplicability.in_scope.is_(True)))))
    roles: list[str] = []
    if change.field_path.startswith("role_map."):
        roles = [change.field_path.split(".", 1)[1]]
    elif change.base_version_id and change.field_path in ("law.effective_on", "law.compliance_on", "law.status", "repeal"):
        ids = list(db.scalars(select(LawRoleMap.role_id).where(LawRoleMap.law_version_id == change.base_version_id)))
        roles = sorted(db.scalars(select(RoleCatalog.code).where(RoleCatalog.id.in_(ids)))) if ids else []
    out = []
    for org in orgs:
        systems = list(db.scalars(select(RegisterSystemLaw.register_system_id).where(RegisterSystemLaw.organization_id == org, RegisterSystemLaw.regulation_id == change.regulation_id,
                                                                                      RegisterSystemLaw.status == "active"))) if change.regulation_id else []
        letter = False
        if change.base_version_id:
            for lt in db.scalars(select(IntroLetter).where(IntroLetter.organization_id == org, IntroLetter.status == "sent")):
                if change.base_version_id in (lt.law_versions_used or []):
                    letter = True
        imp = ChangeImpact(proposed_change_id=change.id, organization_id=org, ai_system_ids=systems, roles_affected=roles, letter_update_needed=letter)
        db.add(imp)
        out.append(imp)
    db.flush()
    return out
