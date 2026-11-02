"""Reassessment triggers detected from register edits, the 12-month schedule, the trigger lifecycle on the register and
the "Reassessment overdue" monitoring check."""
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.impact.models import ImpactAssessment, ReassessmentTrigger
from app.impact.schedule import run_reassessment_schedule
from app.register.models import HistoryEntry
from tests.factories import login_as


def _triggers(db, sid):
    return db.scalars(select(ReassessmentTrigger).where(ReassessmentTrigger.register_system_id == sid).order_by(ReassessmentTrigger.detected_at)).all()


def _edit(client, db, lit, sid, body):
    login_as(client, db, lit["maria"])
    r = client.patch(f"/api/v1/register/{sid}", json=body | {"reason": "Vendor release notes"})
    assert r.status_code == 200, r.text


def test_a_new_model_version_on_a_live_system_raises_a_version_trigger(client, db, lit):
    lit["screening"].model_version = "2025.1"
    db.commit()
    _edit(client, db, lit, lit["screening"].id, {"model_version": "2026.2"})
    t = _triggers(db, lit["screening"].id)
    assert [(x.type, x.source) for x in t] == [("version_change", "register_edit")] and "2025.1" in t[0].detail and "2026.2" in t[0].detail


def test_new_data_categories_and_people_raise_their_triggers_but_removals_do_not(client, db, lit):
    sid = lit["chatbot"].id
    _edit(client, db, lit, sid, {"data": {"data_categories": ["personal"], "data_subjects": ["customers"]}})
    assert {x.type for x in _triggers(db, sid)} == {"new_data_category", "new_population"}
    for t in _triggers(db, sid):
        t.status = "resolved"
    db.commit()
    _edit(client, db, lit, sid, {"data": {"data_categories": [], "data_subjects": ["customers"]}})
    assert all(t.status == "resolved" for t in _triggers(db, sid))


def test_a_vendor_change_and_data_leaving_the_country_raise_triggers(client, db, lit):
    sid = lit["screening"].id
    _edit(client, db, lit, sid, {"ai_provider": "openai"})
    assert not _triggers(db, sid)  # the provider was not recorded before: a first answer, not a change
    _edit(client, db, lit, sid, {"ai_provider": "anthropic", "data": {"cross_border": "india"}})
    assert {x.type for x in _triggers(db, sid)} == {"vendor_change", "new_jurisdiction"}


def test_a_law_from_a_new_jurisdiction_raises_a_trigger(client, db, lit):
    from app.laws.publish import current_regulations

    sid = lit["screening"].id
    regs = current_regulations(db)
    nyc = next(r for r in regs if r.short_name == "NYC Local Law 144")
    il = next(r for r in regs if r.short_name.startswith("HB 3773"))
    login_as(client, db, lit["maria"])
    assert client.post(f"/api/v1/register/{sid}/laws", json={"regulation_id": nyc.id}).status_code == 200
    assert not _triggers(db, sid)  # the first law recorded on a system is filling in the record, not a change
    assert client.post(f"/api/v1/register/{sid}/laws", json={"regulation_id": il.id}).status_code == 200
    t = _triggers(db, sid)
    assert [x.type for x in t] == ["new_jurisdiction"] and "HB 3773" in t[0].detail and "Illinois" in t[0].detail


def test_laws_recorded_when_a_system_is_added_raise_no_trigger(client, db, lit):
    from app.laws.publish import current_regulations

    regs = current_regulations(db)
    ids = [next(r for r in regs if r.short_name == "NYC Local Law 144").id, next(r for r in regs if r.short_name.startswith("HB 3773")).id]
    login_as(client, db, lit["maria"])
    r = client.post("/api/v1/register", json={"name": "Interview scheduler", "type": "vendor_app", "sourcing": "vendor", "stage": "ready_for_go_live", "company_wide": True,
                                              "decision_impact": "informs", "regulation_ids": ids})
    assert r.status_code == 200, r.text
    assert not _triggers(db, r.json()["id"])


def test_a_proposed_system_gets_triggers_only_after_its_impact_assessment_is_approved(client, db, lit):
    s = lit["chatbot"]
    s.stage = "proposed"
    db.commit()
    _edit(client, db, lit, s.id, {"data": {"data_categories": ["health"]}})
    assert not _triggers(db, s.id)
    db.add(ImpactAssessment(organization_id=s.organization_id, reference="IA-001", project_name="Chatbot", status="decided", decision="approved", register_system_id=s.id, intake={}))
    db.commit()
    _edit(client, db, lit, s.id, {"data": {"data_categories": ["health", "biometric"]}})
    assert [x.type for x in _triggers(db, s.id)] == ["new_data_category"]


def test_twelve_months_after_the_last_assessment_the_schedule_raises_a_trigger(db, lit, settings):
    s = lit["screening"]
    s.live_since = date(2025, 9, 1)
    db.commit()
    now = datetime(2026, 11, 2, 10)
    assert run_reassessment_schedule(db, settings, now) == 1
    t = _triggers(db, s.id)
    assert [(x.type, x.source) for x in t] == [("twelve_months", "schedule")]
    assert run_reassessment_schedule(db, settings, now) == 0  # still open: not raised twice
    db.add(HistoryEntry(organization_id=s.organization_id, register_system_id=lit["chatbot"].id, type="impact_assessment", occurred_on=date(2026, 6, 1), summary="Reassessed"))
    lit["chatbot"].live_since = date(2024, 1, 1)
    db.commit()
    assert run_reassessment_schedule(db, settings, now) == 0  # the chatbot was reassessed in June


def test_the_register_shows_triggers_and_the_caico_resolves_one_with_a_note(client, db, lit):
    from app.impact.triggers import raise_trigger

    t = raise_trigger(db, lit["screening"].id, type="failed_monitor_check", source="monitor", detail="Bias test over 12 months old")
    db.commit()
    login_as(client, db, lit["maria"])
    rows = client.get(f"/api/v1/register/{lit['screening'].id}/triggers").json()["rows"]
    assert rows[0]["type_label"] == "Failed monitoring check" and rows[0]["status"] == "open"
    home = client.get("/api/v1/reassessment").json()["rows"]
    assert [r["system_name"] for r in home] == ["Résumé screening"]
    assert client.post(f"/api/v1/reassessment/{t.id}/resolve", json={}).status_code == 422
    r = client.post(f"/api/v1/reassessment/{t.id}/resolve", json={"note": "New bias audit by Halden Analytics, 20 Oct 2026."})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    h = db.scalar(select(HistoryEntry).where(HistoryEntry.register_system_id == lit["screening"].id, HistoryEntry.type == "impact_assessment"))
    assert "Halden" in h.summary
    assert client.get("/api/v1/reassessment").json()["rows"] == []


def test_the_caico_raises_a_trigger_by_hand(client, db, lit):
    login_as(client, db, lit["maria"])
    r = client.post(f"/api/v1/register/{lit['chatbot'].id}/triggers", json={"type": "new_population", "detail": "Opening the chatbot to customers in Germany"})
    assert r.status_code == 200, r.text
    assert [(x.type, x.source) for x in _triggers(db, lit["chatbot"].id)] == [("new_population", "manual")]
    assert client.post(f"/api/v1/register/{lit['chatbot'].id}/triggers", json={"type": "moon"}).status_code == 422


def test_reassessment_overdue_check(db, lit):
    from app.impact.triggers import raise_trigger
    from app.monitoring.registry import load_checks

    check = load_checks()["reassessment_overdue"]
    assert check.applies_to == "system"
    fresh = raise_trigger(db, lit["chatbot"].id, type="vendor_change", source="manual")
    stale = raise_trigger(db, lit["screening"].id, type="version_change", source="manual")
    stale.detected_at = datetime.now() - timedelta(days=45)
    db.commit()
    out = {o.object_label: o for o in check.fn(db, lit["abc"])}
    assert out["AIS-001 Résumé screening"].status == "failed" and out["AIS-001 Résumé screening"].register_system_id == lit["screening"].id
    assert out["AIS-002 Website chatbot"].status == "attention"
    assert check.fn(db, lit["nw"]) == []
