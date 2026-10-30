"""Demo and browser-test data for the refresh, litigation, sales and alert screens (v0.6 WS-D).

Adds a Sales Team user and a QA Reviewer, the starter litigation cases (real cases, see app.litigation.seed) and,
for the browser tests, one client whose register holds a résumé screener and a customer chatbot, in scope of an
Illinois law, so cases, refresh changes and client alerts have someone to match."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.litigation.seed import seed_cases
from app.tenancy.models import Organization, User
from app.tenancy.service import assign_role, create_organization, create_user

STAFF = [("Sam Seller", "sales@futran.demo", "sales_team"), ("Quinn Taylor", "qa@futran.demo", "qa_reviewer")]
CLIENT = "Harbor Point Staffing"


def _staff(db: Session, password_hash: str | None) -> None:
    futran = db.scalar(select(Organization).where(Organization.type == "futran", Organization.is_internal.is_(False)))
    for name, email, role in STAFF:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = create_user(db, futran, name=name, email=email)
            if password_hash:
                u.password_hash = password_hash
            u.status = "active"
        assign_role(db, u, role)


def _client(db: Session, password_hash: str | None) -> Organization:
    from app.laws.publish import current_regulations
    from app.reference.models import Jurisdiction
    from app.register.models import RegisterSystem
    from app.regmaster.models import ClientGeography, ClientLawApplicability

    org = db.scalar(select(Organization).where(Organization.name == CLIENT))
    if org is not None:
        return org
    org = create_organization(db, name=CLIENT, type="client")
    caico = create_user(db, org, name="Rosa Delgado", email="rosa.delgado@harborpoint.example")
    caico.status = "active"
    if password_hash:
        caico.password_hash = password_hash
    assign_role(db, caico, "caico")
    db.add_all([
        RegisterSystem(organization_id=org.id, reference="AIS-001", name="Résumé screening", type="vendor_app", sourcing="vendor", purpose="Ranks job applicants before recruiter review",
                       decision_impact="consequential", stage="live", live_since=date(2025, 3, 1)),
        RegisterSystem(organization_id=org.id, reference="AIS-002", name="Candidate chat assistant", type="genai_chat_tool", sourcing="vendor",
                       purpose="Answers candidate questions about open roles and the application process", decision_impact="none", stage="live"),
    ])
    il = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US-IL"))
    if il is not None:
        db.add(ClientGeography(organization_id=org.id, jurisdiction_id=il.id, basis="employees", source="manual"))
        laws = sorted((r for r in current_regulations(db) if r.jurisdiction_id == il.id), key=lambda r: r.short_name)
        if laws:
            db.add(ClientLawApplicability(organization_id=org.id, regulation_id=laws[0].id, law_version_id=laws[0].current_version_id, in_scope=True,
                                          reason_text="Employs and hires people in Illinois"))
    db.flush()
    return org


def seed_wsd(db: Session, password_hash: str | None = None, with_client: bool = False) -> dict:
    _staff(db, password_hash)
    if with_client:
        _client(db, password_hash)
    added = seed_cases(db)
    db.flush()
    return {"cases_added": added}
