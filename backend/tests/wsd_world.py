import pytest

from app.register.models import RegisterSystem
from app.systems.models import Vendor
from tests.factories import make_org, make_user


@pytest.fixture
def lit(db, matrix):
    """Futran staff (Chief Auditor, auditor, Sales, Admin) and two clients with register systems."""
    f = make_org(db, type="futran")
    p = {
        "chief": make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test"),
        "chief2": make_user(db, f, roles=["chief_auditor"], name="Dan Chief", email="dan@futran.test"),
        "aud": make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test"),
        "sales": make_user(db, f, roles=["sales_team"], name="Sam Seller", email="sam@futran.test"),
        "admin": make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test"),
        "qa": make_user(db, f, roles=["qa_reviewer"], name="Quinn Reviewer", email="quinn@futran.test"),
    }
    abc = make_org(db, name="ABC Corp")
    nw = make_org(db, name="Northwind Health")
    p["abc"], p["nw"] = abc, nw
    p["maria"] = make_user(db, abc, roles=["caico"], name="Maria Lopez", email="maria@abc.test")
    wd = Vendor(organization_id=abc.id, legal_name="Workday, Inc.")
    db.add(wd)
    db.flush()
    p["screening"] = RegisterSystem(organization_id=abc.id, reference="AIS-001", name="Résumé screening", type="vendor_app", sourcing="vendor", vendor_id=wd.id, purpose="Ranks job applicants before recruiter review", decision_impact="consequential", stage="live")
    p["chatbot"] = RegisterSystem(organization_id=abc.id, reference="AIS-002", name="Website chatbot", type="genai_chat_tool", sourcing="vendor", purpose="Answers customer questions about refunds", stage="live")
    p["nw_ats"] = RegisterSystem(organization_id=nw.id, reference="AIS-001", name="ATS ranking", type="vendor_app", sourcing="vendor", purpose="Scores candidates for interview", stage="live")
    p["retired"] = RegisterSystem(organization_id=nw.id, reference="AIS-002", name="Old applicant screener", type="vendor_app", sourcing="vendor", purpose="Screened applicants", stage="retired")
    db.add_all([p["screening"], p["chatbot"], p["nw_ats"], p["retired"]])
    db.commit()
    return p


HIRING_CASE = {
    "name": "Mobley v. Workday, Inc.",
    "geography": "United States · federal",
    "jurisdiction_code": "US",
    "area": "Hiring discrimination",
    "court": "U.S. District Court, N.D. Cal.",
    "docket_ref": "3:23-cv-00770",
    "description": "Applicant says AI screening tools rejected him because of age, race and disability.",
    "stage": "discovery",
    "match_rule": {"types": ["vendor_app"], "sourcing": ["vendor"], "uses": ["applicant", "candidate", "résumé", "resume"]},
    "sources": [{"title": "Court docket", "url": "https://www.courtlistener.com/docket/66831340/mobley-v-workday-inc/"}],
}
