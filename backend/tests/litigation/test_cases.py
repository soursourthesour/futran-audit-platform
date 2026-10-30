"""§27.4 litigation tracker: cases, stages, matches with client registers, follows, export, law links."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.litigation.models import Case, CaseClientMatch
from app.litigation.service import match_case
from tests.factories import login_as
from tests.wsd_world import HIRING_CASE


def _add(client, body=HIRING_CASE):
    r = client.post("/api/v1/litigation", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_chief_auditor_adds_a_case_and_it_is_matched(client, db, lit):
    login_as(client, db, lit["chief"])
    c = _add(client)
    assert c["stage"] == "discovery" and c["version"] == 1
    orgs = {m["organization_name"] for m in c["matches"]}
    assert orgs == {"ABC Corp", "Northwind Health"}
    abc = next(m for m in c["matches"] if m["organization_name"] == "ABC Corp")
    assert [s["name"] for s in abc["systems"]] == ["Résumé screening"]
    assert "vendor" in abc["match_reason"].lower()


def test_retired_and_unrelated_systems_are_not_matched(db, lit):
    case = Case(name="X v. Y", area="Hiring", stage="filed", match_rule=HIRING_CASE["match_rule"], created_by=lit["chief"].id)
    db.add(case)
    db.flush()
    matches = match_case(db, case)
    ids = {sid for m in matches for sid in m.ai_system_ids}
    assert lit["retired"].id not in ids and lit["chatbot"].id not in ids
    assert lit["nw_ats"].id in ids


def test_vendor_term_narrows_the_match(db, lit):
    case = Case(name="X v. Workday", area="Hiring", stage="filed", match_rule={"vendors": ["workday"]}, created_by=lit["chief"].id)
    db.add(case)
    db.flush()
    matches = match_case(db, case)
    assert [m.organization_id for m in matches] == [lit["abc"].id]


def test_stage_must_be_a_known_value(client, db, lit):
    login_as(client, db, lit["chief"])
    r = client.post("/api/v1/litigation", json={**HIRING_CASE, "stage": "hearings"})
    assert r.status_code == 422


def test_edit_bumps_version_and_records_the_stage_timeline(client, db, lit):
    login_as(client, db, lit["chief"])
    c = _add(client)
    r = client.patch(f"/api/v1/litigation/{c['id']}", json={"stage": "trial", "stage_note": "Trial set"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["version"] == 2 and out["stage"] == "trial"
    assert [t["stage"] for t in out["timeline"]][-1] == "trial"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "case.update")) is not None


def test_list_filters_by_stage_area_and_client(client, db, lit):
    login_as(client, db, lit["chief"])
    _add(client)
    _add(client, {**HIRING_CASE, "name": "Moffatt v. Air Canada", "area": "Chatbot liability", "stage": "decided", "match_rule": {"types": ["genai_chat_tool"]}})
    assert len(client.get("/api/v1/litigation").json()["items"]) == 2
    assert [i["name"] for i in client.get("/api/v1/litigation?stage=decided").json()["items"]] == ["Moffatt v. Air Canada"]
    assert [i["name"] for i in client.get("/api/v1/litigation?area=Hiring discrimination").json()["items"]] == ["Mobley v. Workday, Inc."]
    nw = client.get(f"/api/v1/litigation?client_id={lit['nw'].id}").json()["items"]
    assert [i["name"] for i in nw] == ["Mobley v. Workday, Inc."]
    row = client.get("/api/v1/litigation?stage=decided").json()["items"][0]
    assert row["clients_count"] == 1


def test_auditor_reads_but_cannot_edit(client, db, lit):
    login_as(client, db, lit["chief"])
    c = _add(client)
    login_as(client, db, lit["aud"])
    assert client.get(f"/api/v1/litigation/{c['id']}").status_code == 200
    assert client.patch(f"/api/v1/litigation/{c['id']}", json={"stage": "trial"}).status_code == 403


def test_clients_cannot_see_the_tracker(client, db, lit):
    login_as(client, db, lit["maria"])
    assert client.get("/api/v1/litigation").status_code in (403, 404)


def test_admin_does_not_see_the_tracker(client, db, lit):
    login_as(client, db, lit["admin"])
    assert client.get("/api/v1/litigation").status_code == 403


def test_follow_and_unfollow(client, db, lit):
    login_as(client, db, lit["chief"])
    c = _add(client)
    login_as(client, db, lit["sales"])
    assert client.post(f"/api/v1/litigation/{c['id']}/follow").json()["following"] is True
    assert client.get(f"/api/v1/litigation/{c['id']}").json()["following"] is True
    assert client.post(f"/api/v1/litigation/{c['id']}/unfollow").json()["following"] is False


def test_export_csv(client, db, lit):
    login_as(client, db, lit["chief"])
    _add(client)
    r = client.get("/api/v1/litigation/export.csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert "Mobley v. Workday, Inc." in r.text


def test_cases_for_a_law(client, db, lit):
    from app.laws.publish import current_regulations

    law = current_regulations(db)[0]
    login_as(client, db, lit["chief"])
    c = _add(client, {**HIRING_CASE, "regulation_ids": [law.id]})
    rows = client.get(f"/api/v1/laws/{law.id}/cases").json()
    assert [r["id"] for r in rows] == [c["id"]]


def test_sales_sees_matches_without_audit_detail(client, db, lit):
    login_as(client, db, lit["chief"])
    c = _add(client)
    login_as(client, db, lit["sales"])
    out = client.get(f"/api/v1/litigation/{c['id']}").json()
    abc = next(m for m in out["matches"] if m["organization_name"] == "ABC Corp")
    assert set(abc["systems"][0]) <= {"id", "name", "type", "type_label", "stage"}
    assert db.scalars(select(CaseClientMatch)).all()


def test_decision_impact_narrows_the_match(db, lit):
    case = Case(name="Challenge to an AI law", area="Challenges to AI laws", stage="stayed", match_rule={"decision_impact": ["consequential"]}, created_by=lit["chief"].id)
    db.add(case)
    db.flush()
    ids = {sid for m in match_case(db, case) for sid in m.ai_system_ids}
    assert ids == {lit["screening"].id}


def test_seeded_cases_are_real_and_cited(db, matrix):
    from app.litigation.seed import CASES, seed_cases

    seed_cases(db)
    rows = db.scalars(select(Case)).all()
    assert len(rows) == len(CASES) >= 8
    for c in rows:
        assert c.sources and all(s["url"].startswith("https://") for s in c.sources), c.name
        assert c.court and c.stage and c.match_rule, c.name
    assert seed_cases(db) == 0  # idempotent


def test_send_briefing_queues_alerts_for_matched_clients(client, db, lit):
    from app.clientalerts.models import AlertSend

    login_as(client, db, lit["chief"])
    c = _add(client, {**HIRING_CASE, "talking_points_client": "List every hiring tool."})
    login_as(client, db, lit["sales"])
    r = client.post(f"/api/v1/litigation/{c['id']}/briefing", json={"organization_ids": [lit["abc"].id]})
    assert r.status_code == 200 and r.json()["queued"] == 1
    s = db.scalar(select(AlertSend))
    assert s.organization_id == lit["abc"].id and s.status == "waiting_approval"  # the Chief Auditor approves the send


def test_create_opportunities_and_assign_to_sales(client, db, lit):
    from app.sales.models import Opportunity

    login_as(client, db, lit["chief"])
    c = _add(client)
    r = client.post("/api/v1/litigation/bulk-assign", json={"ids": [c["id"]], "owner_id": lit["sales"].id})
    assert r.status_code == 200 and r.json()["created"] == 2
    opps = db.scalars(select(Opportunity)).all()
    assert {o.owner_id for o in opps} == {lit["sales"].id} and {o.trigger for o in opps} == {"case"}
    login_as(client, db, lit["aud"])
    assert client.post(f"/api/v1/litigation/{c['id']}/opportunities", json={}).status_code == 403


def test_bulk_follow_and_bulk_briefing(client, db, lit):
    login_as(client, db, lit["chief"])
    c = _add(client, {**HIRING_CASE, "talking_points_client": "List every hiring tool."})
    assert client.post("/api/v1/litigation/bulk-follow", json={"ids": [c["id"]]}).json()["changed"] == 1
    assert client.post("/api/v1/litigation/bulk-briefing", json={"ids": [c["id"]]}).json()["queued"] == 2
