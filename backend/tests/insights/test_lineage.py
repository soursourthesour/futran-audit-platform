"""Lineage (F6): "Why is this a finding?" from the finding back to the law, and "What proves this control?" from a
control to its evidence, with the other controls the same evidence satisfies (F16 cross-framework reuse)."""
from sqlalchemy import select

from app.engagements.models import ClientRequirement
from app.findings.service import create_finding
from app.laws.models import Regulation
from app.questionnaire.models import ChecklistItem, ChecklistResult
from app.regmaster.seed import seed_regmaster
from tests.factories import login_as


def _ll144_in_scope(db, e):
    seed_regmaster(db)
    reg = db.scalar(select(Regulation).where(Regulation.label == "NYC LL144")) or db.scalar(select(Regulation).where(Regulation.short_name.ilike("%Local Law 144%")))
    if not db.scalar(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.regulation_id == reg.id)):
        db.add(ClientRequirement(organization_id=e.client_id, engagement_id=e.id, regulation_id=reg.id, source="manual", in_scope=True))
    db.flush()
    return reg


def _finding(db, people, e, s):
    return create_finding(db, people["aud"], e, {"title": "No bias testing on the résumé screener", "severity": "high", "template_section": "6.2", "ai_system_id": s.id,
                                                 "source_question_ids": ["6.2.01"], "control_refs": ["NIST_AI_RMF MEASURE 2.11"], "proposed_owner": "Head of HR"})


def test_why_is_this_a_finding_walks_back_to_the_law_and_forward_to_remediation(client, db, ats, people):
    from datetime import date

    from app.remediation.models import ManagementResponse, RemediationItem

    cid, e, maria, s = ats
    reg = _ll144_in_scope(db, e)
    f = _finding(db, people, e, s)
    mr = ManagementResponse(organization_id=cid, engagement_id=e.id, finding_id=f.id, response="agree", planned_action="Commission an independent bias audit")
    db.add(mr)
    db.flush()
    db.add(RemediationItem(organization_id=cid, engagement_id=e.id, finding_id=f.id, response_id=mr.id, action="Commission an independent bias audit", owner_name="Priya Shah",
                           due_date=date(2026, 12, 31), status="open"))
    db.commit()
    login_as(client, db, people["aud"])
    r = client.get(f"/api/v1/findings/{f.id}/lineage")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["finding"]["ref"] == f.ref
    resp = out["responses"][0]
    assert (resp["code"], resp["answer"], resp["source"]) == ("6.2.01", "No", "Lee Park, HR systems lead")
    assert [c["code"] for c in out["checklist"]] == ["6.4.03", "6.4.04", "6.4.10"]
    assert "NIST AI RMF MEASURE 2.11" in [c["label"] for c in out["controls"]]
    laws = {x["regulation"]: x for x in out["obligations"]}
    ll = laws[reg.short_name]
    assert ll["kind"] == "requirement" and {i["code"] for i in ll["items"]} >= {"LL144-01", "LL144-02"}
    assert out["evidence"] == [] and out["evidence_note"] == "No evidence is linked to these answers or checklist items."
    assert out["remediation"][0]["action"] == "Commission an independent bias audit" and out["remediation"][0]["owner"] == "Priya Shah"


def test_approved_obligations_take_the_place_of_requirements(client, db, ats, people):
    from app.ai.models import Obligation

    cid, e, maria, s = ats
    reg = _ll144_in_scope(db, e)
    f = _finding(db, people, e, s)
    db.add(Obligation(organization_id="futran", regulation_id=reg.id, text="An employer using an AEDT must have an independent bias audit within the past year and publish a summary.",
                      actor="employer", citation="Admin. Code § 20-871(a)", question_ids=["6.2.01"], status="approved"))
    db.add(Obligation(organization_id="futran", regulation_id=reg.id, text="A suggestion nobody approved", actor="employer", question_ids=["6.2.01"], status="suggested"))
    db.commit()
    login_as(client, db, people["aud"])
    ll = next(x for x in client.get(f"/api/v1/findings/{f.id}/lineage").json()["obligations"] if x["regulation"] == reg.short_name)
    assert ll["kind"] == "obligation" and [i["text"] for i in ll["items"]] == ["An employer using an AEDT must have an independent bias audit within the past year and publish a summary."]


def test_what_proves_this_control_lists_the_evidence_and_everything_else_it_satisfies(client, db, ats, people, settings):
    from app.files.service import upload

    cid, e, maria, s = ats
    _ll144_in_scope(db, e)
    item = db.scalar(select(ChecklistItem).where(ChecklistItem.code == "6.4.03"))
    f = upload(db, client.app.state.settings, people["aud"], data=b"%PDF-1.4 bias report", filename="bias-audit.pdf", content_type=None, organization_id=cid, engagement_id=e.id, linked_type="evidence")
    db.add(ChecklistResult(organization_id=cid, engagement_id=e.id, ai_system_id=s.id, checklist_item_id=item.id, confirmed=True, evidence_ids=[f.id]))
    db.commit()
    login_as(client, db, people["aud"])
    r = client.get(f"/api/v1/systems/{s.id}/lineage/control/6.4.03")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["control"]["code"] == "6.4.03" and out["confirmed"] is True
    assert out["evidence"] == [{"id": f.id, "filename": "bias-audit.pdf", "via": "Checklist 6.4.03"}]
    assert {"NYC Local Law 144 6 RCNY § 5-301", "NIST AI RMF MEASURE 2.11", "EU AI Act Art. 10"} <= {c["label"] for c in out["also_satisfies"]["controls"]}
    assert {"LL144-01", "NIST-MS2.11"} <= {x["code"] for x in out["also_satisfies"]["requirements"]}
    login_as(client, db, maria)
    assert client.get(f"/api/v1/systems/{s.id}/lineage/control/6.4.03").status_code in (403, 404)


def test_the_report_has_a_heat_map_and_a_lineage_appendix(client, db, ats, people):
    from app.findings.models import Finding
    from app.reports.service import build_report

    cid, e, maria, s = ats
    _ll144_in_scope(db, e)
    f = _finding(db, people, e, s)
    f.status = "approved"
    db.commit()
    md = build_report(db, e, "v0.1").markdown
    assert "## Appendix D. Risk heat map" in md and "## Appendix E. Lineage of findings" in md
    assert "| Maturity 1 | Low | Medium | High | Critical |" in md and "Not placed until their inherent risk and maturity are both scored: SYS-001" in md
    assert f"### {f.ref} " in md and "LL144-01" in md
    assert db.scalar(select(Finding).where(Finding.id == f.id)).status == "approved"
