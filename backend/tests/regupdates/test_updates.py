"""Screen 26 (Futran): curated regulatory updates with a second reviewer, matching to clients, impact, A1 alerts, S1
opportunities, the law-change proposal and the read-only law-library items."""
from sqlalchemy import select

from app.clientalerts.models import AlertRule, AlertSend
from app.impact.models import ReassessmentTrigger
from app.regmaster.models import ProposedChange
from app.regupdates.models import RegulatoryAlert, RegulatoryUpdate
from app.register.models import RegisterSystemLaw
from app.sales.models import Opportunity
from tests.factories import login_as
from tests.regupdates.conftest import nyc_enforcement, publish


def test_a_draft_needs_a_second_reviewer_who_is_not_the_author(client, db, world):
    login_as(client, db, world["legal"])
    r = client.post("/api/v1/reg/updates", json=nyc_enforcement(world))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "draft" and d["reference"] == "RU-001"
    assert client.post(f"/api/v1/reg/updates/{d['id']}/submit").json()["status"] == "awaiting_review"
    assert client.post(f"/api/v1/reg/updates/{d['id']}/review", json={"approve": True}).status_code == 403  # the author
    login_as(client, db, world["legal2"])
    r = client.post(f"/api/v1/reg/updates/{d['id']}/review", json={"approve": True, "note": "Matches the audit report."})
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["reviewed_by_name"] == "Kim Legal"


def test_a_reviewer_can_send_a_draft_back_with_a_reason(client, db, world):
    login_as(client, db, world["legal"])
    uid = client.post("/api/v1/reg/updates", json=nyc_enforcement(world)).json()["id"]
    client.post(f"/api/v1/reg/updates/{uid}/submit")
    login_as(client, db, world["chief"])
    assert client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": False}).status_code == 422
    r = client.post(f"/api/v1/reg/updates/{uid}/review", json={"approve": False, "note": "Quote the audit's figures."})
    assert r.json()["status"] == "draft" and r.json()["review_note"] == "Quote the audit's figures."


def test_submitting_needs_a_source(client, db, world):
    login_as(client, db, world["legal"])
    uid = client.post("/api/v1/reg/updates", json=nyc_enforcement(world, source_url=None)).json()["id"]
    r = client.post(f"/api/v1/reg/updates/{uid}/submit")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "source_url"


def test_publishing_matches_clients_by_geography_and_ai_feature(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    alerts = db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == d["id"])).all()
    assert [a.organization_id for a in alerts] == [world["abc"].id]  # Northwind is in Illinois
    assert alerts[0].affected_system_ids == [world["screening"].id]  # the hiring system, not the chatbot
    assert "New York City" in alerts[0].match_reason


def test_an_update_on_a_law_matches_systems_that_carry_the_law(client, db, world):
    db.add(RegisterSystemLaw(organization_id=world["nw"].id, register_system_id=world["nw_ats"].id, regulation_id=world["ll144"].id, status="active"))
    db.commit()
    d = publish(client, db, world, nyc_enforcement(world, regulation_id=world["ll144"].id, affected_features=[]))
    orgs = {a.organization_id: a for a in db.scalars(select(RegulatoryAlert).where(RegulatoryAlert.update_id == d["id"]))}
    assert world["nw"].id in orgs and orgs[world["nw"].id].affected_system_ids == [world["nw_ats"].id]


def test_watch_items_are_published_but_never_matched(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world, change_type="pending_bill", watch=True, jurisdiction_id=world["j"]["US"].id, law_name="Great American AI Act",
                                                   title="Discussion draft would pause state AI model-development laws for three years", affected_features=[]))
    assert d["status"] == "published" and d["watch"] is True and d["client_count"] == 0
    assert db.scalars(select(RegulatoryAlert)).all() == []


def test_publishing_raises_a_reassessment_trigger_on_affected_systems(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    t = db.scalar(select(ReassessmentTrigger).where(ReassessmentTrigger.register_system_id == world["screening"].id))
    assert t.type == "regulatory_update" and t.source == "regulatory_update" and t.source_ref == f"update:{d['id']}" and "RU-001" in t.detail


def test_the_list_has_tabs_and_shows_approved_law_library_changes_read_only(client, db, world):
    publish(client, db, world, nyc_enforcement(world))
    login_as(client, db, world["legal"])
    second = client.post("/api/v1/reg/updates", json=nyc_enforcement(world, title="Second draft")).json()["id"]
    client.post(f"/api/v1/reg/updates/{second}/submit")
    db.add(ProposedChange(change_type="effective_date", regulation_id=world["ll144"].id, field_path="law.effective_on", summary="Date confirmed", status="approved",
                          origin="admin_edit", source_url="https://www.nyc.gov/x"))
    db.commit()
    login_as(client, db, world["aud"])  # Auditors read
    d = client.get("/api/v1/reg/updates").json()
    assert d["counts"] == {"all": 3, "awaiting_review": 1, "published": 2}
    lib = [x for x in d["rows"] if x["kind"] == "law_library"]
    assert len(lib) == 1 and lib[0]["read_only"] is True and lib[0]["law_name"] == "NYC Local Law 144"
    assert client.post("/api/v1/reg/updates", json=nyc_enforcement(world)).status_code == 403


def test_sales_and_clients_cannot_see_the_screen(client, db, world):
    login_as(client, db, world["sales"])
    assert client.get("/api/v1/reg/updates").status_code == 403
    login_as(client, db, world["maria"])
    assert client.get("/api/v1/reg/updates").status_code in (403, 404)


def test_impact_lists_systems_open_findings_and_remediation_dates(client, db, world):
    from datetime import date

    from app.engagements.models import Engagement
    from app.findings.models import Finding
    from app.remediation.models import RemediationItem
    from app.systems.models import AISystem

    e = Engagement(organization_id=world["abc"].id, client_id=world["abc"].id, name="ABC 2026 audit", status="completed", stage=9)
    db.add(e)
    db.flush()
    s = AISystem(organization_id=world["abc"].id, engagement_id=e.id, name="Résumé screening", reference_id="SYS-001", register_system_id=world["screening"].id, tool_ids=[], use_case_ids=[])
    db.add(s)
    db.flush()
    f = Finding(organization_id=world["abc"].id, engagement_id=e.id, ref="F-007", ai_system_id=s.id, title="No bias audit within the past year", severity="high", status="approved")
    db.add(f)
    db.flush()
    db.add(RemediationItem(organization_id=world["abc"].id, engagement_id=e.id, finding_id=f.id, action="Commission an independent bias audit", due_date=date(2026, 12, 15), status="open"))
    db.commit()
    d = publish(client, db, world, nyc_enforcement(world))
    r = client.get(f"/api/v1/reg/updates/{d['id']}/impact/{world['abc'].id}")
    assert r.status_code == 200, r.text
    imp = r.json()
    assert imp["systems"][0]["name"] == "Résumé screening" and imp["systems"][0]["risk_tier"] == 3
    assert imp["findings"][0]["ref"] == "F-007" and imp["findings"][0]["remediation_due"] == "2026-12-15"


def test_send_alert_to_client_goes_through_the_a1_approval_queue_once(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    login_as(client, db, world["legal"])  # not on ABC Corp's engagement team: the client is not visible to them
    assert client.post(f"/api/v1/reg/updates/{d['id']}/alerts", json={"organization_ids": [world["abc"].id]}).status_code == 404
    login_as(client, db, world["chief"])
    r = client.post(f"/api/v1/reg/updates/{d['id']}/alerts", json={"organization_ids": [world["abc"].id]})
    assert r.status_code == 200, r.text
    s = db.scalar(select(AlertSend))
    rule = db.get(AlertRule, s.alert_rule_id)
    assert rule.trigger == "regulatory_update" and rule.approval == "chief_auditor" and s.status == "waiting_approval"
    assert s.change_ref == f"update:{d['id']}" and s.affected_system_ids == [world["screening"].id]
    assert [t["text"] for t in s.todo_items][:1] == ["Confirm the bias audit is less than 12 months old"]
    client.post(f"/api/v1/reg/updates/{d['id']}/alerts", json={"organization_ids": [world["abc"].id]})
    assert len(db.scalars(select(AlertSend)).all()) == 1
    assert db.scalar(select(RegulatoryAlert)).alert_send_id == s.id


def test_an_alert_is_only_for_a_matched_client(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    r = client.post(f"/api/v1/reg/updates/{d['id']}/alerts", json={"organization_ids": [world["nw"].id]})
    assert r.status_code == 409


def test_advisory_opportunity_goes_to_s1_and_keeps_the_independence_rule(client, db, world):
    from app.engagements.models import Engagement
    from app.findings.models import Finding

    d = publish(client, db, world, nyc_enforcement(world))
    e = Engagement(organization_id=world["abc"].id, client_id=world["abc"].id, name="ABC audit", status="in_progress", stage=5)
    db.add(e)
    db.flush()
    db.add(Finding(organization_id=world["abc"].id, engagement_id=e.id, ref="F-001", title="Gap", severity="high"))
    db.commit()
    r = client.post(f"/api/v1/reg/updates/{d['id']}/opportunity", json={"organization_id": world["abc"].id, "service_kind": "remediation"})
    assert r.status_code == 409 and "finding" in r.json()["detail"]
    r = client.post(f"/api/v1/reg/updates/{d['id']}/opportunity", json={"organization_id": world["abc"].id, "service_kind": "advisory"})
    assert r.status_code == 200, r.text
    assert r.json()["needs_ca_approval"] is True  # a current audit client
    o = db.scalar(select(Opportunity).where(Opportunity.trigger == "regulatory_update"))
    assert o.organization_id == world["abc"].id and o.trigger_ref == f"{d['id']}" and o.system_ids == [world["screening"].id]


def test_propose_the_law_change_creates_a_pending_m3_change_with_the_source(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world, regulation_id=world["ll144"].id, source_quote="identified at least 17 instances of potential non-compliance"))
    login_as(client, db, world["legal"])
    r = client.post(f"/api/v1/reg/updates/{d['id']}/law-change", json={"field_path": "law.litigation_text", "new_value": "State Comptroller audit 2024-N-6 (December 2025) found weak enforcement.",
                                                                       "summary": "Record the State Comptroller's enforcement audit."})
    assert r.status_code == 200, r.text
    pc = db.get(ProposedChange, r.json()["proposed_change_id"])
    assert pc.status == "pending" and pc.regulation_id == world["ll144"].id and pc.source_url == d["source_url"]
    assert "RU-001" in pc.reason and pc.proposed_by == world["legal"].id
    assert db.get(RegulatoryUpdate, d["id"]).proposed_change_id == pc.id


def test_the_law_change_needs_a_law(client, db, world):
    d = publish(client, db, world, nyc_enforcement(world))
    r = client.post(f"/api/v1/reg/updates/{d['id']}/law-change", json={"field_path": "law.effective_on", "new_value": "2027-01-01", "summary": "x"})
    assert r.status_code == 409
