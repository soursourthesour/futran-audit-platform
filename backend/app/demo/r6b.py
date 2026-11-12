"""Demo and browser-test data for Release 2 R6b: a client on a Copilot readiness engagement and a client on an EU AI Act
readiness engagement, each with the audit team and a CAICO, plus a Futran Legal/Compliance Reviewer. Idempotent; the
two clients are new tenants, so no existing demo data changes. Imports, classifications and sign-offs are left for
the people (and the browser tests) to do."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement, EngagementTeam
from app.engagements.service import next_audit_ref
from app.register.models import RegisterSystem
from app.tenancy.models import Organization, User
from app.tenancy.service import assign_role, create_organization, create_user

COPILOT_CLIENT = "Acme Staffing LLC"
EU_CLIENT = "Northbank Credit Union"
LEGAL = ("Jordan Ellis", "legal@futran.demo")
COPILOT_CAICO = ("Dana Reyes", "dana.reyes@acmestaffing.example")
EU_CAICO = ("Ines Maier", "ines.maier@northbank.example")


def _user(db: Session, org: Organization, name: str, email: str, role: str, password_hash: str | None) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = create_user(db, org, name=name, email=email)
        u.status = "active"
        if password_hash:
            u.password_hash = password_hash
    assign_role(db, u, role)
    return u


def _engagement(db: Session, org: Organization, name: str, type_: str, team: list[tuple[User | None, str]]) -> Engagement:
    e = Engagement(organization_id=org.id, client_id=org.id, name=name, type=type_, audit_ref=next_audit_ref(db), status="in_progress", stage=3,
                   period_start=date(date.today().year, 1, 1), period_end=date(date.today().year, 12, 31))
    db.add(e)
    db.flush()
    for u, role in team:
        if u is not None:
            db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=u.id, role=role))
    return e


def seed_r6b(db: Session, password_hash: str | None = None) -> dict:
    futran = db.scalar(select(Organization).where(Organization.type == "futran", Organization.is_internal.is_(False)))
    auditor = db.scalar(select(User).where(User.email == "auditor1@futran.demo"))
    manager = db.scalar(select(User).where(User.email.in_(("manager@futran.demo", "em@futran.demo"))))
    legal = _user(db, futran, *LEGAL, "legal_reviewer", password_hash)
    out: dict = {}

    acme = db.scalar(select(Organization).where(Organization.name == COPILOT_CLIENT, Organization.type == "client"))
    if acme is None:
        acme = create_organization(db, name=COPILOT_CLIENT, type="client", status="active", industry="staffing", hq_city="Jersey City", hq_state="NJ", hq_country="US")
        _user(db, acme, *COPILOT_CAICO, "caico", password_hash)
        _engagement(db, acme, "Microsoft 365 Copilot readiness", "copilot_readiness", [(auditor, "auditor"), (manager, "engagement_manager")])
    out["copilot_client"] = acme.id

    nb = db.scalar(select(Organization).where(Organization.name == EU_CLIENT, Organization.type == "client"))
    if nb is None:
        nb = create_organization(db, name=EU_CLIENT, type="client", status="active", industry="bfsi", hq_city="Dublin", hq_country="IE")
        _user(db, nb, *EU_CAICO, "caico", password_hash)
        _engagement(db, nb, "EU AI Act readiness", "eu_ai_act_readiness", [(auditor, "auditor"), (manager, "engagement_manager"), (legal, "legal_reviewer")])
        db.add_all([
            RegisterSystem(organization_id=nb.id, reference="AIS-001", name="Credit decision model", type="in_house_model", sourcing="in_house", stage="live",
                           decision_impact="consequential", purpose="Scores loan applications from EU members", run_location={"country": "IE"},
                           vendor_documents=[], source_refs=[], history_answers={}),
            RegisterSystem(organization_id=nb.id, reference="AIS-002", name="Hiring screening (vendor)", type="vendor_app", sourcing="vendor", stage="live",
                           decision_impact="consequential", purpose="Ranks job applicants", data_locations=[{"country": "IE"}, {"country": "DE"}],
                           vendor_documents=[], source_refs=[], history_answers={}),
            RegisterSystem(organization_id=nb.id, reference="AIS-003", name="Member chatbot", type="genai_chat_tool", sourcing="vendor", stage="live",
                           decision_impact="none", purpose="Answers member questions", data_locations=[{"country": "IE"}], vendor_documents=[], source_refs=[], history_answers={}),
            RegisterSystem(organization_id=nb.id, reference="AIS-004", name="Microsoft 365 Copilot", type="genai_chat_tool", sourcing="vendor", stage="live",
                           decision_impact="none", purpose="Drafting and search for staff", data_locations=[{"country": "IE"}], company_wide=True,
                           vendor_documents=[], source_refs=[], history_answers={}),
        ])
    out["eu_client"] = nb.id
    db.flush()
    return out
