"""Confirming carried answers stays within what was asked and what the person covers: "confirm all for this system"
leaves organization-wide answers alone, and only people whose role covers the whole organization confirm those."""
from sqlalchemy import select

from app.annual.models import CarriedAnswer
from app.questionnaire.models import Response
from app.questionnaire.service import Target, save_response
from app.systems.models import AISystem
from app.tenancy.models import User
from tests.annual.test_carry_forward import _client_answers, _close, _start
from tests.factories import login_as


def _setup(client, db, ats, people):
    cid, e, maria, s = ats
    _client_answers(db, maria, e, s)
    save_response(db, maria, Target(e, None), "4.1.01", {"value": "yes", "status": "answered"}, futran=False)  # organization-wide
    db.commit()
    prior = _close(db, e)
    new = _start(client, db, people, prior)
    new.status = "initiated"
    db.commit()
    ns = db.scalar(select(AISystem).where(AISystem.engagement_id == new.id, AISystem.reference_id == "SYS-001"))
    org_wide = db.scalar(select(Response).where(Response.engagement_id == new.id, Response.ai_system_id.is_(None)))
    assert org_wide is not None
    return cid, maria, new, ns, org_wide


def _status(db, r):
    db.expire_all()
    return db.scalar(select(CarriedAnswer).where(CarriedAnswer.response_id == r.id)).status


def test_confirm_all_for_a_system_leaves_organization_wide_answers(client, db, ats, people):
    cid, maria, new, ns, org_wide = _setup(client, db, ats, people)
    login_as(client, db, maria)
    n_sys = len(list(db.scalars(select(CarriedAnswer).join(Response, Response.id == CarriedAnswer.response_id).where(CarriedAnswer.engagement_id == new.id, Response.ai_system_id == ns.id))))
    r = client.post(f"/api/v1/engagements/{new.id}/carried/confirm-unchanged", json={"system_id": ns.id})
    assert r.status_code == 200 and r.json()["confirmed"] == n_sys
    assert _status(db, org_wide) == "pending"
    r = client.post(f"/api/v1/engagements/{new.id}/carried/confirm-unchanged")
    assert r.status_code == 200 and r.json()["confirmed"] == 1 and _status(db, org_wide) == "confirmed"  # the whole organization, by the CAICO


def test_a_department_scoped_person_cannot_confirm_organization_wide_answers(client, db, ats, people):
    cid, maria, new, ns, org_wide = _setup(client, db, ats, people)
    priya = db.scalar(select(User).where(User.email == "priya@abc.test"))  # Department Compliance Lead, HR (SYS-001 is HR's)
    login_as(client, db, priya)
    r = client.post(f"/api/v1/engagements/{new.id}/carried/confirm-unchanged")
    assert r.status_code == 200 and r.json()["confirmed"] > 0
    assert _status(db, org_wide) == "pending"
    assert client.post(f"/api/v1/responses/{org_wide.id}/confirm-carried").status_code == 403
    assert _status(db, org_wide) == "pending"
    login_as(client, db, maria)
    assert client.post(f"/api/v1/responses/{org_wide.id}/confirm-carried").status_code == 200
