"""A world for the website library API: the law library and the starter AI court cases, plus everything that ties them to
Futran clients and staff (client matches, applicability, opportunities, follows, reviewers, pending proposals, unapproved
obligations), so the confidentiality tests can prove none of it leaves through the public API."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.clock import utcnow
from tests.factories import login_as, make_department, make_org, make_user

API = "/api/v1"
LIB = "/api/public/v1/library"
SITE = "https://www.futransolutions.com"


@pytest.fixture
def libw(db, client, matrix):
    from app.ai.models import Obligation
    from app.litigation.models import Case, CaseFollow
    from app.litigation.seed import seed_cases
    from app.litigation.service import match_case
    from app.refresh.models import RefreshRun
    from app.register.models import RegisterSystem
    from app.regmaster.models import ClientLawApplicability, ProposedChange
    from app.regmaster.seed import find_law, seed_regmaster
    from app.sales.models import Opportunity
    from app.systems.models import Vendor

    seed_regmaster(db)
    seed_cases(db)
    w = SimpleNamespace()
    f = make_org(db, type="futran")
    w.futran = f
    w.admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada.admin@futran.test")
    w.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chiefauditor", email="cara.chief@futran.test")
    w.aud = make_user(db, f, roles=["auditor"], name="Alex Auditorperson", email="alex.auditor@futran.test")
    w.sales = make_user(db, f, roles=["sales_team"], name="Sam Salesperson", email="sam.sales@futran.test")
    org = make_org(db, name="Quillfeather Mutual Insurance")  # a client name that appears nowhere in the law or case data
    w.org = org
    hr = make_department(db, org, name="Talent Acquisition")
    w.caico = make_user(db, org, roles=["caico"], name="Maribel Clientuser", email="maribel@quillfeather.test")
    w.cadmin = make_user(db, org, roles=["client_admin"], name="Otis Clientadmin", email="otis@quillfeather.test")
    vendor = Vendor(organization_id=org.id, legal_name="Zyxtrel Hiring Analytics LLC")
    db.add(vendor)
    db.flush()
    w.system = RegisterSystem(organization_id=org.id, reference="AIS-901", name="Quillfeather candidate ranker", type="vendor_app", sourcing="vendor",
                              vendor_id=vendor.id, department_id=hr.id, purpose="Ranks job applicants and candidate résumés for recruiters",
                              decision_impact="consequential", stage="live")
    db.add(w.system)
    db.flush()

    # a published case that matches the client's system, with a staff follow, internal talking points and an opportunity
    w.case = Case(name="Harlow v. Talentsift Corp.", geography="United States · federal", area="Hiring discrimination", court="U.S. District Court, D. Mass.",
                  docket_ref="1:26-cv-01234", description="Applicants say an AI screening tool rejected them because of age.",
                  why_matters="Deployers of screening tools may share liability.", stage="discovery", stage_note="Discovery under way",
                  last_update_on=date(2026, 11, 2), talking_points_futran="INTERNAL-TP: pitch the bias audit to every HR buyer this quarter.",
                  talking_points_client="Check that your screening vendor has run a bias audit.",
                  sources=[{"title": "Court docket", "url": "https://www.courtlistener.com/docket/1/harlow-v-talentsift/"}],
                  timeline=[{"on": "2026-03-01", "stage": "filed", "label": "Filed"}, {"on": "2026-11-02", "stage": "discovery", "label": "Discovery under way"}],
                  match_rule={"types": ["vendor_app"], "sourcing": ["vendor"], "vendors": ["zyxtrel"], "uses": ["applicant"]}, origin="manual",
                  created_by=w.chief.id, updated_by=w.chief.id)
    co = find_law(db, "US-CO", "^SB 26-189$")
    w.law = co
    w.case.regulation_ids = [co.id]
    db.add(w.case)
    db.flush()
    w.matches = match_case(db, w.case)
    assert [m.organization_id for m in w.matches] == [org.id], "the client must be matched to the case for the confidentiality test"
    db.add(CaseFollow(case_id=w.case.id, user_id=w.chief.id))
    w.opp = Opportunity(organization_id=org.id, trigger="case", trigger_ref=f"{w.case.id}:v1", service="Briefing and review of AI like that in Harlow",
                        service_kind="advisory", why_now="OPP-WHY: Quillfeather renewal in Q1", owner_id=w.sales.id, value=48500, system_ids=[w.system.id])
    db.add(w.opp)

    # the law: a named reviewer and watch list, a client in scope, a pending change, an approved and an unapproved obligation
    co.reviewer_id = w.aud.id
    co.review_due_on = date.today() + timedelta(days=30)
    co.watch = True
    co.refresh_every_days = 14
    db.add(ClientLawApplicability(organization_id=org.id, regulation_id=co.id, law_version_id=co.current_version_id, in_scope=True,
                                  reason_text="CLIENT-REASON: Quillfeather hires in Colorado", decided_by=w.chief.id, decided_at=utcnow()))
    db.add(ProposedChange(origin="claude_refresh", change_type="amendment", regulation_id=co.id, base_version_id=co.current_version_id, field_path="law.cure_period",
                          new_value="PENDING-VALUE: 90 days", summary="PENDING-SUMMARY: longer cure period", status="pending", proposed_by=w.aud.id))
    db.add(ProposedChange(origin="claude_refresh", change_type="new_case", jurisdiction_id=co.jurisdiction_id, field_path="new_case",
                          new_value={"name": "Unreviewed v. Proposal Inc.", "area": "Hiring", "stage": "filed"}, summary="PENDING-CASE: a new case", status="pending"))
    db.add(Obligation(organization_id=f.id, regulation_id=co.id, law_version_id=co.current_version_id, text="Give applicants notice before an AI decision.",
                      actor="deployer", citation="SB 26-189 §6-1-1703", status="approved", approved_by=w.chief.id, approved_at=utcnow()))
    db.add(Obligation(organization_id=f.id, regulation_id=co.id, law_version_id=co.current_version_id, text="UNAPPROVED-OBLIGATION: keep logs for ten years.",
                      actor="deployer", status="suggested"))
    # both libraries have refreshed once
    w.law_run = RefreshRun(kind="law", trigger="scheduled", status="completed", started_at=utcnow() - timedelta(hours=3), finished_at=utcnow() - timedelta(hours=2),
                           started_by=w.chief.id)
    w.lit_run = RefreshRun(kind="litigation", trigger="scheduled", status="completed", started_at=utcnow() - timedelta(hours=1), finished_at=utcnow() - timedelta(minutes=50))
    db.add_all([w.law_run, w.lit_run])
    db.commit()
    w.as_ = lambda u: login_as(client, db, u)
    return w


def new_key(client, w, name="Futran website", origins=(SITE,), rate=None) -> dict:
    """Create a website key as the Futran Admin; returns the create response (with the key, shown once)."""
    w.as_(w.admin)
    body = {"name": name, "allowed_origins": list(origins)}
    if rate is not None:
        body["rate_limit_per_minute"] = rate
    r = client.post(f"{API}/admin/website-keys", json=body)
    assert r.status_code == 200, r.text
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    return r.json()


@pytest.fixture
def key(client, libw):
    return new_key(client, libw)["key"]


def hdr(k: str, **extra) -> dict:
    return {"X-API-Key": k, **extra}


def staff(client, w, path: str):
    """GET a staff endpoint as the Chief Auditor (who sees the whole library and tracker)."""
    w.as_(w.chief)
    r = client.get(f"{API}{path}")
    assert r.status_code == 200, r.text
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    return r.json()


def all_pages(client, path: str, k: str, **params) -> list[dict]:
    out, page = [], 1
    while True:
        r = client.get(f"{LIB}{path}", params={**params, "page": page, "limit": 200}, headers=hdr(k))
        assert r.status_code == 200, r.text
        b = r.json()
        out += b["data"]
        if not b["pagination"]["next_page"]:
            return out
        page = b["pagination"]["next_page"]


def walk(value, keys: set, strings: list):
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(k)
            walk(v, keys, strings)
    elif isinstance(value, list):
        for v in value:
            walk(v, keys, strings)
    elif isinstance(value, str):
        strings.append(value)


def select_one(db, model, *where):
    return db.scalar(select(model).where(*where).limit(1))
