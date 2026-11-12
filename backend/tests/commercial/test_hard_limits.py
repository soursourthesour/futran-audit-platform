"""Hard limits (api_access, trust_center) are switched off for an ordered plan without them; clients without an order
keep today's behaviour."""
from app.commercial import handoff
from tests.commercial.conftest import STANDARD_LINES, proposal_for
from tests.factories import make_user


def test_api_clients_need_api_access_on_an_ordered_plan(cw, fake_catalog):
    p, a = proposal_for(cw, STANDARD_LINES())
    handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.prospect.status = "active"
    admin = make_user(cw.db, cw.prospect, roles=["client_admin"], name="Pat Admin", email="pat@acme.example")
    cw.db.commit()
    cw.as_(admin)
    r = cw.client.post("/api/v1/admin/api/clients", json={"name": "HR system", "scopes": ["inventory:read"]})
    assert r.status_code == 409 and "plan" in r.json()["detail"]
    # a client set up before Release 2 is unchanged
    cw.as_(cw.client_admin)
    assert cw.client.post("/api/v1/admin/api/clients", json={"name": "HR system", "scopes": ["inventory:read"]}).status_code == 200


def test_trust_center_needs_trust_center_on_an_ordered_plan(cw, fake_catalog):
    p, a = proposal_for(cw, STANDARD_LINES())
    handoff.create_from_acceptance(cw.db, p, a, cw.sales)
    cw.prospect.status = "active"
    caico = make_user(cw.db, cw.prospect, roles=["caico"], name="Kim Caico", email="kim@acme.example")
    cw.db.commit()
    body = {"slug": "acme", "title": "How Acme governs AI", "intro": "We use AI in hiring.", "contact_email": "ai@acme.example", "live": True}
    cw.as_(caico)
    r = cw.client.put("/api/v1/trust/page", json=body)
    assert r.status_code == 409 and "plan" in r.json()["detail"]
    cw.as_(cw.caico)
    assert cw.client.put("/api/v1/trust/page", json=body | {"slug": "harbor"}).status_code == 200
