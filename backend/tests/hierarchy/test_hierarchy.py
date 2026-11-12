"""G-04 client hierarchy (spec B4): the tree, LL144 scope per end-client, and roll-up only with each subsidiary CAICO's
consent. Tenancy is unchanged: no link in the tree lets anyone read another tenant's data."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.hierarchy import service as h
from app.hierarchy.models import RollupConsent
from app.register.models import RegisterSystem
from app.tenancy.models import Organization
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def hw(db, client):
    f = make_org(db, type="futran")
    w = SimpleNamespace(db=db, client=client)
    w.fadmin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    w.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    w.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    w.parent = make_org(db, name="Acme Staffing LLC", status="active")
    w.sub = make_org(db, name="Acme Healthcare Staffing Inc.", status="active")
    w.other = make_org(db, name="Unrelated Corp", status="active")
    w.parent_caico = make_user(db, w.parent, roles=["caico"], name="Pat Parent", email="pat@acme.example")
    w.sub_caico = make_user(db, w.sub, roles=["caico"], name="Sid Sub", email="sid@acmehc.example")
    w.other_caico = make_user(db, w.other, roles=["caico"], name="Olive Other", email="olive@other.example")
    for i, (org, stage) in enumerate([(w.sub, "live"), (w.sub, "live"), (w.sub, "proposed"), (w.parent, "live"), (w.parent, "live")]):
        db.add(RegisterSystem(organization_id=org.id, reference=f"AIS-{i:03d}", name=f"Screening tool {i}", type="other", sourcing="vendor", stage=stage, risk_tier=3 if i == 0 else 1))
    db.commit()
    w.as_ = lambda u: login_as(client, db, u)
    return w


def _link(w):
    w.as_(w.fadmin)
    r = w.client.post(f"/api/v1/staff/clients/{w.parent.id}/entities/link", json={"child_id": w.sub.id, "relationship": "subsidiary"})
    assert r.status_code == 200, r.text
    return r.json()


def test_existing_organizations_have_no_parent(hw):
    for org in hw.db.scalars(select(Organization)):
        assert org.parent_id is None and org.relationship is None


def test_futran_admin_builds_the_tree(hw):
    _link(hw)
    r = hw.client.post(f"/api/v1/staff/clients/{hw.parent.id}/entities", json={"name": "Riverside Hospital", "relationship": "end_client"})
    assert r.status_code == 200, r.text
    tree = hw.client.get(f"/api/v1/staff/clients/{hw.sub.id}/entities").json()
    assert tree["root"]["id"] == hw.parent.id  # any entity opens the whole group
    names = {n["name"]: n for n in tree["nodes"]}
    assert names["Acme Healthcare Staffing Inc."]["relationship"] == "subsidiary"
    assert names["Riverside Hospital"]["relationship"] == "end_client" and names["Riverside Hospital"]["parent_id"] == hw.parent.id
    end = hw.db.get(Organization, names["Riverside Hospital"]["id"])
    assert end.type == "client" and end.organization_id == end.id  # its own tenant
    assert hw.db.scalar(select(AuditLog).where(AuditLog.action == "hierarchy.add_entity")) is not None


def test_cycles_and_self_links_are_refused(hw):
    _link(hw)
    r = hw.client.post(f"/api/v1/staff/clients/{hw.sub.id}/entities/link", json={"child_id": hw.parent.id, "relationship": "subsidiary"})
    assert r.status_code == 409
    r = hw.client.post(f"/api/v1/staff/clients/{hw.parent.id}/entities/link", json={"child_id": hw.parent.id, "relationship": "subsidiary"})
    assert r.status_code == 409


def test_only_the_futran_admin_changes_the_tree(hw):
    hw.as_(hw.chief)
    assert hw.client.get(f"/api/v1/staff/clients/{hw.parent.id}/entities").status_code == 200
    assert hw.client.post(f"/api/v1/staff/clients/{hw.parent.id}/entities", json={"name": "X", "relationship": "end_client"}).status_code == 403
    hw.as_(hw.auditor)
    assert hw.client.get(f"/api/v1/staff/clients/{hw.parent.id}/entities").status_code in (403, 404)
    hw.as_(hw.parent_caico)
    assert hw.client.get(f"/api/v1/staff/clients/{hw.parent.id}/entities").status_code == 404


def test_rollup_needs_the_subsidiary_caicos_consent(hw):
    _link(hw)
    hw.as_(hw.parent_caico)
    g = hw.client.get("/api/v1/group").json()
    sub = next(c for c in g["children"] if c["id"] == hw.sub.id)
    assert sub["consent"] is False and sub["rollup"] is None
    # the parent cannot consent for the subsidiary
    assert hw.client.post("/api/v1/group/consent").status_code in (403, 409)
    # the subsidiary CAICO consents
    hw.as_(hw.sub_caico)
    g = hw.client.get("/api/v1/group").json()
    assert g["parent"]["name"] == "Acme Staffing LLC" and g["can_consent"] and g["consent"] is None
    r = hw.client.post("/api/v1/group/consent")
    assert r.status_code == 200 and r.json()["consent"]["given_by"] == "Sid Sub"
    c = hw.db.scalar(select(RollupConsent).where(RollupConsent.organization_id == hw.sub.id))
    assert c.given_by == hw.sub_caico.id and c.revoked_at is None
    hw.as_(hw.parent_caico)
    sub = next(c for c in hw.client.get("/api/v1/group").json()["children"] if c["id"] == hw.sub.id)
    assert sub["consent"] is True
    assert sub["rollup"]["systems_total"] == 3 and sub["rollup"]["by_stage"]["live"] == 2 and sub["rollup"]["high_risk"] == 1
    assert "systems" not in sub["rollup"]  # counts and statuses only: no names
    assert hw.db.scalar(select(AuditLog).where(AuditLog.action == "hierarchy.rollup_view", AuditLog.organization_id == hw.sub.id)) is not None
    # revocable: the roll-up goes away at once
    hw.as_(hw.sub_caico)
    assert hw.client.post("/api/v1/group/consent/revoke").status_code == 200
    hw.as_(hw.parent_caico)
    sub = next(c for c in hw.client.get("/api/v1/group").json()["children"] if c["id"] == hw.sub.id)
    assert sub["consent"] is False and sub["rollup"] is None
    actions = set(hw.db.scalars(select(AuditLog.action).where(AuditLog.organization_id == hw.sub.id)))
    assert {"hierarchy.consent_given", "hierarchy.consent_revoked"} <= actions


def test_end_clients_cannot_be_rolled_up(hw):
    hw.as_(hw.fadmin)
    hw.client.post(f"/api/v1/staff/clients/{hw.parent.id}/entities/link", json={"child_id": hw.sub.id, "relationship": "end_client"})
    hw.as_(hw.sub_caico)
    assert hw.client.get("/api/v1/group").json()["can_consent"] is False
    assert hw.client.post("/api/v1/group/consent").status_code == 409


def test_the_tree_opens_no_tenant_data(hw):
    """A parent CAICO gets nothing of the subsidiary through any ordinary endpoint, consent or not."""
    _link(hw)
    hw.as_(hw.sub_caico)
    hw.client.post("/api/v1/group/consent")
    hw.as_(hw.parent_caico)
    systems = hw.client.get("/api/v1/register").json()
    rows = systems if isinstance(systems, list) else systems.get("systems", systems.get("rows", []))
    assert all("Screening tool 0" != s.get("name") for s in rows)
    sub_sys = hw.db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == hw.sub.id))
    assert hw.client.get(f"/api/v1/register/{sub_sys.id}").status_code == 404
    # an unrelated client sees no group at all
    hw.as_(hw.other_caico)
    g = hw.client.get("/api/v1/group").json()
    assert g["parent"] is None and g["children"] == []


def test_ll144_scope_per_end_client_and_pricing_count(hw):
    hw.as_(hw.fadmin)
    ids = []
    for name in ("Riverside Hospital", "Brookline Bank", "Hudson Logistics"):
        ids.append(hw.client.post(f"/api/v1/staff/clients/{hw.parent.id}/entities", json={"name": name, "relationship": "end_client"}).json()["id"])
    aedts = [s.id for s in hw.db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == hw.parent.id))]
    for eid, in_scope, note in zip(ids, (True, True, False), ("NYC roles", "NYC roles", "NJ roles only")):
        r = hw.client.put(f"/api/v1/staff/entities/{eid}/ll144", json={"ll144_in_scope": in_scope, "aedt_system_ids": aedts if in_scope else [], "roles_note": note,
                                                                      "own_public_summary": in_scope})
        assert r.status_code == 200, r.text
    assert h.ll144_end_client_count(hw.db, hw.parent.id) == 2
    tree = hw.client.get(f"/api/v1/staff/clients/{hw.parent.id}/entities").json()
    assert tree["ll144"] == {"end_clients": 3, "in_scope": 2, "aedts": 2}
    node = next(n for n in tree["nodes"] if n["name"] == "Riverside Hospital")
    assert node["ll144"]["in_scope"] and len(node["ll144"]["aedts"]) == 2 and node["ll144"]["own_public_summary"]
    # an AEDT must be one of the parent's own systems
    sub_sys = hw.db.scalar(select(RegisterSystem.id).where(RegisterSystem.organization_id == hw.sub.id))
    r = hw.client.put(f"/api/v1/staff/entities/{ids[0]}/ll144", json={"ll144_in_scope": True, "aedt_system_ids": [sub_sys]})
    assert r.status_code == 422


def test_import_end_clients_from_csv_previews_then_creates(hw):
    hw.as_(hw.fadmin)
    csv = b"name,relationship,ll144_in_scope,roles_note\nRiverside Hospital,end_client,yes,NYC roles\n=HYPERLINK(\"x\"),end_client,no,\nHudson Logistics,,no,NJ roles only\nBad Co,partner,no,\n"
    url = f"/api/v1/staff/clients/{hw.parent.id}/entities/import"
    r = hw.client.post(url, files={"file": ("ends.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    v = r.json()
    assert [x["name"] for x in v["rows"]] == ["Riverside Hospital", 'HYPERLINK("x")', "Hudson Logistics"] and v["errors"][0]["row"] == 5
    assert h.children(hw.db, hw.parent.id) == []  # a preview changes nothing
    r = hw.client.post(url + "?apply=true", files={"file": ("ends.csv", csv, "text/csv")})
    assert r.json()["created"] == 3
    assert h.ll144_end_client_count(hw.db, hw.parent.id) == 1
    r = hw.client.post(url + "?apply=true", files={"file": ("ends.csv", csv, "text/csv")})
    assert r.json()["created"] == 0  # names already in the group are skipped
