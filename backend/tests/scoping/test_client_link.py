"""SM-06 and SM-07: a personal no-login link from the rep's mailbox; internal questions never on it; token hashed,
expiring and rate limited; save and continue, forward to a colleague, submit; reminders on day 3 and 7; the owner is
told when the client completes or partly completes it (spec §4.10)."""
import re
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utcnow
from app.mail.models import MailSend, OutboxMessage
from app.notifications.models import Notification
from app.scoping import sending, service
from app.scoping.models import QuestionnaireSend
from tests.factories import login_as

LINK = re.compile(r"/q/([A-Za-z0-9_\-]+)")


def _send(client, db, world, codes=None, **kw):
    login_as(client, db, world["sales"])
    opp = world["opp"]
    q = client.post(f"/api/v1/scoping/opportunities/{opp.id}/start").json()
    body = {"contact": {"name": "Pat Champion", "email": "pat@acme.example"}, "question_codes": codes or ["SQ-C.07", "SQ-C.08", "SQ-D.02", "SQ-A.02"],
            "due_on": (utcnow().date() + timedelta(days=10)).isoformat(), "reminders": [3, 7], "allow_forward": True, **kw}
    r = client.post(f"/api/v1/scoping/{q['id']}/send", json=body)
    assert r.status_code == 200, r.text
    mail = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "scoping_questionnaire").order_by(OutboxMessage.created_at.desc())).first()
    token = LINK.search(mail.body_text).group(1)
    client.cookies.clear()
    return q, r.json(), token, mail


def test_send_goes_from_the_reps_mailbox_with_a_hashed_expiring_link_and_no_internal_questions(client, db, world):
    q, sent, token, mail = _send(client, db, world)
    assert mail.to == ["pat@acme.example"] and "Open the questions" in mail.body_html
    ms = db.get(MailSend, mail.mail_send_id)
    assert ms.sent_by == world["sales"].id and ms.related_type == "QuestionnaireSend"
    row = db.get(QuestionnaireSend, sent["id"])
    assert row.token_hash != token and len(row.token_hash) == 64 and token not in str(row.__dict__)
    assert row.question_codes == ["SQ-C.07", "SQ-C.08", "SQ-D.02"]  # the internal budget question is dropped
    assert (row.expires_at - row.sent_at).days == 14 and row.reminder_days == [3, 7]
    view = client.get(f"/api/v1/public/q/{token}").json()
    codes = [x["code"] for s in view["sections"] for x in s["questions"]]
    assert codes == ["SQ-C.07", "SQ-C.08", "SQ-D.02"] and view["company"] == "Acme Staffing LLC"
    assert "Budget" not in str(view) and "SQ-A.02" not in str(view)
    assert view["questions_label"] and "not legal advice" in view["footer"].lower()
    assert client.get("/api/v1/public/q/not-a-real-token").status_code == 404


def test_client_saves_as_they_go_and_submits_and_the_owner_is_told(client, db, world, settings):
    q, sent, token, _ = _send(client, db, world)
    r = client.put(f"/api/v1/public/q/{token}/answers", json={"answers": [{"code": "SQ-C.07", "value": 12}, {"code": "SQ-A.02", "value": "$5k"},
                                                                         {"code": "SQ-C.08", "confidence": "unknown"}]})
    assert r.status_code == 200
    qq = service.get(db, q["id"])
    eff = service.effective_answers(db, qq)
    assert eff["SQ-C.07"].value == 12 and eff["SQ-C.07"].source == "client" and "SQ-A.02" not in eff
    assert eff["SQ-C.08"].confidence == "unknown" and qq.status == "client_in_progress"
    view = client.get(f"/api/v1/public/q/{token}").json()
    assert view["answers"]["SQ-C.07"]["value"] == 12
    assert client.post(f"/api/v1/public/q/{token}/submit").status_code == 200
    n = db.scalar(select(Notification).where(Notification.user_id == world["sales"].id, Notification.kind == "scoping_client_answers"))
    assert n is not None and "partly completed" in n.title  # SQ-D.02 is still blank
    assert db.get(QuestionnaireSend, sent["id"]).status == "submitted"
    assert client.put(f"/api/v1/public/q/{token}/answers", json={"answers": [{"code": "SQ-D.02", "value": 2}]}).status_code == 409


def test_forward_to_a_colleague_gives_them_their_own_link(client, db, world):
    q, sent, token, _ = _send(client, db, world)
    r = client.post(f"/api/v1/public/q/{token}/forward", json={"name": "Tom Tech", "email": "tom@acme.example"})
    assert r.status_code == 200
    mail = db.scalars(select(OutboxMessage).where(OutboxMessage.template_key == "scoping_questionnaire").order_by(OutboxMessage.created_at.desc())).first()
    assert mail.to == ["tom@acme.example"]
    token2 = LINK.search(mail.body_text).group(1)
    assert token2 != token
    fwd = db.scalar(select(QuestionnaireSend).where(QuestionnaireSend.forwarded_from_id == sent["id"]))
    assert fwd.contact_email == "tom@acme.example" and fwd.question_codes == db.get(QuestionnaireSend, sent["id"]).question_codes
    assert client.get(f"/api/v1/public/q/{token2}").status_code == 200
    assert client.post(f"/api/v1/public/q/{token}/forward", json={"name": "X", "email": "not-an-email"}).status_code == 422


def test_links_expire_close_on_lock_and_are_rate_limited(client, db, world):
    q, sent, token, _ = _send(client, db, world)
    row = db.get(QuestionnaireSend, sent["id"])
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/v1/public/q/{token}").status_code == 410
    row.expires_at = utcnow() + timedelta(days=1)
    db.commit()
    for _ in range(60):
        client.get(f"/api/v1/public/q/{token}")
    assert client.get(f"/api/v1/public/q/{token}").status_code == 429


def test_lock_closes_the_link(client, db, world):
    q, sent, token, _ = _send(client, db, world)
    service.lock(db, q["id"], world["sales"])
    db.commit()
    assert client.get(f"/api/v1/public/q/{token}").status_code == 410


def test_reminders_day_3_and_7_carry_a_fresh_link_and_stop_after_submit(db, world, settings, client):
    q, sent, token, _ = _send(client, db, world)
    row = db.get(QuestionnaireSend, sent["id"])
    start = row.sent_at
    assert sending.run_reminders(db, settings, start + timedelta(days=2)) == 0
    assert sending.run_reminders(db, settings, start + timedelta(days=3, hours=1)) == 1
    assert sending.run_reminders(db, settings, start + timedelta(days=4)) == 0  # day 3 is sent once
    assert row.reminders_sent == [3]
    assert client.get(f"/api/v1/public/q/{token}").status_code == 404  # replaced by the reminder's link
    row.submitted_at, row.status = utcnow(), "submitted"
    db.commit()
    assert sending.run_reminders(db, settings, start + timedelta(days=8)) == 0


def test_partly_answered_link_past_due_tells_the_owner_once(db, world, settings, client):
    q, sent, token, _ = _send(client, db, world)
    client.put(f"/api/v1/public/q/{token}/answers", json={"answers": [{"code": "SQ-C.07", "value": 12}]})
    row = db.get(QuestionnaireSend, sent["id"])
    after_due = utcnow() + timedelta(days=11)
    sending.run_reminders(db, settings, after_due)
    sending.run_reminders(db, settings, after_due + timedelta(days=1))
    notes = list(db.scalars(select(Notification).where(Notification.user_id == world["sales"].id, Notification.kind == "scoping_client_answers")))
    assert len(notes) == 1 and "partly completed" in notes[0].title and row.partial_notified_at is not None
