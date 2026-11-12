"""Proposal APIs: who can do what, and the SM-09 → SM-11 → SM-10 round trip through HTTP."""
from app.proposals import service as ps


def test_only_sales_roles_build_and_auditors_see_nothing(db, pw):
    c = pw.as_(pw.auditor)
    assert c.get("/api/v1/sales/proposals").status_code in (403, 404)
    c = pw.as_(pw.sales)
    r = c.post("/api/v1/sales/proposals", json={"opportunity_id": pw.opp.id, "package": "starter"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert [ln["code"] for ln in r.json()["lines"]] == ["L-01"]
    c = pw.as_(pw.approver)  # approvers view but don't edit
    assert c.get(f"/api/v1/sales/proposals/{pid}").status_code == 200
    assert c.post(f"/api/v1/sales/proposals/{pid}/lines", json={"code": "A-05", "qty": 1}).status_code == 403
    c = pw.as_(pw.admin)
    assert c.get(f"/api/v1/sales/proposals/{pid}").status_code in (403, 404)


def test_build_request_approve_and_send_round_trip(db, pw):
    c = pw.as_(pw.sales)
    p = c.post("/api/v1/sales/proposals", json={"opportunity_id": pw.opp.id}).json()
    pid = p["id"]
    p = c.post(f"/api/v1/sales/proposals/{pid}/lines", json={"code": "A-06b", "qty": 1}).json()
    p = c.post(f"/api/v1/sales/proposals/{pid}/lines", json={"code": "M-03a", "qty": 1}).json()
    line = next(ln for ln in p["lines"] if ln["code"] == "A-06b")
    assert "Proposed price" in line["badges"]
    p = c.patch(f"/api/v1/sales/proposals/{pid}/lines/{line['id']}", json={"override_price": 2500}).json()
    line = next(ln for ln in p["lines"] if ln["code"] == "A-06b")
    assert "Edited" in line["badges"] and "Below Low" in line["badges"] and line["edited_by"] == "Raj Mehta"
    p = c.patch(f"/api/v1/sales/proposals/{pid}", json={"discount_recurring_pct": 10, "terms": {"payment_days": 30, "sla": "Next business day"}}).json()
    assert {r["rule"] for r in p["approvals_needed"]} == {"P-1", "P-2", "P-4"}
    blocked = c.post(f"/api/v1/sales/proposals/{pid}/send", json={"recipients": [{"name": "Dana", "email": "dana@acme.example"}]})
    assert blocked.status_code == 409
    out = c.post(f"/api/v1/sales/proposals/{pid}/approvals").json()
    assert sorted(out["requested"]) == ["P-1", "P-2", "P-4"] and out["proposal"]["status"] == "awaiting_approval"
    a = pw.as_(pw.approver)
    queue = a.get("/api/v1/sales/approvals?tab=mine").json()
    assert sorted(i["rule"] for i in queue["items"]) == ["P-1", "P-2", "P-4"]
    for item in queue["items"]:
        d = a.get(f"/api/v1/sales/approvals/{item['id']}").json()
        assert d["can_decide"] and d["margin_note"]
        assert a.post(f"/api/v1/sales/approvals/{item['id']}/decide", json={"decision": "approve", "note": ""}).status_code == 200
    c = pw.as_(pw.sales)
    doc = c.get(f"/api/v1/sales/proposals/{pid}/document").json()
    assert doc["send_blockers"] == [] and [s["number"] for s in doc["sections"]] == list(range(1, 9))
    pdf = c.get(f"/api/v1/sales/proposals/{pid}/export.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    docx = c.get(f"/api/v1/sales/proposals/{pid}/export.docx")
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    r = c.post(f"/api/v1/sales/proposals/{pid}/send", json={"recipients": [{"name": "Dana Buyer", "email": "dana@acme.example"}]})
    assert r.status_code == 200, r.text
    doc = c.get(f"/api/v1/sales/proposals/{pid}/document").json()
    assert doc["log"][0]["kind"] == "sent" and doc["links"][0]["email"] == "dana@acme.example"
    assert c.patch(f"/api/v1/sales/proposals/{pid}", json={"discount_recurring_pct": 0}).status_code == 409
    v2 = c.post(f"/api/v1/sales/proposals/{pid}/versions").json()
    assert v2["version"] == 2 and v2["status"] == "draft"
    d = c.get(f"/api/v1/sales/proposals/{v2['id']}/diff").json()
    assert d == {"from": 1, "to": 2, "lines": [], "terms": [], "totals": {}}


def test_self_approval_is_refused_over_http(db, pw):
    c = pw.as_(pw.manager)
    pid = c.post("/api/v1/sales/proposals", json={"opportunity_id": pw.opp.id}).json()["id"]
    c.post(f"/api/v1/sales/proposals/{pid}/lines", json={"code": "M-03a", "qty": 1})
    c.patch(f"/api/v1/sales/proposals/{pid}", json={"discount_recurring_pct": 5})
    c.post(f"/api/v1/sales/proposals/{pid}/approvals")
    assert c.get("/api/v1/sales/approvals?tab=mine").json()["items"] == []
    rid = c.get("/api/v1/sales/approvals?tab=pricing").json()["items"][0]["id"]
    r = c.post(f"/api/v1/sales/approvals/{rid}/decide", json={"decision": "approve"})
    assert r.status_code == 403 and "own proposal" in r.text


def test_proposal_templates_tab(db, pw):
    c = pw.as_(pw.admin)
    r = c.get("/api/v1/sales/proposal-templates").json()
    assert [t["key"] for t in r["items"]][:3] == ["cover", "situation", "services"] and r["can_edit"]
    bad = c.put("/api/v1/sales/proposal-templates/terms", json={"body": "Valid until [Expiry]."})
    assert bad.status_code == 422
    ok = c.put("/api/v1/sales/proposal-templates/terms", json={"body": "Valid until [Valid until]. Net 30."})
    assert ok.status_code == 200 and ok.json()["updated_by"] == "Ada Admin"
    c = pw.as_(pw.sales)
    assert c.get("/api/v1/sales/proposal-templates").json()["can_edit"] is False
    assert c.put("/api/v1/sales/proposal-templates/terms", json={"body": "x"}).status_code == 403
    p = ps.create_blank(db, pw.opp, pw.sales)
    assert next(s for s in p.sections if s["key"] == "terms")["body"] == "Valid until [Valid until]. Net 30."
