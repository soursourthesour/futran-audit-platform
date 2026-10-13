import pytest
from sqlalchemy import select

from app.reference.catalogs import load_catalogs
from app.reference.frameworks import load_frameworks
from app.reference.models import (
    DocumentCatalogItem,
    DocumentTemplate,
    Framework,
    FrameworkControl,
    GovernanceCatalogItem,
    RiskMethodology,
)
from app.reference.templates import edit_template, load_templates, render_template
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def seeded(db):
    load_frameworks(db)
    load_catalogs(db)
    load_templates(db)
    return db


def test_frameworks_and_controls(seeded):
    codes = set(seeded.scalars(select(Framework.code)))
    assert codes == {"OECD", "NIST_AI_RMF", "EU_AI_ACT", "ISO_42001"}
    oecd = {c.code for c in seeded.scalars(select(FrameworkControl).join(Framework).where(Framework.code == "OECD"))}
    assert oecd == {"1.1", "1.2", "1.3", "1.4", "1.5"}
    nist = {c.code for c in seeded.scalars(select(FrameworkControl).join(Framework).where(Framework.code == "NIST_AI_RMF"))}
    assert {"GOVERN 2", "GOVERN 6", "MEASURE 2.9", "MEASURE 2.11", "MANAGE 4"} <= nist


def test_governance_roles_8_with_controls(seeded):
    roles = seeded.scalars(select(GovernanceCatalogItem).where(GovernanceCatalogItem.kind == "role")).all()
    assert len(roles) == 8
    bias = next(r for r in roles if r.title == "Bias and fairness review committee")
    assert set(bias.control_refs) == {"OECD 1.2", "NIST_AI_RMF MEASURE 2.11", "EU_AI_ACT Art. 10"}
    eu_rep = next(r for r in roles if r.title == "EU representative contact")
    assert eu_rep.conditional == "eu_operations"


def test_governance_documents_5_plus_5_security(seeded):
    docs = seeded.scalars(select(GovernanceCatalogItem).where(GovernanceCatalogItem.kind == "document")).all()
    sec = seeded.scalars(select(GovernanceCatalogItem).where(GovernanceCatalogItem.kind == "security_document")).all()
    assert len(docs) == 5 and len(sec) == 5
    assert any(d.title == "AI acceptable use policy" for d in docs)


def test_document_catalog_6_categories_and_per_system_flags(seeded):
    items = seeded.scalars(select(DocumentCatalogItem)).all()
    assert {i.category for i in items} == {1, 2, 3, 4, 5, 6}
    per_system = {i.title for i in items if i.per_system}
    assert per_system == {
        "Model card",
        "Model validation report",
        "Bias and fairness test report",
        "Data protection impact assessment (DPIA)",
        "Model monitoring reports (last 6 months)",
    }
    assert len(items) == 36


def test_risk_weights_sum_to_1(seeded):
    m = seeded.scalar(select(RiskMethodology).where(RiskMethodology.version == "1.0"))
    assert abs(sum(f["weight"] for f in m.factor_weights.values()) - 1.0) < 1e-9
    for build, weights in m.domain_weights_by_build_type.items():
        assert abs(sum(weights.values()) - 1.0) < 1e-9, build
    assert m.bands == [{"min": 75, "rating": "critical"}, {"min": 50, "rating": "high"}, {"min": 25, "rating": "medium"}, {"min": 0, "rating": "low"}]
    assert m.factor_weights["decision_type"]["weight"] == 0.20
    assert m.domain_weights_by_build_type["vendor"]["vendor_risk"] == 0.15


def test_templates_seeded_and_render(seeded):
    keys = set(seeded.scalars(select(DocumentTemplate.key).where(DocumentTemplate.active.is_(True))))
    assert {"engagement_letter", "roles_note", "user_csv", "department_csv", "data_notice", "getting_started", "governance_request", "document_request_email", "management_representation"} <= keys
    text = render_template(seeded, "management_representation", {"client": {"name": "ABC Corp"}})
    assert text.startswith("To the best of our knowledge, the AI inventory submitted for ABC Corp is complete and accurate")


def test_template_version_bump_on_edit(seeded):
    f = make_org(seeded, type="futran")
    admin = make_user(seeded, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    t2 = edit_template(seeded, admin, "management_representation", "Revised text for {{ client.name }}.")
    assert t2.version == 2 and t2.active
    old = seeded.scalar(select(DocumentTemplate).where(DocumentTemplate.key == "management_representation", DocumentTemplate.version == 1))
    assert old.active is False
    assert render_template(seeded, "management_representation", {"client": {"name": "X"}}) == "Revised text for X."


def test_template_edit_rejects_broken_jinja(seeded):
    from app.core.errors import Invalid

    f = make_org(seeded, type="futran")
    admin = make_user(seeded, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    with pytest.raises(Invalid):
        edit_template(seeded, admin, "management_representation", "Broken {{ client.name ")


def test_loaders_idempotent(seeded):
    n = seeded.query(DocumentCatalogItem).count(), seeded.query(FrameworkControl).count(), seeded.query(DocumentTemplate).count()
    load_frameworks(seeded)
    load_catalogs(seeded)
    load_templates(seeded)
    assert (seeded.query(DocumentCatalogItem).count(), seeded.query(FrameworkControl).count(), seeded.query(DocumentTemplate).count()) == n


def test_templates_api_admin_only(client, db, seeded):
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    aud = make_user(db, f, roles=["auditor"], name="Al Aud", email="al@f.test")
    db.commit()
    login_as(client, db, aud)
    assert client.get("/api/v1/admin/templates").status_code == 200
    assert client.put("/api/v1/admin/templates/roles_note", json={"body": "x"}).status_code == 403
    login_as(client, db, admin)
    r = client.put("/api/v1/admin/templates/roles_note", json={"body": "New roles note for {{ client.name }}."})
    assert r.status_code == 200 and r.json()["version"] == 2
