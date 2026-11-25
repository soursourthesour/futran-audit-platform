"""Y04: the Chief Auditor does not approve an intro letter they drafted or edited (spec §6 rule 2)."""
from app.regmaster.models import IntroLetter
from tests.factories import login_as
from tests.regmaster.test_api import API, _futran

SOD = "You prepared this item, so you cannot approve it. Another approver must sign it off."


def _draft(client, db, seeded, submitted, drafter):
    cid, e = submitted()
    login_as(client, db, drafter)
    d = client.post(f"{API}/clients/{cid}/letters")
    assert d.status_code == 200, d.text
    return cid, d.json()


def test_the_chief_who_drafted_the_letter_cannot_approve_it(client, db, seeded, submitted):
    cid, d = _draft(client, db, seeded, submitted, seeded["chief"])
    r = client.post(f"{API}/clients/{cid}/letters/{d['id']}/approve")
    assert r.status_code == 403 and r.json()["detail"] == SOD
    db.expire_all()
    assert db.get(IntroLetter, d["id"]).status == "draft"
    login_as(client, db, seeded["chief2"])
    assert client.post(f"{API}/clients/{cid}/letters/{d['id']}/approve").status_code == 200


def test_the_chief_who_edited_the_letter_cannot_approve_it(client, db, seeded, submitted):
    admin = _futran(db, "admin", "Ada Admin")
    cid, d = _draft(client, db, seeded, submitted, admin)
    login_as(client, db, seeded["chief"])
    assert client.patch(f"{API}/clients/{cid}/letters/{d['id']}", json={"opening": "Thank you for choosing Futran."}).status_code == 200
    r = client.post(f"{API}/clients/{cid}/letters/{d['id']}/approve")
    assert r.status_code == 403 and r.json()["detail"] == SOD


def test_a_letter_the_admin_drafted_is_approved_by_the_chief(client, db, seeded, submitted):
    admin = _futran(db, "admin", "Ada Admin")
    cid, d = _draft(client, db, seeded, submitted, admin)
    login_as(client, db, seeded["chief"])
    r = client.post(f"{API}/clients/{cid}/letters/{d['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
