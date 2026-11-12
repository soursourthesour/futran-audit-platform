"""SM-10 send and SM-12 public acceptance: approvals gate the send, a sent version is frozen, the personal link is hashed,
expiring, rate limited and shows only that proposal; accepting records who, when and from where, wins the opportunity
and starts the hand-off (spec §4.6, §4.10)."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid
from app.proposals import approvals, sending
from app.proposals import service as ps
from app.proposals.models import Acceptance, ProposalEvent, ProposalLink

TO = [{"name": "Dana Buyer", "email": "dana@acme.example"}]


@pytest.fixture
def ready(db, pw, settings):
    p = ps.create_blank(db, pw.opp, pw.sales)
    ps.add_line(db, pw.sales, p, "L-01", 1)
    ps.add_line(db, pw.sales, p, "M-03a", 1)
    db.commit()
    return p


def _send(db, settings, pw, p, to=TO):
    links = sending.send(db, settings, pw.sales, p, recipients=to, subject="Proposal for [Company]", message="Hi [First name],\n\nHere it is.")
    db.commit()
    return links


def _raw(monkeypatch):
    """Capture the raw tokens the send makes (only their hashes are stored)."""
    seen = []
    real = sending.new_token

    def grab():
        raw = real()
        seen.append(raw)
        return raw

    monkeypatch.setattr(sending, "new_token", grab)
    return seen


def test_send_is_refused_while_an_approval_is_missing(db, pw, settings, ready):
    ps.update_terms(db, pw.sales, ready, {"discount_recurring_pct": 10})
    with pytest.raises(Conflict) as exc:
        _send(db, settings, pw, ready)
    assert "P-2" in exc.value.detail
    [req] = approvals.request(db, pw.sales, ready)
    approvals.decide(db, pw.manager, req, "approve", "")
    _send(db, settings, pw, ready)
    assert ready.status == "sent"


def test_send_needs_a_recipient_and_no_blocked_lines(db, pw, settings, ready):
    with pytest.raises(Invalid):
        _send(db, settings, pw, ready, to=[])
    with pytest.raises(Invalid):
        _send(db, settings, pw, ready, to=[{"name": "X", "email": "not-an-email"}])


def test_send_freezes_the_version_stores_files_and_emails_a_hashed_link(db, pw, settings, ready, monkeypatch):
    from app.files.models import FileObject
    from app.mail.models import OutboxMessage

    seen = _raw(monkeypatch)
    [link] = _send(db, settings, pw, ready)
    assert ready.status == "sent" and ready.valid_until == today() + timedelta(days=30) and ready.sent_by == pw.sales.id
    assert link.token_hash != seen[0] and len(link.token_hash) == 64
    assert link.expires_at.date() == ready.valid_until + timedelta(days=1)
    for kind in ("pdf", "docx"):
        f = db.get(FileObject, ready.file_ids[kind])
        assert f is not None and f.size > 1000
    msg = db.scalar(select(OutboxMessage).where(OutboxMessage.template_key == "proposal_send"))
    assert msg.to == ["dana@acme.example"] and f"/p/{seen[0]}" in msg.body_text and "Hi Dana," in msg.body_text
    assert "AI Governix" not in msg.body_html
    assert db.scalar(select(ProposalEvent).where(ProposalEvent.proposal_id == ready.id, ProposalEvent.kind == "sent"))
    with pytest.raises(Conflict):
        ps.update_line(db, pw.sales, ready, ps.lines(db, ready)[0].id, {"qty": 3})


def test_a_new_sent_version_supersedes_the_old_one_and_its_links(db, pw, settings, ready, monkeypatch):
    seen = _raw(monkeypatch)
    _send(db, settings, pw, ready)
    v2 = ps.new_version(db, pw.sales, ready)
    _send(db, settings, pw, v2)
    assert ready.status == "superseded" and v2.status == "sent"
    r = pw.client.get(f"/api/v1/public/p/{seen[0]}")
    assert r.status_code == 410
    assert pw.client.get(f"/api/v1/public/p/{seen[1]}").status_code == 200


def test_public_page_shows_only_this_proposal_and_nothing_internal(db, pw, settings, ready, monkeypatch):
    from app.notifications.models import Notification

    seen = _raw(monkeypatch)
    ps.update_line(db, pw.sales, ready, ps.lines(db, ready)[0].id, {"override_price": 9000})
    db.commit()
    _send(db, settings, pw, ready)
    pw.client.cookies.clear()
    r = pw.client.get(f"/api/v1/public/p/{seen[0]}", headers={"user-agent": "phone"})
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "Acme Staffing LLC" and body["version"] == 1 and body["status"] == "viewed"
    assert body["totals"]["y1_total"] == ready.totals["y1_total"]
    assert [s["title"] for s in body["sections"]][:2] == ["Cover", "Your situation"]
    text = r.text
    for secret in ("rule_code", "list_price", "\"low\"", "\"high\"", "override", "8500", "P-2", "approv"):
        assert secret not in text
    link = db.scalar(select(ProposalLink).where(ProposalLink.proposal_id == ready.id))
    db.refresh(link)
    assert link.open_count == 1 and link.opened_at is not None
    assert db.scalar(select(Notification).where(Notification.user_id == pw.sales.id, Notification.kind == "proposal_opened"))
    pw.client.get(f"/api/v1/public/p/{seen[0]}")
    assert len(list(db.scalars(select(Notification).where(Notification.kind == "proposal_opened")))) == 1  # first open only
    pdf = pw.client.get(f"/api/v1/public/p/{seen[0]}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_bad_expired_and_revoked_links(db, pw, settings, ready, monkeypatch):
    seen = _raw(monkeypatch)
    [link] = _send(db, settings, pw, ready)
    assert pw.client.get("/api/v1/public/p/nonsense").status_code == 404
    link.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert pw.client.get(f"/api/v1/public/p/{seen[0]}").status_code == 410


def test_accept_records_who_when_where_wins_and_hands_off(db, pw, settings, ready, monkeypatch):
    from app.commercial import handoff

    calls = []
    monkeypatch.setattr(handoff, "create_from_acceptance", lambda db, p, a, actor: calls.append((p.id, a.id)) or type("H", (), {"id": "h1"})())
    seen = _raw(monkeypatch)
    _send(db, settings, pw, ready)
    url = f"/api/v1/public/p/{seen[0]}/accept"
    form = {"name": "Dana Buyer", "title": "COO", "email": "dana@acme.example", "po_number": "PO-778"}
    r = pw.client.post(url, data=form)
    assert r.status_code == 422  # the authority tick is required
    r = pw.client.post(url, data={**form, "authorised": "true"}, files={"po_file": ("po.pdf", b"%PDF-1.4 purchase order", "application/pdf")},
                       headers={"user-agent": "Mobile Safari"})
    assert r.status_code == 200, r.text
    a = db.scalar(select(Acceptance).where(Acceptance.proposal_id == ready.id))
    assert a.name == "Dana Buyer" and a.authorised_confirmed and a.po_number == "PO-778" and a.ip and a.user_agent == "Mobile Safari"
    assert a.po_file_id and a.handoff_id == "h1"
    db.refresh(ready)
    db.refresh(pw.opp)
    assert ready.status == "accepted" and pw.opp.stage == "won" and calls == [(ready.id, a.id)]
    assert pw.client.post(url, data={**form, "authorised": "true"}).status_code == 409
    view = pw.client.get(f"/api/v1/public/p/{seen[0]}").json()
    assert view["status"] == "accepted" and view["accepted"]["name"] == "Dana Buyer"


def test_accept_runs_the_real_handoff(db, pw, settings, ready, monkeypatch):
    from app.commercial.models import Handoff

    seen = _raw(monkeypatch)
    _send(db, settings, pw, ready)
    r = pw.client.post(f"/api/v1/public/p/{seen[0]}/accept", data={"name": "Dana Buyer", "title": "COO", "email": "dana@acme.example", "authorised": "true"})
    assert r.status_code == 200, r.text
    h = db.scalar(select(Handoff).where(Handoff.proposal_id == ready.id))
    assert h is not None


def test_request_changes(db, pw, settings, ready, monkeypatch):
    from app.notifications.models import Notification

    seen = _raw(monkeypatch)
    _send(db, settings, pw, ready)
    url = f"/api/v1/public/p/{seen[0]}/changes"
    assert pw.client.post(url, json={"message": " "}).status_code == 422
    r = pw.client.post(url, json={"message": "Can we start in January?", "name": "Dana"})
    assert r.status_code == 200
    db.refresh(ready)
    assert ready.status == "changes_requested"
    ev = db.scalar(select(ProposalEvent).where(ProposalEvent.kind == "changes_requested"))
    assert "January" in ev.detail
    assert db.scalar(select(Notification).where(Notification.user_id == pw.manager.id, Notification.kind == "proposal_changes_requested"))


def test_public_endpoints_are_rate_limited(db, pw, settings, ready, monkeypatch):
    seen = _raw(monkeypatch)
    _send(db, settings, pw, ready)
    codes = [pw.client.post(f"/api/v1/public/p/{seen[0]}/changes", json={"message": "x"}).status_code for _ in range(sending.SUBMITS_PER_MINUTE + 1)]
    assert codes[-1] == 429


def test_reminder_gives_a_fresh_link_and_retires_the_old(db, pw, settings, ready, monkeypatch):
    seen = _raw(monkeypatch)
    [link] = _send(db, settings, pw, ready)
    new = sending.remind(db, settings, pw.sales, ready, link.id)
    db.commit()
    assert link.revoked_at is not None and new.expires_at == link.expires_at
    assert pw.client.get(f"/api/v1/public/p/{seen[0]}").status_code == 410
    assert pw.client.get(f"/api/v1/public/p/{seen[1]}").status_code == 200


def test_daily_job_tells_the_owner_and_expires(db, pw, settings, ready):
    from app.notifications.models import Notification

    _send(db, settings, pw, ready)
    now = utcnow() + timedelta(days=4)
    assert sending.run_daily(db, settings, now) >= 1
    kinds = [n.kind for n in db.scalars(select(Notification).where(Notification.user_id == pw.sales.id))]
    assert "proposal_not_opened" in kinds
    sending.run_daily(db, settings, now)
    assert [n.kind for n in db.scalars(select(Notification).where(Notification.user_id == pw.sales.id))].count("proposal_not_opened") == 1
    sending.run_daily(db, settings, utcnow() + timedelta(days=26))
    assert "proposal_expiring" in [n.kind for n in db.scalars(select(Notification).where(Notification.user_id == pw.sales.id))]
    sending.run_daily(db, settings, utcnow() + timedelta(days=32))
    assert ready.status == "expired"
