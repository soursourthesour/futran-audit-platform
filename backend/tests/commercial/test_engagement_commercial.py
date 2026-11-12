"""G-02: the engagement's commercial tab (order lines, fee, milestones, deliverables, change orders). Fees and prices are
never sent to Auditors. A change order is priced from the price list, checked against the sales approval rules,
approved by the client's CAICO in the platform, and only then does the scope change. Adding a system after initiation
on an engagement that came from an order goes through a change order."""
from sqlalchemy import select

from app.commercial.models import ChangeOrder, EngagementCommercial, OrderLine
from app.notifications.models import Notification
from app.systems.models import AISystem, SystemAdditionRequest
from tests.factories import make_user


def _commercial(cw, fee=43500):
    from app.commercial.handoff import default_milestones
    from app.commercial.models import Order

    o = Order(organization_id=cw.org.id, ref="ORD-0188", status="active")
    cw.db.add(o)
    cw.db.flush()
    cw.db.add(OrderLine(organization_id=cw.org.id, order_id=o.id, catalog_code="A-02b", description="Audit, 11–50 systems", qty=1, unit_price=35000, line_value=35000,
                        engagement_id=cw.engagement.id, deliverables_text="Final report (sign-off 7)"))
    cw.db.add(EngagementCommercial(organization_id=cw.org.id, engagement_id=cw.engagement.id, order_id=o.id, fee_total=fee, milestones=default_milestones(fee)))
    cw.db.commit()
    return o


def _url(cw, tail=""):
    return f"/api/v1/e/{cw.engagement.id}/commercial{tail}"


def test_fees_go_to_the_chief_auditor_manager_sales_and_admin_never_auditors(cw, fake_catalog):
    _commercial(cw)
    for u in (cw.chief, cw.em, cw.sales, cw.fadmin):
        cw.as_(u)
        r = cw.client.get(_url(cw))
        assert r.status_code == 200, (u.name, r.text)
        d = r.json()
        assert d["fee_total"] == 43500 and d["order_lines"][0]["value"] == 35000 and d["milestones"][0]["amount"] == 21750
        assert d["deliverables"] == [{"code": "A-02b", "text": "Final report (sign-off 7)"}]
    cw.as_(cw.auditor)
    assert cw.client.get(_url(cw)).status_code == 403
    r = cw.client.get(f"/api/v1/e/{cw.engagement.id}/change-orders")
    assert r.status_code == 200 and "unit_price" not in str(r.json()) and "value" not in str(r.json())


def test_manager_edits_fee_and_milestones_that_add_up(cw, fake_catalog):
    _commercial(cw)
    cw.as_(cw.em)
    bad = cw.client.put(_url(cw), json={"fee_total": 40000, "milestones": [{"label": "All on start", "trigger": "sign_off_1", "pct": 60}]})
    assert bad.status_code == 422
    r = cw.client.put(_url(cw), json={"fee_total": 40000, "milestones": [{"label": "30% on start", "trigger": "sign_off_1", "pct": 30},
                                                                          {"label": "70% on report", "trigger": "sign_off_7", "pct": 70}]})
    assert r.status_code == 200, r.text
    assert [m["amount"] for m in r.json()["milestones"]] == [12000, 28000]
    cw.as_(cw.sales)
    assert cw.client.put(_url(cw), json={"fee_total": 1}).status_code in (403, 404)


def test_change_order_priced_from_the_catalog_and_approved_by_the_client(cw, fake_catalog):
    _commercial(cw)
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/e/{cw.engagement.id}/change-orders", json={"code": "A-04", "qty": 2, "reason": "Two more states found in scoping"})
    assert r.status_code == 200, r.text
    co = r.json()
    assert co["ref"] == "CO-001" and co["status"] == "awaiting_client" and co["lines"][0]["unit_price"] == 1200 and co["value"] == 2400
    # the client's CAICO approves in the platform
    cw.as_(cw.caico)
    lst = cw.client.get("/api/v1/change-orders").json()
    assert [c["ref"] for c in lst] == ["CO-001"] and lst[0]["value"] == 2400
    cw.as_(cw.client_admin)
    assert cw.client.post(f"/api/v1/change-orders/{co['id']}/decide", json={"approve": True}).status_code == 403
    cw.as_(cw.caico)
    r = cw.client.post(f"/api/v1/change-orders/{co['id']}/decide", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    line = cw.db.scalar(select(OrderLine).where(OrderLine.change_order_id == co["id"]))
    assert line.catalog_code == "A-04" and line.qty == 2 and line.unit_price == 1200 and line.engagement_id == cw.engagement.id
    assert cw.db.scalar(select(EngagementCommercial)).fee_total == 43500 + 2400
    assert cw.db.scalar(select(Notification).where(Notification.user_id == cw.em.id, Notification.kind == "change_order_decided")) is not None


def test_price_below_list_needs_a_sales_approver_who_is_not_the_raiser(cw, fake_catalog):
    _commercial(cw)
    approver = make_user(cw.db, cw.futran, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    cw.db.commit()
    cw.as_(cw.em)
    co = cw.client.post(f"/api/v1/e/{cw.engagement.id}/change-orders", json={"code": "A-03", "qty": 1, "unit_price": 500, "reason": "Goodwill"}).json()
    assert co["status"] == "awaiting_futran_approval"
    assert cw.client.post(f"/api/v1/change-orders/{co['id']}/price-decision", json={"approve": True}).status_code == 403
    cw.as_(approver)
    r = cw.client.post(f"/api/v1/change-orders/{co['id']}/price-decision", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_client"


def test_auditor_raises_without_seeing_prices_and_the_manager_approves_first(cw, fake_catalog):
    _commercial(cw)
    cw.as_(cw.auditor)
    r = cw.client.post(f"/api/v1/e/{cw.engagement.id}/change-orders", json={"code": "A-07", "qty": 3, "reason": "Eight governance documents, not five"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft" and "unit_price" not in str(r.json())
    co_id = r.json()["id"]
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/change-orders/{co_id}/manager-approve")
    assert r.status_code == 200 and r.json()["status"] == "awaiting_client"


def test_roadmap_items_cannot_be_sold_on_a_change_order(cw, fake_catalog):
    _commercial(cw)
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/e/{cw.engagement.id}/change-orders", json={"code": "M-14a", "qty": 1, "reason": "API"})
    assert r.status_code == 422


def test_adding_a_system_after_initiation_goes_through_a_change_order(cw, fake_catalog):
    _commercial(cw)
    req = SystemAdditionRequest(organization_id=cw.org.id, engagement_id=cw.engagement.id, requested_by=cw.auditor.id,
                                payload={"name": "Vendor chatbot", "built_by": "vendor", "use_case_ids": []}, reason="Found in the discovery sweep", status="pending")
    cw.db.add(req)
    cw.db.commit()
    before = len(list(cw.db.scalars(select(AISystem).where(AISystem.engagement_id == cw.engagement.id))))
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "co_pending"
    co = cw.db.scalar(select(ChangeOrder).where(ChangeOrder.engagement_id == cw.engagement.id))
    assert co.scope_change_ref == f"system_addition:{req.id}" and co.lines[0]["code"] == "A-03" and co.status == "awaiting_client" and co.em_approved_by == cw.em.id
    assert len(list(cw.db.scalars(select(AISystem).where(AISystem.engagement_id == cw.engagement.id)))) == before  # nothing in scope yet
    cw.as_(cw.caico)
    assert cw.client.post(f"/api/v1/change-orders/{co.id}/decide", json={"approve": True}).status_code == 200
    cw.db.expire_all()
    systems = list(cw.db.scalars(select(AISystem).where(AISystem.engagement_id == cw.engagement.id)))
    assert len(systems) == before + 1 and systems[-1].name == "Vendor chatbot"
    assert cw.db.get(SystemAdditionRequest, req.id).status == "approved"


def test_client_rejection_leaves_scope_alone(cw, fake_catalog):
    _commercial(cw)
    req = SystemAdditionRequest(organization_id=cw.org.id, engagement_id=cw.engagement.id, requested_by=cw.auditor.id,
                                payload={"name": "Vendor chatbot", "built_by": "vendor", "use_case_ids": []}, reason="Found", status="pending")
    cw.db.add(req)
    cw.db.commit()
    cw.as_(cw.em)
    cw.client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True})
    co = cw.db.scalar(select(ChangeOrder))
    cw.as_(cw.caico)
    assert cw.client.post(f"/api/v1/change-orders/{co.id}/decide", json={"approve": False}).status_code == 422  # a reason is needed
    assert cw.client.post(f"/api/v1/change-orders/{co.id}/decide", json={"approve": False, "note": "Out of budget this year"}).status_code == 200
    cw.db.expire_all()
    assert cw.db.get(SystemAdditionRequest, req.id).status == "rejected"
    assert cw.db.scalar(select(AISystem).where(AISystem.name == "Vendor chatbot")) is None


def test_engagements_without_an_order_keep_todays_addition_rule(cw, fake_catalog):
    req = SystemAdditionRequest(organization_id=cw.org.id, engagement_id=cw.engagement.id, requested_by=cw.auditor.id,
                                payload={"name": "Vendor chatbot", "built_by": "vendor", "use_case_ids": []}, reason="Found", status="pending")
    cw.db.add(req)
    cw.db.commit()
    cw.as_(cw.em)
    r = cw.client.post(f"/api/v1/system-requests/{req.id}/decide", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert cw.db.scalar(select(ChangeOrder)) is None
