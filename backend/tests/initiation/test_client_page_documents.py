"""Client page: laws table and stage documents with view and edit (fixes 2026-10-27, items 2a and 2b)."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.engagements.models import Engagement
from app.notifications.models import Notification
from app.signoffs.models import SignOff
from app.tenancy.models import User
from tests.factories import login_as
from tests.initiation.conftest import APPROVAL


def _sent(client, db, people, submitted):
    cid, e = submitted()
    login_as(client, db, people["chief2"])  # Cara prepared nothing, but Alex drafted it; Dan approves
    client.get(f"/api/v1/clients/{cid}/package")
    assert client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL).status_code == 200
    maria = db.scalar(select(User).where(User.email == "maria@abc.test"))
    maria.status = "active"
    db.commit()
    return cid, e, maria


def _docs(client, cid):
    page = client.get(f"/api/v1/clients/{cid}").json()
    return {d["item"]: d for d in page["package"]["documents"]}, page


def test_laws_in_scope_carry_jurisdiction_citation_and_effective_date(client, db, people, submitted):
    from app.laws.models import Regulation

    cid, _ = submitted()
    reg = db.scalar(select(Regulation).where(Regulation.short_name == "NYC Local Law 144", Regulation.retired_in_version_id.is_(None)))
    reg.citation, reg.effective_date_text = "N.Y.C. Admin. Code §§ 20-870 to 20-874", "July 5, 2023"
    db.commit()
    login_as(client, db, people["chief"])
    laws = client.get(f"/api/v1/clients/{cid}").json()["laws"]
    ll144 = next(x for x in laws if x["label"] == "NYC Local Law 144")
    assert ll144["jurisdiction"] == "New York City"
    assert ll144["citation"] == "N.Y.C. Admin. Code §§ 20-870 to 20-874" and ll144["effective_date"] == "July 5, 2023"
    assert all("citation" in x and "effective_date" in x for x in laws)


def test_chief_auditor_edits_a_sent_document_and_the_client_is_told(client, db, people, submitted):
    cid, e, maria = _sent(client, db, people, submitted)
    login_as(client, db, people["chief"])
    docs, page = _docs(client, cid)
    roles_note = docs[2]
    assert roles_note["can_edit"] is True and roles_note["signed"] is False
    assert docs[3]["can_edit"] is False  # a CSV built from the engagement details
    r = client.put(f"/api/v1/packages/documents/{roles_note['id']}", json={"body_md": "# Roles\n\nName your Executive Sponsor by Friday."})
    assert r.status_code == 200, r.text
    assert r.json()["pdf_file_id"] != roles_note["pdf_file_id"] and r.json()["docx_file_id"] != roles_note["docx_file_id"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "package.edit_document", AuditLog.object_id == roles_note["id"])) is not None
    note = db.scalar(select(Notification).where(Notification.user_id == maria.id, Notification.kind == "document_changed"))
    assert note is not None and roles_note["title"] in note.title and note.link == "/start"
    # Futran staff are not notified about their own change
    assert db.scalar(select(Notification).where(Notification.user_id == people["chief"].id, Notification.kind == "document_changed")) is None


def test_auditor_cannot_edit(client, db, people, submitted):
    cid, e, _ = _sent(client, db, people, submitted)
    login_as(client, db, people["aud"])
    docs, _ = _docs(client, cid)
    assert docs[2]["can_edit"] is False
    assert client.put(f"/api/v1/packages/documents/{docs[2]['id']}", json={"body_md": "x"}).status_code in (403, 404)


def test_signed_engagement_letter_is_locked(client, db, people, submitted):
    cid, e, maria = _sent(client, db, people, submitted)
    login_as(client, db, people["chief"])
    letter = _docs(client, cid)[0][1]
    assert letter["can_edit"] is True
    so = db.scalar(select(SignOff).where(SignOff.engagement_id == e.id, SignOff.number == 1))
    login_as(client, db, maria)
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Maria Lopez"}).status_code == 200
    login_as(client, db, people["chief"])
    letter = _docs(client, cid)[0][1]
    assert letter["signed"] is True and letter["can_edit"] is False
    r = client.put(f"/api/v1/packages/documents/{letter['id']}", json={"body_md": "# Changed"})
    assert r.status_code == 409 and "signed" in r.json()["detail"]


def test_closed_engagement_documents_are_not_edited(client, db, people, submitted):
    cid, e, _ = _sent(client, db, people, submitted)
    db.get(Engagement, e.id).status = "completed"
    db.commit()
    login_as(client, db, people["chief"])
    docs, _ = _docs(client, cid)
    assert docs[2]["can_edit"] is False
    assert client.put(f"/api/v1/packages/documents/{docs[2]['id']}", json={"body_md": "# x"}).status_code == 409
