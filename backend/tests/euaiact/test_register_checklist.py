"""Provider, importer and distributor duties on a register system's requirements checklist (review item 2):
- a role the legal reviewer signed off in G-08 decides which supplier-side duties apply;
- an item that already has an answer stays visible, editable and counted, flagged as a duty that may not apply;
- only unanswered supplier-side items are hidden on bought systems with no signed-off supplier role."""
from sqlalchemy import select

from app.euaiact import lawseed
from app.euaiact.models import EuAiActRecord
from app.regmaster.changes import apply_changes
from app.regmaster.models import ProposedChange, Requirement
from app.register.gate import gate_for
from app.register.models import RegisterSystem, RegisterSystemLaw, RequirementStatus
from app.register.requirements import checklist
from tests.factories import make_org, make_user


def _approved_library(db):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    lawseed.ensure_requirements(db)
    chief = make_user(db, make_org(db, type="futran"), roles=["chief_auditor"])
    apply_changes(db, list(db.scalars(select(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH))), chief.id)
    reg, v = lawseed.eu_ai_act(db)
    return reg, v


def _system(db, org, reg, **kw):
    s = RegisterSystem(organization_id=org.id, **kw)
    db.add(s)
    db.flush()
    db.add(RegisterSystemLaw(organization_id=org.id, register_system_id=s.id, regulation_id=reg.id))
    db.flush()
    return s


def _req(db, v, cite_start):
    return next(r for r in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id)) if (r.citation or "").startswith(cite_start))


def test_answered_provider_items_on_a_bought_chatbot_stay_shown_and_counted(matrix):
    db = matrix
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(db)
    reg, v = lawseed.eu_ai_act(db)
    org = make_org(db, name="Northbank Credit Union")
    bot = _system(db, org, reg, reference="AIS-001", name="Member chatbot", type="genai_chat_tool", sourcing="vendor", stage="live", decision_impact="none")
    # answers recorded before this release (Art. 50(1) was shown on bought systems then)
    answered = [_req(db, v, "EU AI Act Art. 4 "), _req(db, v, "EU AI Act Art. 50(1)"), _req(db, v, "EU AI Act Art. 50(3)")]
    for r, st in zip(answered, ("met", "partly_met", "not_applicable")):
        db.add(RequirementStatus(organization_id=org.id, register_system_id=bot.id, requirement_id=r.id, status=st, note="answered before"))
    db.flush()
    before = checklist(db, bot)
    gate_before = gate_for(db, bot)
    # the library gains the provider duties (approved by a Futran reviewer)
    chief = make_user(db, make_org(db, type="futran"), roles=["chief_auditor"])
    lawseed.ensure_requirements(db)
    apply_changes(db, list(db.scalars(select(ProposedChange).where(ProposedChange.batch_id == lawseed.BATCH))), chief.id)
    after = checklist(db, bot)
    stored = [r for r in after["rows"] if r["status"] != "not_met"]
    assert len(stored) == 3  # 3 statuses stored → 3 shown
    art50 = next(r for r in after["rows"] if r["citation"] == "EU AI Act Art. 50(1)")
    assert art50["status"] == "partly_met" and art50["note"] == "answered before" and art50["may_not_apply"]
    assert {r["code"] for r in before["rows"]} <= {r["code"] for r in after["rows"]}  # nothing that was shown disappears (rows are copied to the new version)
    assert {r["code"]: r["status"] for r in before["rows"]} == {r["code"]: r["status"] for r in after["rows"] if r["code"] in {x["code"] for x in before["rows"]}}
    added = [r for r in after["rows"] if r["code"] not in {x["code"] for x in before["rows"]}]
    assert [r["citation"] for r in added] == ["EU AI Act Art. 5(1)"] and not added[0]["gate"]  # the approved screen, never a blocker
    assert (after["met"], after["blocking"]) == (before["met"], before["blocking"])
    assert gate_for(db, bot)["state"] == gate_before["state"] and gate_for(db, bot)["requirements"] == gate_before["requirements"]


def test_unanswered_supplier_duties_hidden_on_bought_systems_and_shown_when_built(matrix):
    db = matrix
    reg, v = _approved_library(db)
    org = make_org(db, name="Northbank Credit Union")
    bought = _system(db, org, reg, reference="AIS-002", name="Hiring screening", type="vendor_app", sourcing="vendor", stage="proposed", decision_impact="consequential")
    built = _system(db, org, reg, reference="AIS-003", name="Credit model", type="in_house_model", sourcing="in_house", stage="proposed", decision_impact="consequential")

    def cites(s):
        return {r["citation"] for r in checklist(db, s)["rows"]}

    assert not {"EU AI Act Art. 9(1)", "EU AI Act Art. 50(1)", "EU AI Act Art. 23(1)"} & cites(bought)
    assert {"EU AI Act Art. 26(1)", "EU AI Act Art. 26(2)", "EU AI Act Art. 14(4)(e)"} <= cites(bought)
    assert "EU AI Act Art. 9(1)" in cites(built) and not {"EU AI Act Art. 23(1)", "EU AI Act Art. 24(1)"} & cites(built)


def test_a_signed_off_role_in_g08_decides(matrix):
    db = matrix
    reg, v = _approved_library(db)
    org = make_org(db, name="Northbank Credit Union")
    white_label = _system(db, org, reg, reference="AIS-004", name="Branded chatbot", type="genai_chat_tool", sourcing="vendor", stage="proposed", decision_impact="consequential")
    importer = _system(db, org, reg, reference="AIS-005", name="Imported scorer", type="vendor_app", sourcing="vendor", stage="proposed", decision_impact="consequential")
    db.add_all([
        EuAiActRecord(organization_id=org.id, register_system_id=white_label.id, role="provider", classification="high_risk_annex_iii", annex_iii_area="credit", signoff_status="signed_off"),
        EuAiActRecord(organization_id=org.id, register_system_id=importer.id, role="importer", classification="high_risk_annex_iii", annex_iii_area="credit", signoff_status="signed_off"),
    ])
    db.flush()
    wl = {r["citation"]: r for r in checklist(db, white_label)["rows"]}
    assert "EU AI Act Art. 9(1)" in wl and not wl["EU AI Act Art. 9(1)"]["may_not_apply"] and "EU AI Act Art. 23(1)" not in wl
    imp = {r["citation"] for r in checklist(db, importer)["rows"]}
    assert "EU AI Act Art. 23(1)" in imp and "EU AI Act Art. 9(1)" not in imp
    # an unsigned record decides nothing
    rec = db.scalar(select(EuAiActRecord).where(EuAiActRecord.register_system_id == importer.id))
    rec.signoff_status = "awaiting_signoff"
    db.flush()
    assert "EU AI Act Art. 23(1)" not in {r["citation"] for r in checklist(db, importer)["rows"]}


def test_the_prohibited_practice_screen_blocks_only_a_system_signed_off_as_prohibited(matrix):
    from app.register.requirements import gate_blockers

    db = matrix
    reg, v = _approved_library(db)
    org = make_org(db, name="Northbank Credit Union")
    s = _system(db, org, reg, reference="AIS-006", name="Emotion scanner", type="vendor_app", sourcing="vendor", stage="ready_for_go_live", decision_impact="none")
    assert not any("Art. 5" in b or "prohibited" in b.lower() for b in gate_blockers(db, s))
    db.add(EuAiActRecord(organization_id=org.id, register_system_id=s.id, role="deployer", classification="prohibited", signoff_status="signed_off"))
    db.flush()
    assert any("prohibited practices" in b for b in gate_blockers(db, s))
