"""F18: threaded comments with internal / shared visibility and @mentions (spec §21 F18)."""
from datetime import timedelta

from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.comments.models import Comment
from app.mail.models import OutboxMessage
from app.notifications.models import Notification

API = "/api/v1"


def _post(client, obj_type, obj_id, body="Please attach the bias test report.", **kw):
    return client.post(f"{API}/comments", json={"object_type": obj_type, "object_id": obj_id, "body": body, **kw})


def _threads(client, obj_type, obj_id):
    r = client.get(f"{API}/comments", params={"object_type": obj_type, "object_id": obj_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_futran_comments_default_internal_and_client_never_sees_them(client, w):
    w.as_(w.aud)
    r = _post(client, "finding", w.finding.id, body="Check whether the vendor test covered Pune applicants.")
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "internal"
    s = _post(client, "finding", w.finding.id, body="Can you send the vendor's bias test summary?", visibility="shared")
    assert s.json()["visibility"] == "shared"
    assert len(_threads(client, "finding", w.finding.id)["threads"]) == 2
    w.as_(w.caico)
    seen = _threads(client, "finding", w.finding.id)["threads"]
    assert [t["body"] for t in seen] == ["Can you send the vendor's bias test summary?"]
    assert "Pune" not in client.get(f"{API}/comments", params={"object_type": "finding", "object_id": w.finding.id}).text


def test_client_comments_are_shared_and_cannot_be_internal(client, w):
    w.as_(w.caico)
    r = _post(client, "finding", w.finding.id, body="We have asked the vendor for the report.")
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "shared" and r.json()["author_side"] == "client"
    assert _post(client, "finding", w.finding.id, visibility="internal").status_code == 422
    w.as_(w.aud)
    assert [t["body"] for t in _threads(client, "finding", w.finding.id)["threads"]] == ["We have asked the vendor for the report."]


def test_draft_findings_take_internal_comments_only(client, w):
    w.as_(w.aud)
    assert _post(client, "finding", w.draft.id, visibility="shared").status_code == 422
    out = _threads(client, "finding", w.draft.id)
    assert out["shared_allowed"] is False and out["visibility_options"] == ["internal"]
    assert _post(client, "finding", w.draft.id).json()["visibility"] == "internal"
    w.as_(w.caico)  # the client cannot see a draft finding at all
    assert client.get(f"{API}/comments", params={"object_type": "finding", "object_id": w.draft.id}).status_code == 404
    assert _post(client, "finding", w.draft.id).status_code == 404


def test_other_tenants_and_unassigned_auditors_get_404(client, w):
    w.as_(w.aud)
    _post(client, "finding", w.finding.id, visibility="shared")
    for user in (w.x_caico, w.aud2):
        w.as_(user)
        assert client.get(f"{API}/comments", params={"object_type": "finding", "object_id": w.finding.id}).status_code == 404
        assert _post(client, "finding", w.finding.id).status_code == 404
    w.as_(w.caico)
    assert client.get(f"{API}/comments", params={"object_type": "finding", "object_id": w.x_finding.id}).status_code == 404
    assert client.get(f"{API}/comments", params={"object_type": "nonsense", "object_id": w.finding.id}).status_code == 422


def test_department_scope_applies_to_client_users(client, w):
    w.as_(w.hr_lead)
    for t, oid in (("remediation", w.item.id), ("response", w.resp.id), ("evidence_request", w.er.id), ("finding", w.finding.id)):
        assert _post(client, t, oid, body=f"HR note on {t}").status_code == 200, t
    w.as_(w.fin_lead)  # the system belongs to HR
    for t, oid in (("remediation", w.item.id), ("response", w.resp.id), ("evidence_request", w.er.id), ("finding", w.finding.id)):
        assert client.get(f"{API}/comments", params={"object_type": t, "object_id": oid}).status_code in (403, 404), t


def test_internal_comment_cannot_mention_client_people(client, w):
    w.as_(w.aud)
    r = _post(client, "finding", w.finding.id, body="@Maria Lopez see this", mention_ids=[w.caico.id])
    assert r.status_code == 422
    assert "Futran" in r.text
    people = client.get(f"{API}/comments/mentionable", params={"object_type": "finding", "object_id": w.finding.id, "visibility": "internal"}).json()["people"]
    assert {p["id"] for p in people} == {w.chief.id, w.aud.id}
    people = client.get(f"{API}/comments/mentionable", params={"object_type": "finding", "object_id": w.finding.id, "visibility": "shared"}).json()["people"]
    ids = {p["id"] for p in people}
    assert {w.chief.id, w.aud.id, w.caico.id, w.hr_lead.id} <= ids
    assert w.fin_lead.id not in ids and w.x_caico.id not in ids and w.aud2.id not in ids


def test_mentions_notify_in_app_and_by_email(client, db, w):
    w.as_(w.aud)
    r = _post(client, "finding", w.finding.id, body="@Maria Lopez please confirm the owner.", visibility="shared", mention_ids=[w.caico.id])
    assert r.status_code == 200, r.text
    n = db.scalar(select(Notification).where(Notification.user_id == w.caico.id, Notification.kind == "comment_mention"))
    assert n is not None and n.link == "/responses"
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.to.contains("maria@abc.test"))) is not None
    i = _post(client, "finding", w.finding.id, body="@Cara Chief internal view please", mention_ids=[w.chief.id])
    assert i.status_code == 200
    n2 = db.scalar(select(Notification).where(Notification.user_id == w.chief.id, Notification.kind == "comment_mention"))
    assert n2 is not None and n2.link == f"/clients/{w.org.id}/findings"
    # a mention of someone who cannot see the object (Finance lead on an HR finding) or another tenant is refused
    assert _post(client, "finding", w.finding.id, visibility="shared", mention_ids=[w.fin_lead.id]).status_code == 422
    assert _post(client, "finding", w.finding.id, visibility="shared", mention_ids=[w.x_caico.id]).status_code == 422


def test_replies_inherit_visibility_and_notify_the_thread_author(client, db, w):
    w.as_(w.aud)
    internal = _post(client, "finding", w.finding.id, body="Internal thread").json()
    shared = _post(client, "finding", w.finding.id, body="Shared thread", visibility="shared").json()
    w.as_(w.chief)
    reply = client.post(f"{API}/comments", json={"object_type": "finding", "object_id": w.finding.id, "body": "Agreed", "parent_id": internal["id"], "visibility": "shared"})
    assert reply.status_code == 200 and reply.json()["visibility"] == "internal"
    assert db.scalar(select(Notification).where(Notification.user_id == w.aud.id, Notification.kind == "comment_reply")) is not None
    w.as_(w.caico)
    assert client.post(f"{API}/comments", json={"object_type": "finding", "object_id": w.finding.id, "body": "x", "parent_id": internal["id"]}).status_code == 404
    ok = client.post(f"{API}/comments", json={"object_type": "finding", "object_id": w.finding.id, "body": "Report attached", "parent_id": shared["id"]})
    assert ok.status_code == 200
    thread = [t for t in _threads(client, "finding", w.finding.id)["threads"] if t["id"] == shared["id"]][0]
    assert [x["body"] for x in thread["replies"]] == ["Report attached"]


def test_edit_within_15_minutes_by_the_author_only(client, db, w):
    w.as_(w.aud)
    c = _post(client, "finding", w.finding.id, body="Frist draft").json()
    w.as_(w.chief)
    assert client.patch(f"{API}/comments/{c['id']}", json={"body": "Hijack"}).status_code == 403
    w.as_(w.aud)
    r = client.patch(f"{API}/comments/{c['id']}", json={"body": "First draft"})
    assert r.status_code == 200 and r.json()["body"] == "First draft" and r.json()["edited_at"]
    row = db.get(Comment, c["id"])
    row.created_at = row.created_at - timedelta(minutes=16)
    db.commit()
    assert client.patch(f"{API}/comments/{c['id']}", json={"body": "Too late"}).status_code == 409
    assert db.scalar(select(AuditLog).where(AuditLog.action == "comment.edited", AuditLog.object_id == c["id"])) is not None


def test_withdraw_keeps_the_record_and_hides_the_text(client, db, w):
    w.as_(w.aud)
    c = _post(client, "finding", w.finding.id, body="Wrong finding, sorry", visibility="shared").json()
    assert client.delete(f"{API}/comments/{c['id']}").status_code in (404, 405)
    w.as_(w.chief)
    assert client.post(f"{API}/comments/{c['id']}/withdraw", json={}).status_code == 403
    w.as_(w.aud)
    assert client.post(f"{API}/comments/{c['id']}/withdraw", json={"reason": "Posted on the wrong finding"}).status_code == 200
    row = db.get(Comment, c["id"])
    assert row is not None and row.withdrawn_at is not None and row.body == "Wrong finding, sorry"
    log = db.scalar(select(AuditLog).where(AuditLog.action == "comment.withdrawn", AuditLog.object_id == c["id"]))
    assert log is not None and log.before["body"] == "Wrong finding, sorry"
    w.as_(w.caico)
    t = _threads(client, "finding", w.finding.id)["threads"][0]
    assert t["withdrawn"] is True and t["body"] is None
    assert client.patch(f"{API}/comments/{c['id']}", json={"body": "x"}).status_code in (403, 409)


def test_counts_respect_visibility(client, w):
    w.as_(w.aud)
    _post(client, "finding", w.finding.id, body="internal")
    _post(client, "finding", w.finding.id, body="shared", visibility="shared")
    r = client.get(f"{API}/comments/counts", params={"object_type": "finding", "ids": f"{w.finding.id},{w.draft.id}"})
    assert r.status_code == 200 and r.json()["counts"] == {w.finding.id: 2}
    w.as_(w.caico)
    r = client.get(f"{API}/comments/counts", params={"object_type": "finding", "ids": f"{w.finding.id},{w.draft.id},{w.x_finding.id}"})
    assert r.json()["counts"] == {w.finding.id: 1}


def test_bell_filters_and_mark_all_read(client, db, w):
    w.as_(w.aud)
    _post(client, "finding", w.finding.id, body="@Cara Chief", mention_ids=[w.chief.id])
    from app.notifications.service import notify

    notify(db, [w.chief], "finding_returned", "Finding F-002 was returned to you")
    db.commit()
    w.as_(w.chief)
    allx = client.get(f"{API}/me/notifications").json()
    assert allx["unread"] == 2 and allx["mentions_unread"] == 1
    m = client.get(f"{API}/me/notifications", params={"filter": "mentions"}).json()["items"]
    assert [x["kind"] for x in m] == ["comment_mention"]
    client.post(f"{API}/notifications/{m[0]['id']}/read")
    u = client.get(f"{API}/me/notifications", params={"filter": "unread"}).json()["items"]
    assert [x["kind"] for x in u] == ["finding_returned"]
    assert client.get(f"{API}/me/notifications", params={"filter": "bogus"}).status_code == 422
    client.post(f"{API}/notifications/read-all")
    assert client.get(f"{API}/me/notifications").json()["unread"] == 0
