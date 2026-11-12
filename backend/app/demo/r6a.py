"""Release 2 R6a test data for the browser tests (test mode only): Delta Logistics, a client with a CAICO and a Client
Admin, an audit in progress with the demo auditor on its team, and one agent in its AI register. G-05 imports, G-06
templates and G-09 records are made by the browser tests themselves."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session


def seed(db: Session, password_hash: str) -> dict:
    from app.engagements.models import Engagement, EngagementTeam
    from app.register.models import RegisterSystem
    from app.servicetemplates.service import seed as seed_templates
    from app.tenancy.models import Organization, User
    from app.tenancy.service import assign_role, create_organization, create_user

    seed_templates(db)
    if db.scalar(select(Organization).where(Organization.name == "Delta Logistics")) is not None:
        return {}
    org = create_organization(db, name="Delta Logistics", type="client", hq_city="Chicago", hq_state="IL", hq_country="US")
    for name, email, role in (("Dee Caico", "caico@delta.demo", "caico"), ("Dan Admin", "admin@delta.demo", "client_admin")):
        u = create_user(db, org, name=name, email=email)
        u.password_hash, u.status = password_hash, "active"
        assign_role(db, u, role)
    e = Engagement(organization_id=org.id, client_id=org.id, name="Delta Logistics initial assessment", type="initial_assessment", audit_ref="FSL-AI-AUD-2026-901",
                   status="in_progress", stage=4)
    db.add(e)
    db.flush()
    auditor = db.scalar(select(User).where(User.email == "auditor1@futran.demo"))
    if auditor is not None:
        db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=auditor.id, role="auditor", created_by=auditor.id))
    db.add(RegisterSystem(organization_id=org.id, reference="AIS-001", name="Carrier-booking agent", type="agent", sourcing="in_house", stage="ready_for_go_live",
                          model_name="Provider model", model_version="2026-09", autonomy="acts_with_approval", guardrail_policy_ref="GR-014"))
    db.flush()
    return {"client_id": org.id, "engagement_id": e.id}
