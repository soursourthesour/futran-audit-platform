import re

import pytest

from app.engagements.models import ClientContact, ClientLocation, Engagement, EngagementTeam
from app.mail.models import OutboxMessage
from tests.engagements.helpers import _new, _put, complete
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def people(db, matrix):
    f = make_org(db, type="futran")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    aud2 = make_user(db, f, roles=["auditor"], name="Bea Auditor", email="bea@futran.test")
    chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    em = make_user(db, f, roles=["engagement_manager"], name="Eli Manager", email="eli@futran.test")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    db.commit()
    return {"aud": aud, "aud2": aud2, "chief": chief, "em": em, "admin": admin}


def test_create_and_autosave_partial_step(client, db, people):
    login_as(client, db, people["aud"])
    ids = _new(client)
    out = _put(client, ids["client_id"], "company", {"legal_name": "ABC Corp Inc.", "industry": "staffing"})
    assert out["errors"] == [] and out["saved_at"]
    w = client.get(f"/api/v1/clients/{ids['client_id']}/wizard").json()
    assert w["company"]["legal_name"] == "ABC Corp Inc." and w["company"]["industry"] == "staffing" and w["company"]["hq_city"] is None
    assert re.fullmatch(r"FSL-AI-AUD-\d{4}-\d{3}", w["engagement"]["audit_ref"]) and w["engagement"]["status"] == "draft"
    assert re.fullmatch(r"FUT-\d{4}", w["company"]["client_ref"])
    # bad values are reported and skipped; good ones in the same save are kept
    out = _put(client, ids["client_id"], "scope", {"type": "ll144_bias_audit", "period_start": "13/40/2026", "industry": "x"})
    assert [e["field"] for e in out["errors"]] == ["scope.period_start"]
    w = client.get(f"/api/v1/clients/{ids['client_id']}/wizard").json()
    assert w["scope"]["type"] == "ll144_bias_audit" and w["scope"]["period_start"] is None
    # the creator is on the team so they can keep working on it
    assert db.query(EngagementTeam).filter_by(engagement_id=ids["engagement_id"], user_id=people["aud"].id).count() == 1


def test_locations_resolve_and_requirements_saved(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    w = client.get(f"/api/v1/clients/{cid}/wizard").json()
    hq = next(loc for loc in w["locations"]["locations"] if loc["site_name"] == "Headquarters")
    assert hq["jurisdictions"] == ["New York City", "New York", "United States"]
    labels = [r["label"] for r in w["locations"]["requirements"]]
    assert any("Local Law 144" in x for x in labels) and any("52-c" in x for x in labels)
    # saving the step again replaces the set rather than duplicating it
    _put(client, cid, "locations", {"locations": [{"id": hq["id"], "site_name": "HQ", "country_code": "US", "subdivision_code": "US-NY", "city": "New York"}]})
    db.expire_all()
    live = db.query(ClientLocation).filter(ClientLocation.organization_id == cid, ClientLocation.deleted_at.is_(None)).all()
    assert [loc.site_name for loc in live] == ["HQ"]


def test_submit_missing_caico_422_lists_field(client, db, people):
    login_as(client, db, people["aud"])
    ids = _new(client)
    complete(client, ids["client_id"], people, caico=False)
    r = client.post(f"/api/v1/clients/{ids['client_id']}/submit")
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert {"contacts.caico.name", "contacts.caico.email", "contacts.caico.title"} <= fields
    assert db.get(Engagement, ids["engagement_id"]).status == "draft"


def test_auditor_creates_draft_only(client, db, people):
    login_as(client, db, people["aud"])
    ids = _new(client)
    cid = ids["client_id"]
    complete(client, cid, people)
    r = client.post(f"/api/v1/clients/{cid}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_approval"
    mail = db.query(OutboxMessage).filter(OutboxMessage.template_key == "engagement_submitted").one()
    assert mail.to == ["cara@futran.test"] and "ABC Corp" in mail.subject
    # locked while awaiting approval
    assert client.put(f"/api/v1/clients/{cid}/wizard/company", json={"legal_name": "X"}).status_code == 409
    # an auditor cannot approve or return it
    assert client.post(f"/api/v1/clients/{cid}/return", json={"comment": "x"}).status_code == 403
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/clients/{cid}/return", json={"comment": " "}).status_code == 422
    r = client.post(f"/api/v1/clients/{cid}/return", json={"comment": "Add the remote staff."})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    returned = db.query(OutboxMessage).filter(OutboxMessage.template_key == "engagement_returned").one()
    assert returned.to == ["alex@futran.test"] and "Add the remote staff." in returned.body_text
    login_as(client, db, people["aud"])
    w = client.get(f"/api/v1/clients/{cid}/wizard").json()
    assert w["engagement"]["returned_comment"] == "Add the remote staff."
    assert client.put(f"/api/v1/clients/{cid}/wizard/company", json={"legal_name": "ABC Corp Inc."}).status_code == 200


def test_team_rules_checked_at_submit(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    out = _put(client, cid, "scope", {"team": [
        {"user_id": people["aud2"].id, "role": "chief_auditor", "conflict_confirmed": True},
        {"user_id": people["aud"].id, "role": "auditor", "conflict_confirmed": False},
        {"user_id": people["admin"].id, "role": "auditor", "conflict_confirmed": True},
        {"user_id": "nobody", "role": "auditor", "conflict_confirmed": True},
    ]})
    assert {e["message"] for e in out["errors"]} >= {"Ada Admin is an administrator and cannot be on an audit team.", "Choose a Futran team member."}
    r = client.post(f"/api/v1/clients/{cid}/submit")
    msgs = [e["message"] for e in r.json()["errors"] if e["field"].startswith("scope.team")]
    assert "Bea Auditor is not a Chief Auditor." in msgs
    assert "Alex Auditor has not confirmed there is no conflict of interest." in msgs
    assert "Choose an Engagement Manager." in msgs


def test_planned_systems_and_contacts_stored(client, db, people):
    login_as(client, db, people["aud"])
    ids = _new(client)
    complete(client, ids["client_id"], people)
    e = db.get(Engagement, ids["engagement_id"])
    db.refresh(e)
    assert e.planned_systems == ["HireScore", "Resume parser"]
    roles = {c.contact_role: c for c in db.query(ClientContact).filter_by(engagement_id=e.id, deleted_at=None)}
    assert roles["client_admin"].email == "maria@abc.test" and roles["dpo"].not_appointed
    assert roles["project_lead"].name == "Maria Lopez"
    w = client.get(f"/api/v1/clients/{ids['client_id']}/wizard").json()
    assert w["contacts"]["client_admin"]["same_as_caico"] is True and w["contacts"]["dpo"]["not_appointed"] is True
    assert w["scope"]["departments"] == ["HR and recruiting", "Engineering and IT"]


@pytest.mark.skip(reason="AISystem rows arrive with Task 22; planned_systems holds the names until then")
def test_ai_systems_included_creates_aisystem_rows():
    pass


def test_other_auditor_cannot_see_draft(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    login_as(client, db, people["aud2"])
    assert client.get(f"/api/v1/clients/{cid}/wizard").status_code == 404
    assert client.put(f"/api/v1/clients/{cid}/wizard/company", json={"legal_name": "X"}).status_code == 404


def test_contact_email_used_by_another_client_rejected(client, db, people):
    other = make_org(db, name="Other Co")
    make_user(db, other, name="Maria Elsewhere", email="maria@abc.test")
    db.commit()
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    r = client.post(f"/api/v1/clients/{cid}/submit")
    assert r.status_code == 422
    assert any(e["field"] == "contacts.caico.email" and "another organization" in e["message"] for e in r.json()["errors"])


def test_team_options_lists_futran_people(client, db, people):
    login_as(client, db, people["aud"])
    opts = client.get("/api/v1/clients/team-options").json()
    cara = next(o for o in opts if o["name"] == "Cara Chief")
    assert cara["roles"] == ["chief_auditor"] and not any(o["name"] == "Ada Admin" for o in opts)
