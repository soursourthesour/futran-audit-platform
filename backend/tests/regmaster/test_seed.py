"""Regulatory master seed: the 21-role catalogue (§24.1) and cited requirements for the named laws (§25)."""
from datetime import date

from sqlalchemy import func, select

from app.laws.models import Regulation
from app.reference.models import Jurisdiction
from app.regmaster.models import CommitteeRule, LawRoleMap, LawVersion, Requirement, RoleCatalog, ScopeTest, Source
from app.regmaster.seed import ensure_versions, load_roles, seed_regmaster

SPEC_ROLES = [
    (1, "Accountable executive", "company", "development"),
    (2, "AI Governance Committee", "company", "program_setup"),
    (3, "AI Compliance Officer", "company", "development"),
    (4, "Data Protection Officer", "company", "go_live"),
    (5, "Grievance officer (India)", "company", "go_live"),
    (6, "AI Incident Response Lead", "company", "go_live"),
    (7, "AI literacy and training owner", "company", "go_live"),
    (8, "Vendor AI risk owner", "company", "procurement"),
    (9, "Records retention owner", "company", "go_live"),
    (10, "AI System Owner", "system", "development"),
    (11, "Technical owner", "system", "go_live"),
    (12, "Human oversight person", "system", "go_live"),
    (13, "Stop / disengage authority", "agent", "go_live"),
    (14, "Agent permissions approver", "agent", "go_live"),
    (15, "Explainability contact", "system", "go_live"),
    (16, "Appeals and correction reviewer", "system", "go_live"),
    (17, "Bias testing lead / independent auditor", "system", "go_live"),
    (18, "Impact assessment owner", "system", "go_live"),
    (19, "Transparency and notice owner", "system", "go_live"),
    (20, "Data and consent steward", "system", "development"),
    (21, "Worker representative contact", "system", "go_live"),
]


def test_role_catalogue_matches_spec_table(db):
    load_roles(db)
    rows = [(r.number, r.name, r.level, r.default_stage) for r in db.scalars(select(RoleCatalog).order_by(RoleCatalog.number))]
    assert rows == SPEC_ROLES


def test_ensure_versions_gives_every_current_law_version_one(matrix):
    db = matrix
    ensure_versions(db)
    current = db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None), Regulation.retired_in_version_id.is_(None))).all()
    assert current and all(r.current_version_id for r in current)
    assert db.get(LawVersion, current[0].current_version_id).version_no == 1


def _law(db, code, contains):
    j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == code))
    return db.scalar(select(Regulation).where(Regulation.jurisdiction_id == j.id, Regulation.short_name.contains(contains), Regulation.superseded_by_id.is_(None)))


def test_seed_attaches_cited_requirements_to_existing_laws(matrix):
    db = matrix
    seed_regmaster(db)
    ll144 = _law(db, "US-NYC", "Local Law 144")
    reqs = db.scalars(select(Requirement).where(Requirement.law_version_id == ll144.current_version_id)).all()
    assert {r.code for r in reqs} >= {"LL144-01", "LL144-03"}
    for r in db.scalars(select(Requirement)):
        assert r.citation and r.source_quote and r.source_url, r.code
    audit = next(r for r in reqs if r.code == "LL144-01")
    assert audit.citation == "NYC Admin. Code §20-871(a)(1)"
    assert db.get(RoleCatalog, audit.role_id).code == "bias_testing_lead"


def test_colorado_is_sb_26_189_not_sb_24_205(matrix):
    db = matrix
    seed_regmaster(db)
    co = _law(db, "US-CO", "SB 26-189")
    v = db.get(LawVersion, co.current_version_id)
    assert (v.signed_on, v.compliance_on, v.status) == (date(2026, 5, 14), date(2027, 1, 1), "enacted_not_in_force")
    reqs = db.scalars(select(Requirement).where(Requirement.law_version_id == v.id)).all()
    assert reqs and all("SB 26-189" in r.citation for r in reqs)
    assert all(r.verify_flag for r in reqs)  # section numbers come from the engrossed bill
    roles = {db.get(RoleCatalog, m.role_id).code: m.level for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == v.id))}
    assert "impact_assessment_owner" not in roles  # SB 26-189 removed impact assessments
    assert roles["explainability_contact"] == "required"


def test_seed_creates_cert_in_when_the_matrix_lacks_it(matrix):
    db = matrix
    seed_regmaster(db)
    certin = _law(db, "IN", "CERT-In")
    assert certin is not None and certin.origin == "manual"
    assert db.scalar(select(func.count()).select_from(Requirement).where(Requirement.law_version_id == certin.current_version_id)) == 4


def test_seed_is_idempotent(matrix):
    db = matrix
    seed_regmaster(db)
    counts = [db.scalar(select(func.count()).select_from(m)) for m in (RoleCatalog, Requirement, LawRoleMap, ScopeTest, CommitteeRule, Source, LawVersion)]
    seed_regmaster(db)
    assert [db.scalar(select(func.count()).select_from(m)) for m in (RoleCatalog, Requirement, LawRoleMap, ScopeTest, CommitteeRule, Source, LawVersion)] == counts


def test_sources_allowlist_marks_law_firms_secondary(matrix):
    db = matrix
    seed_regmaster(db)
    kinds = {s.domain: s.kind for s in db.scalars(select(Source).where(Source.regulation_id.is_(None)))}
    assert kinds["eur-lex.europa.eu"] == "official"
    assert kinds["www.hklaw.com"] == "secondary"


def test_law_replaced_by_a_matrix_edit_carries_its_content_forward(matrix):
    from app.laws.service import edit_law
    from tests.factories import make_org, make_user

    db = matrix
    seed_regmaster(db)
    old = _law(db, "US-NYC", "Local Law 144")
    old_v = db.get(LawVersion, old.current_version_id)
    admin = make_user(db, make_org(db, type="futran"), roles=["admin"], name="Ada Admin")
    new = edit_law(db, admin, old.id, {"obligations_text": "Yearly bias audit"})
    ensure_versions(db)
    v = db.get(LawVersion, new.current_version_id)
    assert v.version_no == old_v.version_no + 1 and v.regulation_id == new.id
    assert {r.code for r in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id))} >= {"LL144-01", "LL144-05"}
    assert new.label == "NYC LL144" or new.label is None  # label is copied by edit_law with the other columns
