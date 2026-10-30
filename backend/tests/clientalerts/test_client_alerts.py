"""§27.6 A1 automatic client alerts: rules, approval queue and per-client emails with affected systems and to-dos."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.clientalerts.models import AlertRule, AlertSend
from app.clientalerts.service import ensure_rules, queue_effective_dates, queue_for_case, queue_for_change
from app.core.clock import today
from app.laws.publish import current_regulations
from app.litigation.models import Case
from app.litigation.service import match_case
from app.mail.models import OutboxMessage
from app.regmaster.models import ChangeImpact, ClientLawApplicability, LawVersion, ProposedChange, Requirement
from tests.factories import login_as, make_user


@pytest.fixture
def law(db, lit):
    """An approved change to a law with two requirements; ABC Corp's résumé screening is affected."""
    reg = current_regulations(db)[0]
    v = LawVersion(regulation_id=reg.id, version_no=2, status="in_force", compliance_on=date(2027, 1, 1), approved_by=lit["chief"].id)
    db.add(v)
    db.flush()
    reg.current_version_id = v.id
    db.add_all([
        Requirement(law_version_id=v.id, code="IL-01", order=1, text="Give employees notice before AI is used in employment decisions.", needed_by_stage="go_live", applies_to=["employer"]),
        Requirement(law_version_id=v.id, code="IL-02", order=2, text="Do not use zip codes as a proxy for protected classes.", needed_by_stage="ongoing", applies_to=["employer"]),
    ])
    pc = ProposedChange(origin="claude_refresh", change_type="new_rule", regulation_id=reg.id, field_path="requirement.IL-01", summary="Illinois notice content set by rules", status="approved", applied_version_id=v.id)
    db.add(pc)
    db.flush()
    db.add(ChangeImpact(proposed_change_id=pc.id, organization_id=lit["abc"].id, ai_system_ids=[lit["screening"].id]))
    db.commit()
    return reg, v, pc


def test_default_rules_match_the_spec_table(db, lit):
    rules = {r.trigger: r for r in ensure_rules(db)}
    assert set(rules) == {"law_change", "new_law", "effective_date", "case", "tracing_addon"}
    assert rules["effective_date"].approval == "automatic"
    assert rules["tracing_addon"].approval == "sales_owner"
    assert {rules[t].approval for t in ("law_change", "new_law", "case")} == {"chief_auditor"}
    assert rules["effective_date"].client_groups == ["AIComplianceTeam", "DeptHeads"]
    assert ensure_rules(db) and db.query(AlertRule).count() == 5  # idempotent


def test_approved_change_waits_for_chief_auditor_with_systems_and_todos(db, lit, law, settings):
    reg, v, pc = law
    sends = queue_for_change(db, settings, pc)
    assert len(sends) == 1
    s = sends[0]
    assert s.organization_id == lit["abc"].id and s.status == "waiting_approval"
    assert s.affected_system_ids == [lit["screening"].id]
    assert [t["text"] for t in s.todo_items] == ["Give employees notice before AI is used in employment decisions.", "Do not use zip codes as a proxy for protected classes."]
    assert s.todo_items[0]["deadline"] == "2027-01-01"
    assert queue_for_change(db, settings, pc)[0].id == s.id  # once per client and change
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "client_alert")) is None


def test_paused_rule_queues_nothing(db, lit, law, settings):
    for r in ensure_rules(db):
        if r.trigger == "law_change":
            r.active = False
    assert queue_for_change(db, settings, law[2]) == []


def test_effective_date_alerts_send_automatically_at_90_and_30_days(db, lit, law, settings):
    reg, v, pc = law
    db.add(ClientLawApplicability(organization_id=lit["abc"].id, regulation_id=reg.id, law_version_id=v.id, in_scope=True))
    db.commit()
    day90 = v.compliance_on - timedelta(days=90)
    assert queue_effective_dates(db, settings, day90 - timedelta(days=1)) == []
    sent = queue_effective_dates(db, settings, day90)
    assert len(sent) == 1 and sent[0].status == "sent"
    mail = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "client_alert"))
    assert "maria@abc.test" in mail.to
    assert "Give employees notice" in mail.body_text and "Résumé screening" not in mail.body_text  # no system impact rows for a date alert
    assert queue_effective_dates(db, settings, day90 + timedelta(days=1)) == []  # not again
    assert len(queue_effective_dates(db, settings, v.compliance_on - timedelta(days=30))) == 1


def test_case_briefing_goes_to_clients_with_similar_ai(db, lit, settings):
    from tests.wsd_world import HIRING_CASE

    case = Case(name=HIRING_CASE["name"], area="Hiring discrimination", stage="discovery", match_rule=HIRING_CASE["match_rule"],
                talking_points_client="List every hiring tool that ranks or filters applicants.\nAsk each vendor for its bias audit, including age.")
    db.add(case)
    db.flush()
    match_case(db, case)
    sends = queue_for_case(db, settings, case)
    assert {s.organization_id for s in sends} == {lit["abc"].id, lit["nw"].id}
    abc = next(s for s in sends if s.organization_id == lit["abc"].id)
    assert abc.affected_system_ids == [lit["screening"].id]
    assert [t["text"] for t in abc.todo_items][0] == "List every hiring tool that ranks or filters applicants."
    assert all(s.status == "waiting_approval" for s in sends)


def test_queue_approve_and_send_lists_only_that_clients_systems(client, db, lit, law, settings):
    reg, v, pc = law
    queue_for_change(db, settings, pc)
    db.commit()
    login_as(client, db, lit["chief"])
    q = client.get("/api/v1/alerts/queue").json()
    assert len(q["groups"]) == 1 and q["groups"][0]["items"][0]["client_name"] == "ABC Corp"
    item = q["groups"][0]["items"][0]
    assert item["systems"] == ["Résumé screening"] and item["sent_from"].startswith("Futran on behalf")
    pv = client.get(f"/api/v1/alerts/sends/{item['id']}/preview").json()
    assert "Résumé screening" in pv["text"] and "IL-01" not in pv["subject"]
    assert "Give employees notice" in pv["text"] and "not legal advice" in pv["text"].lower()
    r = client.post("/api/v1/alerts/sends/approve", json={"ids": [item["id"]]})
    assert r.status_code == 200 and r.json()["sent"] == 1
    send = db.get(AlertSend, item["id"])
    db.refresh(send)
    assert send.status == "sent" and send.approved_by == lit["chief"].id
    mail = db.get(OutboxMessage, send.outbox_message_id)  # AIComplianceTeam has no members yet: straight to the CAICO
    assert mail.to == ["maria@abc.test"] and "Résumé screening" in mail.body_text
    rule = db.get(AlertRule, send.alert_rule_id)
    db.refresh(rule)
    assert rule.last_sent_at is not None


def test_edit_and_hold(client, db, lit, law, settings):
    s = queue_for_change(db, settings, law[2])[0]
    db.commit()
    login_as(client, db, lit["chief"])
    r = client.patch(f"/api/v1/alerts/sends/{s.id}", json={"subject": "Illinois notice rules: two systems to check", "intro": "Illinois issued notice rules."})
    assert r.status_code == 200
    assert client.get(f"/api/v1/alerts/sends/{s.id}/preview").json()["subject"].startswith("Illinois notice rules: two systems to check")
    assert client.post("/api/v1/alerts/sends/hold", json={"ids": [s.id]}).json()["held"] == 1
    db.refresh(s)
    assert s.status == "held"


def test_sales_cannot_approve_chief_auditor_sends_but_owns_addon_sends(client, db, lit, law, settings):
    s = queue_for_change(db, settings, law[2])[0]
    db.commit()
    login_as(client, db, lit["sales"])
    assert client.post("/api/v1/alerts/sends/approve", json={"ids": [s.id]}).status_code == 403
    assert client.get("/api/v1/alerts/rules").status_code == 403


def test_rules_grid_pause_and_turn_on(client, db, lit):
    login_as(client, db, lit["admin"])
    rules = client.get("/api/v1/alerts/rules").json()["rules"]
    assert len(rules) == 5 and rules[0]["when_label"] == "Law change approved"
    ids = [r["id"] for r in rules[:2]]
    assert client.post("/api/v1/alerts/rules/bulk", json={"ids": ids, "active": False}).json()["changed"] == 2
    assert [r["active"] for r in client.get("/api/v1/alerts/rules").json()["rules"]][:2] == [False, False]
    r = client.patch(f"/api/v1/alerts/rules/{ids[0]}", json={"client_groups": ["AIComplianceTeam"], "approval": "automatic"})
    assert r.status_code == 200 and r.json()["approval"] == "automatic"
    login_as(client, db, lit["aud"])
    assert client.get("/api/v1/alerts/rules").status_code == 403


def test_send_goes_to_the_client_group_through_group_email(client, db, lit, law, settings):
    from app.mail.groups import add_member, default_group
    from app.mail.models import AdminLogEntry, MailRecipient, MailSend
    from app.mail.people import ensure_platform_people, find_person

    ensure_platform_people(db, lit["abc"].id)
    team = default_group(db, lit["abc"].id, "ai_compliance_team")
    add_member(db, lit["maria"], team, person_id=find_person(db, lit["abc"].id, "maria@abc.test").id)
    s = queue_for_change(db, settings, law[2])[0]
    db.commit()
    login_as(client, db, lit["chief"])
    assert client.get(f"/api/v1/alerts/sends/{s.id}/preview").json()["fallback"] is False
    assert client.post("/api/v1/alerts/sends/approve", json={"ids": [s.id]}).json()["sent"] == 1
    db.refresh(s)
    ms = db.get(MailSend, s.mail_send_id)
    assert ms is not None and ms.related_id == s.id
    assert [r.email for r in db.scalars(select(MailRecipient).where(MailRecipient.send_id == ms.id))] == ["maria@abc.test"]
    assert db.scalar(select(AdminLogEntry).where(AdminLogEntry.send_id == ms.id)) is not None
    assert s.sent_from == "Futran on behalf (no client mailbox)"
