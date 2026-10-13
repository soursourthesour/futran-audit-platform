from app.engagements.service import add_location
from app.engagements.suggest import suggest_requirements
from tests.factories import make_org


def _ny_chicago(db):
    org = make_org(db, industry="Staffing & recruitment", engagement_reason="AI screening and ranking of job applicants")
    add_location(db, org, site_name="Headquarters", country_code="US", subdivision_code="US-NY", city="New York")
    add_location(db, org, site_name="Chicago office", country_code="US", subdivision_code="IL", city="Chicago")
    return org


def test_suggest_ny_chicago_hiring(db, matrix):
    org = _ny_chicago(db)
    sugg = suggest_requirements(db, org)
    pre = [s.label for s in sugg if s.prechecked]
    for name in ["NYC Local Law 144", "HB 3773", "Title VII", "Age Discrimination in Employment Act", "Civil Rights Law §52-c", "NIST AI Risk Management Framework"]:
        assert any(name in p for p in pre), name
    ll144 = next(s for s in sugg if "Local Law 144" in s.label)
    assert ll144.source == "auto" and "Headquarters" in ll144.reason and ll144.jurisdiction_code == "US-NYC"
    nist = next(s for s in sugg if "NIST" in s.label)
    assert nist.source == "futran_default" and nist.reason == "Futran default assessment framework"
    s52 = next(s for s in sugg if "52-c" in s.label)
    assert s52.source == "futran_default" and s52.regulation_id is None and "monitoring" in s52.reason
    # laws for other features in the same places are offered but not pre-checked
    bipa = next(s for s in sugg if "Biometric Information Privacy Act" in s.label)
    assert not bipa.prechecked
    assert pre == [s.label for s in sugg][: len(pre)]  # pre-checked first


def test_suggest_no_ny_site_no_52c(db, matrix):
    org = make_org(db, industry="Healthcare", engagement_reason="Claims triage model")
    add_location(db, org, site_name="Chicago office", country_code="US", subdivision_code="US-IL", city="Chicago")
    sugg = suggest_requirements(db, org)
    assert not any("52-c" in s.label for s in sugg)
    assert any(s.prechecked and "HIPAA" in s.label for s in sugg)


def test_suggest_berlin_includes_eu_ai_act_and_gdpr(db, matrix):
    org = make_org(db, industry="Technology", engagement_reason="Customer service chatbot")
    add_location(db, org, site_name="Berlin office", country_code="DE", city="Berlin")
    sugg = suggest_requirements(db, org)
    pre = [s.label for s in sugg if s.prechecked]
    assert any(p.startswith("EU AI Act") for p in pre) and any(p.startswith("GDPR") for p in pre)
    assert any("Digital Services Act" in p for p in pre)  # chatbot keyword
    nist = next(s for s in sugg if "NIST" in s.label)  # Futran's default framework applies to every client
    assert nist.prechecked and nist.regulation_id is not None


def test_developer_only_excluded(db, matrix):
    org = _ny_chicago(db)
    labels = [s.label for s in suggest_requirements(db, org)]
    assert not any("RAISE Act" in label or "SB 315" in label for label in labels)


def test_out_of_scope_location_ignored(db, matrix):
    org = make_org(db, industry="Staffing", engagement_reason="hiring")
    add_location(db, org, site_name="Denver", country_code="US", subdivision_code="US-CO", city="Denver", in_scope=False)
    add_location(db, org, site_name="Chicago", country_code="US", subdivision_code="US-IL", city="Chicago")
    assert not any(s.jurisdiction_code == "US-CO" for s in suggest_requirements(db, org))
