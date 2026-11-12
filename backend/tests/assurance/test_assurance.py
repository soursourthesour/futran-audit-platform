"""G-09 Agent Assure records and AgentWarden licence sync (Release 2 B9)."""
import io
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.factories import login_as, make_org, make_user

RUN = {"release_ref": "v1.2", "model_ref": "Provider model 2026-09", "eval_set_version": "v3", "eval_set_size": 240, "eval_set_owner": "Delta QA team",
       "checks": [{"position": 1, "result": "pass"}, {"position": 2, "result": "conditional", "note": "Add human approval before sending external email", "due": "Before go-live"}],
       "redteam": [{"scenario": "Found credential in shared doc", "outcome": "Agent stopped but did not alert", "severity": "medium"}],
       "outcome": "conditional"}
WARDEN = b"""Agent,Autonomy,Actions this month,Actions included,Approver seats,Deployment
AIS-001,acts_with_approval,41200,100000,3,SaaS
Unknown bot,autonomous,10,,1,VPC
"""


@pytest.fixture
def w(db, client):
    from app.engagements.models import Engagement, EngagementTeam
    from app.register.models import RegisterSystem

    f = make_org(db, type="futran")
    ns = SimpleNamespace(client=client, db=db)
    ns.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    ns.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    ns.outsider = make_user(db, f, roles=["auditor"], name="Olly Other", email="olly@futran.test")
    ns.fadmin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    org = make_org(db, name="Delta Logistics")
    ns.org = org
    ns.caico = make_user(db, org, roles=["caico"], name="Maria Lopez", email="maria@delta.example")
    ns.contrib = make_user(db, org, roles=["contributor"], name="Tom Reyes", email="tom@delta.example")
    other = make_org(db, name="Other Co")
    ns.other_caico = make_user(db, other, roles=["caico"], name="Olga", email="olga@other.example")
    ns.agent = RegisterSystem(organization_id=org.id, reference="AIS-001", name="Carrier-booking agent", type="agent", sourcing="in_house", stage="live",
                              model_name="Provider model", model_version="2026-09", autonomy="acts_with_approval")
    ns.app = RegisterSystem(organization_id=org.id, reference="AIS-002", name="Résumé screening", type="vendor_app", sourcing="vendor", stage="live")
    db.add_all([ns.agent, ns.app])
    e = Engagement(organization_id=org.id, client_id=org.id, name="Delta AI audit", status="in_progress")
    db.add(e)
    db.flush()
    db.add(EngagementTeam(organization_id=org.id, engagement_id=e.id, user_id=ns.auditor.id, role="auditor"))
    db.commit()
    ns.engagement = e
    ns.as_ = lambda user: login_as(client, db, user)
    ns.futran = f"/api/v1/clients/{org.id}/register/{ns.agent.id}/assurance"
    return ns


def test_the_fifteen_point_check_list_is_blank_by_default_and_editable_by_futran(w):
    w.as_(w.chief)
    r = w.client.get("/api/v1/assurance/checklist")
    assert r.status_code == 200, r.text
    d = r.json()
    assert [i["position"] for i in d["items"]] == list(range(1, 16)) and all(i["text"] is None for i in d["items"])
    assert "FATF" in d["note"]
    w.as_(w.fadmin)
    r = w.client.put("/api/v1/assurance/checklist", json={"items": [{"position": 1, "text": "Tool permissions are least privilege"}]})
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["text"] == "Tool permissions are least privilege" and r.json()["items"][1]["text"] is None
    w.as_(w.auditor)
    assert w.client.put("/api/v1/assurance/checklist", json={"items": [{"position": 2, "text": "x"}]}).status_code == 403


def test_futran_records_a_release_and_the_register_status_is_computed(w):
    w.as_(w.auditor)
    r = w.client.post(f"{w.futran}/runs", json=RUN)
    assert r.status_code == 200, r.text
    w.db.refresh(w.agent)
    assert w.agent.agentassure_status == "conditional"
    w.as_(w.caico)
    d = w.client.get(f"/api/v1/register/{w.agent.id}/assurance").json()
    assert d["status"] == "conditional" and d["status_label"] == "Agent Assure: conditional pass"
    run = d["runs"][0]
    assert run["release_ref"] == "v1.2" and run["eval_set_size"] == 240 and run["checks_summary"] == {"pass": 1, "conditional": 1, "fail": 0, "not_run": 13}
    assert run["redteam"][0]["severity"] == "medium" and d["open_conditions"][0]["condition"] == "Add human approval before sending external email"
    assert d["can_record"] is False
    assert w.client.post(f"{w.futran}/runs", json=RUN).status_code in (403, 404)


def test_only_agents_get_agent_assure_records_and_input_is_checked(w):
    w.as_(w.auditor)
    r = w.client.post(f"/api/v1/clients/{w.org.id}/register/{w.app.id}/assurance/runs", json=RUN)
    assert r.status_code == 409
    bad = w.client.post(f"{w.futran}/runs", json=RUN | {"outcome": "maybe", "eval_set_size": -1, "checks": [{"position": 16, "result": "pass"}]})
    assert bad.status_code == 422
    assert {e["field"] for e in bad.json()["errors"]} >= {"outcome", "eval_set_size", "checks"}


def test_the_assurance_letter_is_stored_with_who_signed_it_and_when(w):
    from app.files.models import FileObject

    w.as_(w.auditor)
    rid = w.client.post(f"{w.futran}/runs", json=RUN | {"outcome": "pass"}).json()["id"]
    r = w.client.post(f"{w.futran}/runs/{rid}/letter", data={"signed_by": "Jordan Lee, Agent Assure lead", "signed_on": "2026-11-10"},
                      files={"file": ("letter.pdf", b"%PDF-1.4 letter", "application/pdf")})
    assert r.status_code == 200, r.text
    run = r.json()
    f = w.db.get(FileObject, run["letter"]["id"])
    assert f.linked_type == "assurance_letter" and f.organization_id == w.org.id and run["signed_by"].startswith("Jordan Lee") and run["signed_on"] == "2026-11-10"


def test_a_model_or_version_change_asks_for_re_certification_through_the_reassessment_triggers(w):
    w.as_(w.auditor)
    w.client.post(f"{w.futran}/runs", json=RUN | {"outcome": "pass"})
    w.db.refresh(w.agent)
    assert w.agent.agentassure_status == "passed"
    w.as_(w.caico)
    r = w.client.patch(f"/api/v1/register/{w.agent.id}", json={"model_version": "2026-11"})
    assert r.status_code == 200, r.text
    w.db.refresh(w.agent)
    assert w.agent.agentassure_status == "recertification_due"
    d = w.client.get(f"/api/v1/register/{w.agent.id}/assurance").json()
    assert d["recertification"]["due"] and "version" in d["recertification"]["reason"].lower()
    w.as_(w.auditor)
    w.client.post(f"{w.futran}/runs", json=RUN | {"release_ref": "v1.3", "outcome": "pass"})
    w.db.refresh(w.agent)
    assert w.agent.agentassure_status == "passed"


def test_the_register_field_cannot_be_set_by_hand_once_agent_assure_records_exist(w):
    w.as_(w.caico)
    assert w.client.patch(f"/api/v1/register/{w.agent.id}", json={"agentassure_status": "planned"}).status_code == 200  # no record yet: as before
    w.as_(w.auditor)
    w.client.post(f"{w.futran}/runs", json=RUN)
    w.as_(w.caico)
    r = w.client.patch(f"/api/v1/register/{w.agent.id}", json={"agentassure_status": "passed"})
    assert r.status_code == 422 and "Agent Assure" in r.text


def test_agentwarden_licence_sync_by_csv_feeds_the_agent_and_usage(w):
    w.as_(w.fadmin)
    r = w.client.post(f"/api/v1/clients/{w.org.id}/agentwarden/sync", files={"file": ("warden.csv", WARDEN, "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["matched"] == 1 and d["unmatched"] == ["Unknown bot"]
    w.as_(w.caico)
    aw = w.client.get(f"/api/v1/register/{w.agent.id}/assurance").json()["warden"]
    assert aw["actions_month"] == 41200 and aw["actions_included"] == 100000 and aw["approvers"] == 3 and aw["deployment"] == "saas" and aw["autonomy"] == "acts_with_approval"
    try:
        from app.commercial.models import UsageRecord
    except ImportError:
        return
    got = {u.key: u.value for u in w.db.scalars(select(UsageRecord).where(UsageRecord.organization_id == w.org.id))}
    assert got["agents_protected"] == 1 and got["agent_actions_month"] == 41200 and got["approver_seats"] == 3


def test_independence_rule_i2_is_noted_when_futran_also_audits_the_client(w):
    w.as_(w.caico)
    d = w.client.get(f"/api/v1/register/{w.agent.id}/assurance").json()
    assert "I-2" in d["independence_note"]


def test_people_outside_see_nothing(w):
    w.as_(w.other_caico)
    assert w.client.get(f"/api/v1/register/{w.agent.id}/assurance").status_code == 404
    w.as_(w.outsider)
    assert w.client.get(w.futran).status_code == 404
    w.as_(w.contrib)
    assert w.client.get(f"/api/v1/register/{w.agent.id}/assurance").status_code in (403, 404)
    w.as_(w.auditor)
    assert w.client.get(w.futran).status_code == 200
