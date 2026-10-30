"""Regulatory master API: M1, M1a, M1b, M2, M4, M5 and the intro letter, with §25.7 permissions."""
from sqlalchemy import select

from app.initiation.models import PackageDocument
from app.mail.models import OutboxMessage
from app.regmaster.models import ClientGeography, IntroLetter, ProposedChange
from app.regmaster.seed import find_law
from tests.factories import login_as, make_org, make_user

API = "/api/v1"


def _futran(db, role, name):
    from app.tenancy.models import Organization

    f = db.scalar(select(Organization).where(Organization.type == "futran"))
    u = make_user(db, f, roles=[role], name=name, email=f"{name.split()[0].lower()}@futran.test")
    db.commit()
    return u


def test_law_library_lists_curated_laws_with_kpis(client, db, seeded):
    login_as(client, db, seeded["aud"])
    r = client.get(f"{API}/reg/laws")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpis"]["laws"] >= 10 and body["kpis"]["requirements"] >= 50
    rows = [x for g in body["groups"] for x in g["laws"]]
    co = next(x for x in rows if x["short_name"] == "SB 26-189")
    assert co["status"] == "enacted_not_in_force" and co["requirement_count"] == 8 and co["verify"]
    assert client.get(f"{API}/reg/laws?show=all").json()["kpis"]["shown"] > body["kpis"]["shown"]


def test_client_users_cannot_read_the_master(client, db, seeded):
    org = make_org(db, name="Other Co")
    u = make_user(db, org, roles=["caico"], name="Cli Ent", email="c@other.test")
    db.commit()
    login_as(client, db, u)
    assert client.get(f"{API}/reg/laws").status_code in (403, 404)
    assert client.get(f"{API}/reg/roles").status_code in (403, 404)


def test_law_record_has_requirements_roles_tests_and_history(client, db, seeded):
    login_as(client, db, seeded["chief"])
    reg = find_law(db, "US-CO", "^SB 26-189$")
    r = client.get(f"{API}/reg/laws/{reg.id}")
    assert r.status_code == 200, r.text
    b = r.json()
    assert [q["code"] for q in b["requirements"]][:2] == ["CO-01", "CO-02"]
    assert b["version"]["signed_on"] == "2026-05-14"
    assert any(m["role"] == "explainability_contact" and m["level"] == "required" for m in b["role_maps"])
    assert len(b["scope_tests"]) == 3 and b["history"][0]["version_no"] == 1


def test_admin_edit_becomes_a_proposal(client, db, seeded):
    admin = _futran(db, "admin", "Ada Admin")
    login_as(client, db, admin)
    reg = find_law(db, "US-CO", "^SB 26-189$")
    r = client.post(f"{API}/reg/laws/{reg.id}/proposals", json={"changes": [{"field_path": "law.cure_period", "new_value": "30 days"}], "summary": "Shorter cure period", "reason": "Test"})
    assert r.status_code == 200, r.text
    assert db.scalar(select(ProposedChange).where(ProposedChange.regulation_id == reg.id)).status == "pending"
    law = client.get(f"{API}/reg/laws/{reg.id}").json()
    assert law["version"]["cure_period"].startswith("60 days") and law["pending"][0]["summary"] == "Shorter cure period"


def test_auditor_suggestion_needs_a_source(client, db, seeded):
    login_as(client, db, seeded["aud"])
    reg = find_law(db, "US-CO", "^SB 26-189$")
    r = client.post(f"{API}/reg/laws/{reg.id}/proposals", json={"changes": [{"field_path": "law.cure_period", "new_value": "30 days"}], "summary": "x"})
    assert r.status_code == 422
    r = client.post(f"{API}/reg/laws/{reg.id}/proposals", json={"changes": [{"field_path": "law.cure_period", "new_value": "30 days"}], "summary": "x", "source_url": "https://leg.colorado.gov/bills/sb26-189", "source_quote": "sixty days"})
    assert r.status_code == 200 and r.json()["proposals"][0]["origin"] == "auditor_suggestion"


def test_bulk_edit_applies_tracking_and_proposes_content(client, db, seeded):
    login_as(client, db, seeded["chief"])
    ids = [find_law(db, c, p).id for c, p in (("US-CO", "^SB 26-189$"), ("US-NYC", "Local Law 144"))]
    pre = client.post(f"{API}/reg/laws/bulk/preview", json={"ids": ids, "role_levels": [{"role": "human_oversight_person", "level": "required", "needed_by_stage": "go_live"}]})
    assert pre.status_code == 200, pre.text
    warn = pre.json()["roles"][0]
    assert warn["not_set_on"] == ["NYC LL144"]
    r = client.post(f"{API}/reg/laws/bulk", json={"ids": ids, "tracking": {"review_due_on": "2026-11-15", "refresh_every_days": 14}, "role_levels": [{"role": "human_oversight_person", "level": "required", "needed_by_stage": "go_live", "skip": [ids[1]]}], "reason": "Aligning human review"})
    assert r.status_code == 200, r.text
    assert r.json()["tracking_applied"] == 2 and r.json()["proposals"] == 0  # Colorado already requires it; NYC skipped
    r = client.post(f"{API}/reg/laws/bulk", json={"ids": ids, "role_levels": [{"role": "worker_rep_contact", "level": "recommended", "needed_by_stage": "go_live"}]})
    assert r.status_code == 422  # reason required


def test_role_matrix(client, db, seeded):
    login_as(client, db, seeded["aud"])
    r = client.get(f"{API}/reg/roles?laws=all")
    assert r.status_code == 200, r.text
    b = r.json()
    assert len(b["roles"]) == 21 and b["roles"][0]["name"] == "Accountable executive"
    nyc = next(x for x in b["laws"] if x["label"] == "NYC LL144")
    assert b["cells"]["bias_testing_lead"][nyc["id"]]["level"] == "required"
    assert any(c["committee_type"] == "ai_governance_committee" for c in b["committees"])


def test_wizard_step_two_writes_client_geography(client, db, seeded, submitted):
    cid, e = submitted()
    geos = db.scalars(select(ClientGeography).where(ClientGeography.organization_id == cid)).all()
    from app.reference.models import Jurisdiction

    codes = {db.get(Jurisdiction, g.jurisdiction_id).code for g in geos}
    assert {"US-NYC", "US-IL"} <= codes and all(g.basis == "office" and g.source == "wizard" for g in geos)


def test_applicability_screen_and_letter_flow(client, db, seeded, submitted):
    cid, e = submitted()
    login_as(client, db, seeded["chief"])
    client.get(f"{API}/clients/{cid}/package")  # package generated at submit-for-approval
    r = client.get(f"{API}/clients/{cid}/applicability")
    assert r.status_code == 200, r.text
    b = r.json()
    ins = {x["label"] for x in b["laws_in"]}
    assert {"NYC LL144", "Illinois HB 3773"} <= ins
    co = next(x for x in b["laws_out"] if x["label"] == "Colorado")
    assert co["reason"] == "No Colorado operations or residents"
    assert any(r["code"] == "bias_testing_lead" and r["level"] == "required" for r in b["roles"])
    # add a geography: Colorado customers bring SB 26-189 in
    r = client.post(f"{API}/clients/{cid}/geographies", json={"jurisdiction_code": "US-CO", "basis": "customers"})
    assert r.status_code == 200, r.text
    assert "Colorado" in {x["label"] for x in client.get(f"{API}/clients/{cid}/applicability").json()["laws_in"]}
    # draft, edit, approve, send
    d = client.post(f"{API}/clients/{cid}/letters").json()
    assert d["status"] == "draft" and d["version_no"] == 1 and "NYC LL144" in d["html"]
    assert client.patch(f"{API}/clients/{cid}/letters/{d['id']}", json={"opening": "Thank you for choosing Futran."}).status_code == 200
    admin = _futran(db, "admin", "Ada Admin")
    login_as(client, db, admin)
    assert client.post(f"{API}/clients/{cid}/letters/{d['id']}/approve").status_code == 403
    login_as(client, db, seeded["chief"])
    a = client.post(f"{API}/clients/{cid}/letters/{d['id']}/approve")
    assert a.status_code == 200, a.text
    assert a.json()["status"] == "approved" and a.json()["file_id"]
    doc = db.scalar(select(PackageDocument).where(PackageDocument.engagement_id == e.id, PackageDocument.template_key == "intro_letter", PackageDocument.deleted_at.is_(None)))
    assert doc is not None and doc.item == 8 and doc.pdf_file_id == a.json()["file_id"]
    assert client.get(f"{API}/files/{a.json()['file_id']}").content[:4] == b"%PDF"
    s = client.post(f"{API}/clients/{cid}/letters/{d['id']}/send")
    assert s.status_code == 200, s.text
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.related_type == "IntroLetter", OutboxMessage.related_id == d["id"]))
    assert msg is not None and msg.to == ["maria@abc.test"] and "AI governance requirements" in msg.subject
    # a later draft is version 2 and supersedes the sent letter
    d2 = client.post(f"{API}/clients/{cid}/letters").json()
    assert d2["version_no"] == 2 and db.get(IntroLetter, d2["id"]).supersedes_id == d["id"]


def test_draft_with_claude_is_disabled_without_a_key(client, db, seeded):
    login_as(client, db, seeded["chief"])
    r = client.post(f"{API}/reg/laws/draft", json={"ref": "https://leg.colorado.gov/bills/sb26-189"})
    assert r.status_code == 409 and "Anthropic API key" in r.json()["detail"]
    assert client.get(f"{API}/reg/laws").json()["claude_available"] is False


class FakeClaude:
    def __init__(self, settings):
        pass

    def research(self, prompt):
        return """```json
{"short_name": "Utah AI Policy Act", "citation": "SB 149 (2024)", "jurisdiction_code": "US-UT", "type": "statute", "binding": true, "status": "in_force",
 "applies_to": ["deployer"], "scope_text": "Businesses that use generative AI with consumers", "sources": [{"name": "Utah Legislature", "url": "https://le.utah.gov/~2024/bills/static/SB0149.html"}],
 "requirements": [{"code": "UT-01", "text": "Disclose generative AI when asked", "role": "transparency_notice_owner", "citation": "Utah Code 13-2-12", "source_quote": "clearly and conspicuously disclose", "source_url": "https://le.utah.gov/~2024/bills/static/SB0149.html"},
                  {"code": "UT-02", "text": "Unquoted duty", "citation": "x"}]}
```"""


def test_draft_with_claude_fills_the_form_and_saves_nothing(client, db, seeded, settings):
    settings.anthropic_api_key = "test-key"
    client.app.state.settings = settings
    client.app.state.claude_factory = FakeClaude
    login_as(client, db, seeded["chief"])
    before = db.scalar(select(ProposedChange.id).limit(1))
    r = client.post(f"{API}/reg/laws/draft", json={"ref": "Utah SB 149"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["draft"]["short_name"] == "Utah AI Policy Act" and [q["code"] for q in b["draft"]["requirements"]] == ["UT-01"]
    assert any("UT-02" in w for w in b["warnings"]) and any("not on the official source list" in w for w in b["warnings"])
    assert db.scalar(select(ProposedChange.id).limit(1)) == before
    # sending the form for approval creates one proposal for the Chief Auditor; no law exists yet
    r = client.post(f"{API}/reg/laws/new", json={"law": {**b["draft"], "jurisdiction_code": "US-UT"}, "drafted_with_claude": True})
    assert r.status_code == 200, r.text
    pc = db.get(ProposedChange, r.json()["id"])
    assert pc.change_type == "new_law" and pc.origin == "claude_draft" and pc.status == "pending" and pc.regulation_id is None


def test_governance_request_reads_headline_roles_from_catalogue(client, db, seeded, submitted):
    from app.governance.service import catalog_roles

    titles = {c["code"]: c["title"] for c in catalog_roles(db)}
    assert titles["GR-05"] == "Human oversight person"
    assert titles["GR-01"] == "AI Governance Committee"
    assert titles["GR-08"] == "EU representative contact"  # no catalogue counterpart; keeps its own text
