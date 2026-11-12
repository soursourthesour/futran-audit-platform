"""G-09 review fixes: re-certification when the reassessment trigger is already open, AgentWarden usage from the latest
snapshot of every agent, letters the client can download, and malformed AgentWarden files."""
from sqlalchemy import select

from app.register.models import RegisterSystem
from tests.assurance.test_assurance import RUN, WARDEN, w  # noqa: F401


def _change_model(w, version):
    w.as_(w.caico)
    r = w.client.patch(f"/api/v1/register/{w.agent.id}", json={"model_version": version})
    assert r.status_code == 200, r.text
    w.db.refresh(w.agent)


def test_recertification_when_a_version_change_trigger_was_already_open(w):
    _change_model(w, "2026-10")  # opens a version_change trigger before any Agent Assure record
    w.as_(w.auditor)
    w.client.post(f"{w.futran}/runs", json=RUN | {"outcome": "pass"})
    w.db.refresh(w.agent)
    assert w.agent.agentassure_status == "passed"
    _change_model(w, "2026-11")  # the open trigger is reused; the agent still needs re-certification
    assert w.agent.agentassure_status == "recertification_due"


def test_recertification_on_a_second_version_change_after_a_new_pass(w):
    w.as_(w.auditor)
    w.client.post(f"{w.futran}/runs", json=RUN | {"outcome": "pass"})
    _change_model(w, "2026-10")
    assert w.agent.agentassure_status == "recertification_due"
    w.as_(w.auditor)
    w.client.post(f"{w.futran}/runs", json=RUN | {"release_ref": "v1.3", "outcome": "pass"})
    w.db.refresh(w.agent)
    assert w.agent.agentassure_status == "passed"
    _change_model(w, "2026-12")
    assert w.agent.agentassure_status == "recertification_due"


def test_a_sync_of_some_agents_keeps_the_others_in_the_usage_totals(w):
    from app.commercial.models import UsageRecord

    second = RegisterSystem(organization_id=w.org.id, reference="AIS-003", name="Invoice triage agent", type="agent", sourcing="in_house", stage="live")
    w.db.add(second)
    w.db.commit()
    w.as_(w.fadmin)
    both = WARDEN.replace(b"Unknown bot,autonomous,10,,1,VPC", b"AIS-003,autonomous,1000,,2,VPC")
    assert w.client.post(f"/api/v1/clients/{w.org.id}/agentwarden/sync", files={"file": ("all.csv", both, "text/csv")}).json()["matched"] == 2
    one = b"Agent,Autonomy,Actions this month,Approver seats,Deployment\nAIS-001,acts_with_approval,50000,4,SaaS\n"
    assert w.client.post(f"/api/v1/clients/{w.org.id}/agentwarden/sync", files={"file": ("one.csv", one, "text/csv")}).json()["matched"] == 1
    got = {u.key: u.value for u in w.db.scalars(select(UsageRecord).where(UsageRecord.organization_id == w.org.id))}
    assert got == {"agents_protected": 2, "agent_actions_month": 51000, "approver_seats": 6}


def test_the_caico_downloads_the_assurance_letter_and_outsiders_do_not(w):
    w.as_(w.auditor)
    rid = w.client.post(f"{w.futran}/runs", json=RUN | {"outcome": "pass"}).json()["id"]
    run = w.client.post(f"{w.futran}/runs/{rid}/letter", data={"signed_by": "Jordan Lee", "signed_on": "2026-11-10"},
                        files={"file": ("letter.pdf", b"%PDF-1.4 letter", "application/pdf")}).json()
    fid = run["letter"]["id"]
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 200
    w.as_(w.caico)
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 200
    w.as_(w.other_caico)
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 404
    w.as_(w.outsider)
    assert w.client.get(f"/api/v1/files/{fid}").status_code == 404


def test_a_malformed_agentwarden_file_is_refused_plainly(w):
    import os

    w.as_(w.fadmin)
    r = w.client.post(f"/api/v1/clients/{w.org.id}/agentwarden/sync", files={"file": ("junk.csv", b"Agent\n" + os.urandom(1500) + b"\x00\n", "text/csv")})
    assert r.status_code == 422, r.text
