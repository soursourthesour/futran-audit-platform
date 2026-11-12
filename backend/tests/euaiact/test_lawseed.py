"""Spec B8: the EU AI Act requirements the law library lacks reach it only as proposed changes that a Futran reviewer
approves (§25.1 principle 1) in Refresh and review, with their client impact. Start-up proposes them once and never
again; nothing on a client's systems changes until the proposal is approved."""
from datetime import date

from sqlalchemy import func, select

from app.audit_log.models import AuditLog
from app.euaiact import lawseed, rules
from app.regmaster.changes import apply_changes, decide
from app.regmaster.models import ChangeImpact, ClientLawApplicability, LawVersion, ProposedChange, Requirement
from app.register.gate import gate_for
from app.register.models import RegisterSystem, RegisterSystemLaw, RequirementStatus
from app.register.requirements import checklist
from tests.factories import make_org, make_user

NEW_REFS = {"5", "9", "10", "11", "12", "13", "14(1)", "15", "17", "23", "24", "43", "47", "49", "53", "72"}


def _world(db):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    reg, v = lawseed.eu_ai_act(db)
    org = make_org(db, name="Northbank Credit Union")
    db.add(ClientLawApplicability(organization_id=org.id, regulation_id=reg.id, law_version_id=v.id, in_scope=True, reason_text="Serves EU members"))
    systems = [
        RegisterSystem(organization_id=org.id, reference="AIS-001", name="Member chatbot", type="genai_chat_tool", sourcing="vendor", stage="live", decision_impact="none"),
        RegisterSystem(organization_id=org.id, reference="AIS-002", name="Hiring screening", type="vendor_app", sourcing="vendor", stage="ready_for_go_live", decision_impact="consequential"),
        RegisterSystem(organization_id=org.id, reference="AIS-003", name="Credit model", type="in_house_model", sourcing="in_house", stage="ready_for_go_live", decision_impact="consequential"),
    ]
    db.add_all(systems)
    db.flush()
    for s in systems:
        db.add(RegisterSystemLaw(organization_id=org.id, register_system_id=s.id, regulation_id=reg.id))
    db.flush()
    return reg, v, org, systems


def _snapshot(db, systems):
    out = {}
    for s in systems:
        c = checklist(db, s)
        g = gate_for(db, s)
        out[s.id] = ([(r["code"], r["status"]) for r in c["rows"]], c["total"], c["met"], c["blocking"], g["state"], g["requirements"])
    return out


def test_start_up_proposes_the_missing_articles_and_changes_nothing_on_clients(matrix):
    db = matrix
    reg, v, org, systems = _world(db)
    before = _snapshot(db, systems)
    rows_before = db.scalar(select(func.count()).select_from(Requirement).where(Requirement.law_version_id == v.id))

    out = lawseed.ensure_requirements(db)
    assert {p["ref"] for p in out["proposed"]} == NEW_REFS and out["missing_law"] is False
    assert db.get(type(reg), reg.id).current_version_id == v.id  # no new version until a reviewer approves
    assert db.scalar(select(func.count()).select_from(Requirement).where(Requirement.law_version_id == v.id)) == rows_before
    assert _snapshot(db, systems) == before  # checklists, totals, Met counts, blockers and finding status identical

    pcs = list(db.scalars(select(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH)))
    assert len(pcs) == 16 and {p.status for p in pcs} == {"pending"} and {p.origin for p in pcs} == {"platform_seed"}
    assert all(p.field_path.startswith("requirement.EU-") and p.base_version_id == v.id and p.new_value["source_quote"] for p in pcs)
    by_ref = {rules.article_refs(p.new_value["citation"])[0].split("(")[0]: p.new_value for p in pcs}
    assert by_ref["23"]["applies_to"] == ["importer"] and by_ref["24"]["applies_to"] == ["distributor"] and by_ref["9"]["applies_to"] == ["provider"]
    assert by_ref["5"]["needed_by_stage"] == "ongoing"  # a screen, never a go-live blocker
    assert db.scalar(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pcs[0].id, ChangeImpact.organization_id == org.id)) is not None


def test_proposed_once_never_again_even_after_rejection(matrix):
    db = matrix
    _world(db)
    lawseed.ensure_requirements(db)
    again = lawseed.ensure_requirements(db)
    assert again["proposed"] == [] and again["already_seeded"] is True
    chief = make_user(db, make_org(db, type="futran"), roles=["chief_auditor"])
    for pc in db.scalars(select(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH)):
        decide(db, pc, "rejected", chief.id, "Not now")
    assert lawseed.ensure_requirements(db)["proposed"] == []
    assert db.scalar(select(func.count()).select_from(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH)) == 16


def test_approving_the_proposal_applies_it_as_a_new_version(matrix):
    db = matrix
    reg, v, _org, (chatbot, hiring, credit) = _world(db)
    lawseed.ensure_requirements(db)
    chief = make_user(db, make_org(db, type="futran"), roles=["chief_auditor"])
    pcs = list(db.scalars(select(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH)))
    new = apply_changes(db, pcs, chief.id, note="EU AI Act provider duties for G-08")
    assert new.id != v.id and new.approved_by == chief.id
    assert db.scalar(select(func.count()).select_from(Requirement).where(Requirement.law_version_id == new.id)) == 29
    for o in rules.data()["obligations"]:  # every obligation on the workspace now has a library row
        assert lawseed.library_row(db, o["ref"]) is not None, o["key"]
    # approved content reaches the systems; which supplier rows apply is decided by the role signed off in G-08
    cites = lambda s: {r["citation"] for r in checklist(db, s)["rows"]}  # noqa: E731
    assert "EU AI Act Art. 9(1)" in cites(credit) and "EU AI Act Art. 9(1)" in cites(hiring)
    assert all("Art. 5(" not in b for b in gate_for(db, chatbot)["requirements"])
    assert lawseed.ensure_requirements(db)["proposed"] == []


def test_rows_an_earlier_build_inserted_directly_are_withdrawn_and_proposed(matrix):
    db = matrix
    reg, v, org, (chatbot, *_rest) = _world(db)
    stray = Requirement(law_version_id=v.id, code="EU-14", order=50, text="Risk management", citation="EU AI Act Art. 9(1)", verify_flag=True)
    kept = Requirement(law_version_id=v.id, code="EU-15", order=51, text="Data governance", citation="EU AI Act Art. 10(1)", verify_flag=True)
    db.add_all([stray, kept])
    db.flush()
    db.add(RequirementStatus(organization_id=org.id, register_system_id=chatbot.id, requirement_id=kept.id, status="met"))  # someone answered it: keep
    db.add(AuditLog(action="law.requirements_seeded", object_type="Regulation", object_id=reg.id, organization_id="futran",
                    after={"added": [{"ref": "9", "code": "EU-14"}, {"ref": "10", "code": "EU-15"}]}, summary="old build"))
    db.flush()
    out = lawseed.ensure_requirements(db)
    assert db.get(Requirement, stray.id) is None and db.get(Requirement, kept.id) is not None
    assert out["withdrawn"] == ["EU-14"]
    refs = {p["ref"] for p in out["proposed"]}
    assert "9" in refs and "10" not in refs  # Art. 10 stays covered by the answered row


def test_no_eu_ai_act_in_the_library_changes_nothing(db):
    out = lawseed.ensure_requirements(db)
    assert out["proposed"] == [] and out["missing_law"] is True
    assert db.scalar(select(ProposedChange.id)) is None


def test_platform_start_up_leaves_client_systems_identical(matrix, app):
    db = matrix
    reg, v, org, systems = _world(db)
    db.commit()
    before = _snapshot(db, systems)
    lawseed.seed_on_start(app)
    lawseed.seed_on_start(app)  # a restart
    db.expire_all()
    assert _snapshot(db, systems) == before
    assert db.scalar(select(func.count()).select_from(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH)) == 16
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == lawseed.MARKER)) == 1


def test_the_proposals_appear_in_refresh_and_review_and_approving_there_applies_them(matrix, client):
    from tests.factories import login_as

    db = matrix
    reg, v, _org, _systems = _world(db)
    lawseed.ensure_requirements(db)
    chief = make_user(db, make_org(db, type="futran"), roles=["chief_auditor"], email="chief@futran.test")
    db.commit()
    login_as(client, db, chief)
    items = [c for c in client.get("/api/v1/reg/changes").json()["items"] if c["field_path"].startswith("requirement.EU-")]
    assert len(items) == 16 and all(c["origin"] == "platform_seed" for c in items)
    r = client.post("/api/v1/reg/changes/bulk", json={"ids": [c["id"] for c in items], "action": "approve", "note": "Checked against EUR-Lex"})
    assert r.status_code == 200 and all(x["ok"] for x in r.json()["results"]), r.text
    db.expire_all()
    cur = lawseed.eu_ai_act(db)[1]
    assert cur.id != v.id and db.scalar(select(func.count()).select_from(Requirement).where(Requirement.law_version_id == cur.id)) == 29
