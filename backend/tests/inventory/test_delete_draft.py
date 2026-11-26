"""BUG-03: a draft use case that was never submitted can be deleted by its creator or the CAICO, logged in the audit log,
so a stray draft no longer blocks the department and organisation sign-offs."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.inventory.models import NamedUser, UseCase
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import _uc, inv  # noqa: F401


def _user(db, email):
    return db.scalar(select(User).where(User.email == email))


def _draft(client, db, inv, who="tom@abc.test", **kw):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, _user(db, who) if who != "maria" else maria)
    return _uc(client, cid, hr, [copilot["id"]], name="Stray draft", **kw)


def test_the_creator_deletes_a_draft_and_it_is_logged(client, db, inv):
    cid, e, *_ = inv
    uc = _draft(client, db, inv, named_users=[{"person_name": "Eve Long", "email": "eve@abc.test", "role_name": "Recruiter"}])
    r = client.delete(f"/api/v1/use-cases/{uc['id']}")
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/use-cases/{uc['id']}").status_code == 404
    row = db.get(UseCase, uc["id"])
    db.refresh(row)
    assert row.deleted_at is not None  # kept for the record, out of every list
    assert all(n.deleted_at is not None for n in db.scalars(select(NamedUser).where(NamedUser.use_case_id == uc["id"])))
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "inventory.delete", AuditLog.object_id == uc["id"]))
    assert entry is not None and "Stray draft" in entry.summary
    assert all(u["id"] != uc["id"] for u in client.get(f"/api/v1/clients/{cid}/inventory").json()["use_cases"])


def test_the_caico_deletes_someone_elses_draft(client, db, inv):
    uc = _draft(client, db, inv)
    cid, e, maria, *_ = inv
    login_as(client, db, maria)
    assert client.delete(f"/api/v1/use-cases/{uc['id']}").status_code == 200


def test_anyone_else_is_refused(client, db, inv, people):
    uc = _draft(client, db, inv)
    login_as(client, db, _user(db, "priya@abc.test"))  # the Department Compliance Lead, not the creator
    assert client.delete(f"/api/v1/use-cases/{uc['id']}").status_code == 403
    login_as(client, db, people["chief"])  # Futran does not delete the client's records
    assert client.delete(f"/api/v1/use-cases/{uc['id']}").status_code in (403, 404)
    assert db.get(UseCase, uc["id"]).deleted_at is None


def test_a_use_case_that_was_ever_submitted_is_kept(client, db, inv):
    uc = _draft(client, db, inv)
    assert client.post(f"/api/v1/use-cases/{uc['id']}/submit").status_code == 200
    r = client.delete(f"/api/v1/use-cases/{uc['id']}")
    assert r.status_code == 409
    login_as(client, db, _user(db, "priya@abc.test"))
    assert client.post(f"/api/v1/use-cases/{uc['id']}/review", json={"approve": False, "comment": "Add the data categories."}).status_code == 200
    login_as(client, db, _user(db, "tom@abc.test"))
    assert client.delete(f"/api/v1/use-cases/{uc['id']}").status_code == 409  # returned: it was submitted once


def test_a_draft_already_mapped_to_an_ai_system_is_kept(client, db, inv):
    from app.systems.models import AISystem

    cid, e, *_ = inv
    uc = _draft(client, db, inv)
    db.add(AISystem(organization_id=cid, engagement_id=e.id, name="Screening", reference_id="SYS-009", use_case_ids=[uc["id"]], tool_ids=[]))
    db.commit()
    r = client.delete(f"/api/v1/use-cases/{uc['id']}")
    assert r.status_code == 409 and "SYS-009" in r.json()["detail"]


def test_a_draft_named_in_an_evidence_request_is_kept(client, db, inv, people):
    """From the 20 Nov hand-off build (BUG-03 fix round 1, M-6): the Futran team's evidence request refers to it."""
    from datetime import date

    from app.docrequests.models import EvidenceRequest

    cid, e, *_ = inv
    uc = _draft(client, db, inv)
    db.add(EvidenceRequest(organization_id=cid, engagement_id=e.id, ref="ER-001", use_case_id=uc["id"], description="Retention settings",
                           requested_by=people["aud"].id, due_date=date(2026, 12, 1)))
    db.commit()
    r = client.delete(f"/api/v1/use-cases/{uc['id']}")
    assert r.status_code == 409 and "ER-001" in r.json()["detail"]
    db.expire_all()
    assert db.get(UseCase, uc["id"]).deleted_at is None
