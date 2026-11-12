"""SM-15 over HTTP: Sales Officers and Managers price lines, save versions on an opportunity, see guardrails."""
import pytest

from app.sales.models import Opportunity
from tests.factories import login_as, make_org

API = "/api/v1/sales/estimates"


def as_(client, db, user):
    client.cookies.clear()
    return login_as(client, db, user)


@pytest.fixture
def opp(db, staff):
    org = make_org(db, type="client", name="Northbank Credit Union")
    o = Opportunity(organization_id=org.id, trigger="manual", service="Governance audit", owner_id=staff["sales"].id)
    db.add(o)
    db.commit()
    return o


GOVERNED = [{"code": "A-02a", "qty": 1, "edited_price": 13500}, {"code": "A-05", "qty": 3}, {"code": "A-06b", "qty": 1}, {"code": "A-08a", "qty": 3},
            {"code": "M-07a", "qty": 2}, {"code": "M-01a", "qty": 1}, {"code": "M-03a", "qty": 1}, {"code": "M-06a", "qty": 1}]


def test_only_sales_roles_use_the_estimator(client, db, seeded, staff):
    for who in ("sales", "manager"):
        assert as_(client, db, staff[who]).get("/api/v1/sales/estimator").status_code == 200
    for who in ("admin", "chief", "auditor", "client", "owner"):
        assert as_(client, db, staff[who]).get("/api/v1/sales/estimator").status_code in (403, 404), who
        assert client.post(f"{API}/preview", json={"lines": GOVERNED}).status_code in (403, 404)


def test_estimator_reference_data(client, db, seeded, staff, opp):
    body = as_(client, db, staff["sales"]).get("/api/v1/sales/estimator").json()
    assert body["catalog_version"] == 1
    assert [p["name"] for p in body["packages"]] == ["Starter (LL144)", "Governed", "Agent-ready", "Custom"]
    m09 = next(i for i in body["items"] if i["code"] == "M-09")
    assert m09["can_add"] is False and "roadmap" in m09["why_not"].lower()
    assert {"id": opp.id, "name": "Northbank Credit Union — Governance audit"} in [{"id": o["id"], "name": o["name"]} for o in body["opportunities"]]


def test_preview_prices_lines_and_shows_guardrails(client, db, seeded, staff):
    r = as_(client, db, staff["sales"]).post(f"{API}/preview", json={"lines": GOVERNED, "discount_recurring_pct": 0, "term": 1})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["totals"] == {"one_time": 39500, "recurring_y1": 31200, "discount": 0, "y1_total": 70700, "arr": 31200}
    assert [a["rule"] for a in b["approvals"]] == ["P-1", "P-8"]
    assert b["summary"].startswith("1 line edited, still inside the Low–High range: no extra approval.")


def test_roadmap_and_unknown_items_cannot_be_added(client, db, seeded, staff):
    as_(client, db, staff["sales"])
    r = client.post(f"{API}/preview", json={"lines": [{"code": "M-09", "qty": 1}]})
    assert r.status_code == 422 and "roadmap" in r.json()["errors"][0]["message"].lower()
    assert client.post(f"{API}/preview", json={"lines": [{"code": "Z-99", "qty": 1}]}).status_code == 422
    assert client.post(f"{API}/preview", json={"lines": [{"code": "A-02a", "qty": 0}]}).status_code == 422


def test_save_versions_and_master_never_changes(client, db, seeded, staff, opp):
    as_(client, db, staff["sales"])
    r = client.post(API, json={"name": "Northbank first pass", "opportunity_id": opp.id, "package": "governed", "lines": GOVERNED, "discount_recurring_pct": 5,
                               "term": 2, "data_region": "us"})
    assert r.status_code == 200, r.text
    e1 = r.json()
    assert e1["version"] == 1 and e1["saved_by"] == "Sam Seller" and e1["totals"]["discount"] == 1560
    a = next(ln for ln in e1["lines"] if ln["code"] == "A-02a")
    assert a["edited"] and a["edited_by"] == "Sam Seller" and a["list_price"] == 15000
    lines2 = [dict(ln, qty=2) if ln["code"] == "A-05" else ln for ln in GOVERNED]
    e2 = client.post(API, json={"thread_id": e1["thread_id"], "name": "Northbank first pass", "opportunity_id": opp.id, "lines": lines2}).json()
    assert e2["version"] == 2 and e2["thread_id"] == e1["thread_id"]
    assert [v["version"] for v in client.get(f"{API}/{e2['id']}").json()["versions"]] == [2, 1]
    from app.catalog import service

    assert service.get_item(db, "A-02a").list_price == 15000 and service.current_version(db) == 1
    listed = client.get(f"{API}?opportunity_id={opp.id}").json()["items"]
    assert [(x["id"], x["version"]) for x in listed] == [(e2["id"], 2)]


def test_list_price_changed_banner(client, db, seeded, staff, opp):
    e = as_(client, db, staff["sales"]).post(API, json={"name": "N", "opportunity_id": opp.id, "lines": GOVERNED}).json()
    as_(client, db, staff["owner"]).post("/api/v1/catalog/save", json={"changes": [{"code": "M-01a", "field": "list_price", "value": 12500},
                                                                                   {"code": "A-02a", "field": "list_price", "value": 15500}], "reason": "Review"})
    got = as_(client, db, staff["sales"]).get(f"{API}/{e['id']}").json()
    # A-02a was edited by the rep, so it keeps the rep's price; only M-01a, still at list, is offered for update
    assert got["price_changes"] == [{"code": "M-01a", "name": "Monitor, up to 10 systems", "old": 12000, "new": 12500}]


def test_retired_item_stays_on_an_old_estimate_but_cannot_be_added(client, db, seeded, staff, opp):
    e = as_(client, db, staff["sales"]).post(API, json={"name": "N", "opportunity_id": opp.id, "lines": [{"code": "A-06b", "qty": 1}]}).json()
    from app.catalog import service

    service.retire_item(db, staff["owner"], "A-06b", reason="Gone")
    db.commit()
    r = client.post(API, json={"thread_id": e["thread_id"], "name": "N", "opportunity_id": opp.id, "lines": [{"code": "A-06b", "qty": 2}]})
    assert r.status_code == 200, r.text
    r = client.post(API, json={"name": "New", "opportunity_id": opp.id, "lines": [{"code": "A-06b", "qty": 1}]})
    assert r.status_code == 422 and "retired" in r.json()["errors"][0]["message"]


def test_convert_waits_for_the_proposal_builder(client, db, seeded, staff, opp):
    e = as_(client, db, staff["sales"]).post(API, json={"name": "N", "opportunity_id": opp.id, "lines": GOVERNED}).json()
    from app.catalog import estimates

    if estimates.proposal_builder() is None:
        assert e["can_convert"] is False and e["convert_note"]
        assert client.post(f"{API}/{e['id']}/convert").status_code == 409


def test_convert_calls_the_proposal_builder(client, db, seeded, staff, opp, monkeypatch):
    from app.catalog import estimates

    calls = []

    class FakeProposal:
        id = "prop-1"

    monkeypatch.setattr(estimates, "proposal_builder", lambda: (lambda db, est, actor: calls.append((est.id, actor.id)) or FakeProposal()))
    e = as_(client, db, staff["sales"]).post(API, json={"name": "N", "opportunity_id": opp.id, "lines": GOVERNED}).json()
    r = client.post(f"{API}/{e['id']}/convert")
    assert r.status_code == 200 and r.json()["proposal_id"] == "prop-1" and calls == [(e["id"], staff["sales"].id)]
    assert client.get(f"{API}/{e['id']}").json()["converted_proposal_id"] == "prop-1"


def test_side_panel_usage_counts_saved_estimates(client, db, seeded, staff, opp):
    as_(client, db, staff["sales"]).post(API, json={"name": "N", "opportunity_id": opp.id, "lines": GOVERNED})
    usage = client.get("/api/v1/catalog/items/A-02a/history").json()["usage"]
    assert usage["estimates"] == 1
    assert client.get("/api/v1/catalog/items/L-01/history").json()["usage"]["estimates"] == 0


def test_convert_needs_an_opportunity(client, db, seeded, staff):
    e = as_(client, db, staff["sales"]).post(API, json={"name": "No opportunity", "lines": GOVERNED}).json()
    assert e["can_convert"] is False and "opportunity" in e["convert_note"].lower()
    r = client.post(f"{API}/{e['id']}/convert")
    assert r.status_code in (409, 422) and "opportunity" in r.json()["detail"].lower()


def test_convert_with_the_real_proposal_builder(client, db, seeded, staff, opp):
    from app.catalog import estimates

    if estimates.proposal_builder() is None:
        pytest.skip("the proposal builder (R4) is not installed")
    e = as_(client, db, staff["sales"]).post(API, json={"name": "N", "opportunity_id": opp.id, "package": "governed", "lines": GOVERNED,
                                                        "discount_recurring_pct": 5}).json()
    assert e["can_convert"] is True
    r = client.post(f"{API}/{e['id']}/convert")
    assert r.status_code == 200, r.text
    from app.proposals.models import Proposal, ProposalLine

    p = db.get(Proposal, r.json()["proposal_id"])
    lines = {ln.catalog_code: ln for ln in db.query(ProposalLine).filter_by(proposal_id=p.id)}
    assert set(lines) == {ln["code"] for ln in GOVERNED} and lines["A-02a"].override_price == 13500
    from app.catalog import service

    assert service.get_item(db, "A-02a").list_price == 15000  # the master never changes
