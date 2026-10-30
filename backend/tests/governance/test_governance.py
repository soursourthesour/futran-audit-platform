from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.governance.models import Commitment, GovernanceItem, GovernanceRequest
from app.governance.service import coverage
from app.notifications.models import Notification
from tests.factories import login_as, make_org, make_user
from tests.initiation.conftest import live, people, submitted  # noqa: F401

LATER = (date.today() + timedelta(days=60)).isoformat()


def _gov(client, cid):
    r = client.get(f"/api/v1/clients/{cid}/governance")
    assert r.status_code == 200, r.text
    return r.json()


def _item(g, code):
    return next(i for i in g["items"] if i["code"] == code)


def test_request_created_at_approval_with_default_items(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    g = _gov(client, cid)
    codes = [i["code"] for i in g["items"]]
    assert "GD-05" not in codes and "GR-08" not in codes  # optional item and EU contact are not requested by default
    assert {"GD-01", "SD-01", "GR-01", "GR-07"} <= set(codes)
    assert g["request"]["status"] == "open" and g["request"]["requested_by"] == "Cara Chief"
    assert g["counts"] == {"roles": {"answered": 0, "total": 7}, "documents": {"answered": 0, "total": 9}}


def test_in_place_requires_names(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    item = _item(_gov(client, cid), "GR-03")
    r = client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "in_place", "names": []})
    assert r.status_code == 422 and r.json()["errors"][0] == {"field": "names", "message": "Name the people who hold this role."}
    r = client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "in_place", "names": [{"name": "Dana Kim", "title": "Head of Data Science"}]})
    assert r.status_code == 200 and r.json()["status"] == "in_place"
    # a document in place needs a file
    doc = _item(_gov(client, cid), "GD-01")
    r = client.put(f"/api/v1/governance/items/{doc['id']}", json={"status": "in_place"})
    assert r.status_code == 422 and r.json()["errors"][0]["message"] == "Upload the document first."
    up = client.post(f"/api/v1/governance/items/{doc['id']}/files", files={"file": ("charter.pdf", b"%PDF-1.4 charter", "application/pdf")})
    assert up.status_code == 200 and up.json()["status"] == "in_place" and len(up.json()["files"]) == 1
    assert client.get(f"/api/v1/files/{up.json()['files'][0]['id']}").status_code == 200


def test_will_constitute_creates_commitment(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    item = _item(_gov(client, cid), "GR-02")
    r = client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "planned"})
    assert {x["field"] for x in r.json()["errors"]} == {"target_date", "interim_owner"}
    past = (date.today() - timedelta(days=1)).isoformat()
    r = client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "planned", "target_date": past, "interim_owner": "Maria Lopez"})
    assert r.json()["errors"][0] == {"field": "target_date", "message": "The target date must be in the future."}
    r = client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "planned", "target_date": LATER, "interim_owner": "Maria Lopez", "planned_members": "HR, Legal, Data science"})
    assert r.status_code == 200
    c = db.scalar(select(Commitment).where(Commitment.source_id == item["id"], Commitment.deleted_at.is_(None)))
    assert c.description == "Constitute bias and fairness review committee" and c.owner == "Maria Lopez" and c.target_date.isoformat() == LATER
    assert c.source == "governance_role" and c.status == "open"
    # changing the answer withdraws the commitment
    client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "in_place", "names": [{"name": "Priya Shah", "title": "Chair"}], "chair": "Priya Shah"})
    assert db.scalar(select(Commitment).where(Commitment.source_id == item["id"], Commitment.deleted_at.is_(None))) is None
    doc = _item(_gov(client, cid), "GD-04")
    client.put(f"/api/v1/governance/items/{doc['id']}", json={"status": "planned", "target_date": LATER, "interim_owner": "Tom Reyes"})
    assert _gov(client, cid)["commitments"][0]["description"] == "Create AI acceptable use policy"


def test_na_requires_reason(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    item = _item(_gov(client, cid), "GR-04")
    r = client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "not_applicable", "na_reason": "  "})
    assert r.status_code == 422 and r.json()["errors"][0] == {"field": "na_reason", "message": "Say why this does not apply."}
    assert client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "not_applicable", "na_reason": "No high-risk systems yet."}).status_code == 200


def _answer_all(client, cid):
    for i in _gov(client, cid)["items"]:
        if i["status"] == "unanswered":
            client.put(f"/api/v1/governance/items/{i['id']}", json={"status": "not_applicable", "na_reason": "Not relevant to us."})


def test_submit_blocked_until_all_answered_and_accuracy(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, maria)
    r = client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": True})
    assert r.status_code == 422 and "still need an answer" in r.json()["detail"]
    _answer_all(client, cid)
    r = client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": False})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "accuracy_confirmed"
    r = client.post(f"/api/v1/clients/{cid}/governance/submit", json={"accuracy_confirmed": True})
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    # locked once submitted
    item = _gov(client, cid)["items"][0]
    assert client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "not_applicable", "na_reason": "x"}).status_code == 409
    assert {i["key"]: i["done"] for i in client.get("/api/v1/me/initiation").json()["items"]}["governance"] is True
    notes = db.scalars(select(Notification).where(Notification.kind == "governance_submitted")).all()
    assert people["chief"].id in {n.user_id for n in notes}


def test_coverage_partial_and_gap():
    def it(refs, status):
        return GovernanceItem(control_refs=refs, status=status, kind="role", catalog_code="X", title="X")

    items = [
        it(["OECD 1.5", "NIST_AI_RMF GOVERN 2"], "in_place"),
        it(["OECD 1.5", "NIST_AI_RMF GOVERN 2"], "unanswered"),
        it(["OECD 1.2", "NIST_AI_RMF MEASURE 2.11"], "planned"),
        it(["OECD 1.3", "NIST_AI_RMF MEASURE 2.9"], "in_place"),
        it(["OECD 1.4", "NIST_AI_RMF MANAGE 4"], "unanswered"),
        it(["OECD 1.4", "NIST_AI_RMF MANAGE"], "not_applicable"),
    ]
    c = coverage(items)
    assert c["oecd"] == {"1.2": "planned", "1.3": "covered", "1.4": "gap", "1.5": "partial"}
    assert c["nist"] == {"GOVERN": "partial", "MEASURE": "planned", "MANAGE": "gap"}


def test_eu_rep_only_when_eu_operations(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, people["chief"])
    g = _gov(client, cid)
    codes = [i["code"] for i in g["items"]] + ["GR-08"]
    r = client.put(f"/api/v1/clients/{cid}/governance/setup", json={"codes": codes, "due_date": LATER})
    assert r.status_code == 422 and r.json()["errors"][0]["message"] == "The EU representative contact applies only to clients with operations in the EU."
    assert "GR-08" in [o["code"] for o in g["catalog"] if not o["available"]]
    # with an EU site it becomes available
    from app.engagements.service import add_location
    from app.tenancy.models import Organization

    add_location(db, db.get(Organization, cid), site_name="Berlin office", country_code="DE", city="Berlin")
    db.commit()
    r = client.put(f"/api/v1/clients/{cid}/governance/setup", json={"codes": codes + ["GD-05"], "due_date": LATER})
    assert r.status_code == 200
    assert {"GR-08", "GD-05"} <= {i["code"] for i in _gov(client, cid)["items"]}


def test_setup_is_chief_only_and_locked_once_answered(client, db, people, live):
    cid, e, maria = live
    login_as(client, db, people["aud"])
    assert client.put(f"/api/v1/clients/{cid}/governance/setup", json={"codes": ["GD-01"], "due_date": LATER}).status_code == 403
    login_as(client, db, maria)
    item = _gov(client, cid)["items"][0]
    client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "not_applicable", "na_reason": "n/a"})
    login_as(client, db, people["chief"])
    r = client.put(f"/api/v1/clients/{cid}/governance/setup", json={"codes": ["GD-01"], "due_date": LATER})
    assert r.status_code == 409


def test_governance_visibility(client, db, people, live):
    cid, e, maria = live
    other = make_org(db, name="XYZ")
    x = make_user(db, other, roles=["caico"], name="X Caico", email="x@xyz.test")
    login_as(client, db, maria)
    client.post(f"/api/v1/clients/{cid}/departments", json={"name": "Finance"})
    client.post(f"/api/v1/clients/{cid}/users", json={"first_name": "Fay", "last_name": "Lead", "email": "fay@abc.test", "job_title": "", "department": "Finance", "role": "dept_compliance_lead"})
    from app.tenancy.models import User

    fay = db.scalar(select(User).where(User.email == "fay@abc.test"))
    fay.status = "active"
    item = _gov(client, cid)["items"][0]
    db.commit()
    login_as(client, db, x)
    assert client.get(f"/api/v1/clients/{cid}/governance").status_code == 404
    assert client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "not_applicable", "na_reason": "x"}).status_code == 404
    login_as(client, db, fay)
    assert client.get(f"/api/v1/clients/{cid}/governance").status_code == 403
    login_as(client, db, people["aud"])
    assert client.get(f"/api/v1/clients/{cid}/governance").status_code == 200
    assert client.put(f"/api/v1/governance/items/{item['id']}", json={"status": "not_applicable", "na_reason": "x"}).status_code == 403


def test_extra_fields_saved(client, db, live):
    cid, e, maria = live
    login_as(client, db, maria)
    r = client.put(f"/api/v1/clients/{cid}/governance/extra", json={"fields": {"policy_owner": "Maria Lopez", "risk_appetite": "informal", "bogus": "x"}})
    assert r.status_code == 200
    g = _gov(client, cid)
    assert g["request"]["extra_fields"] == {"policy_owner": "Maria Lopez", "risk_appetite": "informal"}
    assert any(f["key"] == "risk_appetite" and f["options"] for f in g["extra_field_defs"])


@pytest.fixture
def catalogue(db, people):
    """The §24.1 role catalogue seeded before the engagement is approved, as on a real install."""
    from app.regmaster.seed import load_roles

    load_roles(db)
    db.commit()


@pytest.fixture
def live_cat(catalogue, live):
    return live


def test_bias_review_stays_a_committee_with_the_catalogue_seeded(client, db, live_cat):
    cid, e, maria = live_cat
    login_as(client, db, maria)
    g = _gov(client, cid)
    gr02 = _item(g, "GR-02")
    assert gr02["committee"] is True and gr02["title"] == "Bias and fairness review committee"
    assert _item(g, "GR-01")["committee"] is True
    # person roles keep their catalogue link (name from the §24.1 role catalogue)
    assert _item(g, "GR-03")["committee"] is False and _item(g, "GR-03")["title"] == "Explainability contact"
    r = client.put(f"/api/v1/governance/items/{gr02['id']}", json={"status": "planned", "target_date": LATER, "interim_owner": "Maria Lopez"})
    assert r.status_code == 200, r.text
    c = db.scalar(select(Commitment).where(Commitment.source_id == gr02["id"], Commitment.deleted_at.is_(None)))
    assert c.description == "Constitute bias and fairness review committee"
    # the Futran set-up screen names each item as the client sees it
    titles = {o["code"]: o["title"] for o in g["catalog"]}
    assert all(titles[i["code"]] == i["title"] for i in g["items"])


def test_items_in_flight_are_never_rewritten(client, db, people, live_cat):
    """Items stored before the catalogue link (or under an older title) keep their title and committee flag."""
    cid, e, maria = live_cat
    req = db.scalar(select(GovernanceRequest).where(GovernanceRequest.engagement_id == e.id))
    gr02 = db.scalar(select(GovernanceItem).where(GovernanceItem.request_id == req.id, GovernanceItem.catalog_code == "GR-02"))
    gr01 = db.scalar(select(GovernanceItem).where(GovernanceItem.request_id == req.id, GovernanceItem.catalog_code == "GR-01"))
    gr02.title, gr02.committee = "Bias and fairness review committee (old)", True
    gr01.title = "AI Governance Committee"
    db.commit()
    login_as(client, db, people["chief"])
    g = _gov(client, cid)
    codes = [i["code"] for i in g["items"]] + ["GD-05"]
    assert client.put(f"/api/v1/clients/{cid}/governance/setup", json={"codes": codes, "due_date": LATER}).status_code == 200
    g = _gov(client, cid)
    assert _item(g, "GR-02")["title"] == "Bias and fairness review committee (old)" and _item(g, "GR-02")["committee"] is True
    assert _item(g, "GR-01")["title"] == "AI Governance Committee"
    titles = {o["code"]: o["title"] for o in g["catalog"]}
    assert titles["GR-02"] == "Bias and fairness review committee (old)" and titles["GR-01"] == "AI Governance Committee"
