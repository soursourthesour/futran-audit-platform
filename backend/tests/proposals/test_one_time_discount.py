"""The one-time discount (P-3) is its own line: in the builder totals, the document, the client page and the hand-off."""
from sqlalchemy import select

from app.proposals import approvals, document, sending
from app.proposals import service as ps

TO = [{"name": "Dana Buyer", "email": "dana@acme.example"}]


def _draft(db, pw):
    p = ps.create_blank(db, pw.opp, pw.sales)
    ps.add_line(db, pw.sales, p, "L-01", 1)  # 8,500 one-time
    ps.add_line(db, pw.sales, p, "M-03a", 1)  # 16,800 recurring
    ps.update_terms(db, pw.sales, p, {"discount_recurring_pct": 5, "terms": {"discount_one_time_pct": 10}})
    return p


def test_totals_carry_the_one_time_discount(db, pw):
    p = _draft(db, pw)
    assert p.totals == {"one_time": 8500, "one_time_discount": 850, "one_time_net": 7650, "recurring_y1": 16800, "discount": 840,
                        "y1_total": 23610, "arr": 15960}


def test_document_and_client_page_show_both_discounts(db, pw, settings, monkeypatch):
    p = _draft(db, pw)
    md = document.markdown(db, p)
    assert "| One-time discount (10%) | −$850 |" in md and "| Discount on recurring (5%) | −$840 |" in md and "| **Total, year 1** | $23,610 |" in md
    for q in approvals.request(db, pw.sales, p):
        approvals.decide(db, pw.approver, q, "approve", "")
    seen = []
    real = sending.new_token
    monkeypatch.setattr(sending, "new_token", lambda: seen.append(real()) or seen[-1])
    sending.send(db, settings, pw.sales, p, recipients=TO)
    db.commit()
    body = pw.client.get(f"/api/v1/public/p/{seen[0]}").json()
    assert body["totals"]["one_time_discount"] == 850 and body["totals"]["y1_total"] == 23610 and body["discount_one_time_pct"] == 10


def test_handoff_year1_value_is_net_of_both_discounts(db, pw, settings, monkeypatch):
    from app.commercial.models import Handoff

    p = _draft(db, pw)
    for q in approvals.request(db, pw.sales, p):
        approvals.decide(db, pw.approver, q, "approve", "")
    seen = []
    real = sending.new_token
    monkeypatch.setattr(sending, "new_token", lambda: seen.append(real()) or seen[-1])
    sending.send(db, settings, pw.sales, p, recipients=TO)
    db.commit()
    r = pw.client.post(f"/api/v1/public/p/{seen[0]}/accept", data={"name": "Dana Buyer", "title": "COO", "email": "dana@acme.example", "authorised": "true"})
    assert r.status_code == 200, r.text
    db.expire_all()
    h = db.scalar(select(Handoff).where(Handoff.proposal_id == p.id))
    assert h.year1_value == 23610
