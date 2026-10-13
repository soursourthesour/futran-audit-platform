from pathlib import Path

import pytest

from app.laws.models import MatrixVersion, Regulation
from app.reference.jurisdictions import seed_iso
from tests.factories import login_as, make_org, make_user

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"


@pytest.fixture
def people(db):
    seed_iso(db)
    f = make_org(db, type="futran")
    admin = make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")
    aud = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@f.test")
    db.commit()
    return admin, aud


def _import(client):
    with open(WORKBOOK, "rb") as fh:
        r = client.post("/api/v1/admin/laws/import", files={"file": ("law_matrix.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_preview_then_publish_via_api(client, db, people):
    admin, _ = people
    login_as(client, db, admin)
    pv = _import(client)
    assert pv["status_date"] == "2026-10-05"
    assert pv["counts"]["regulations"] > 200
    assert any(r["verify_flag"] for r in pv["rows"])
    co = next(r for r in pv["rows"] if r["jurisdiction_code"] == "US-CO" and r["kind"] == "regulation")
    r = client.post(f"/api/v1/admin/laws/import/{pv['preview_id']}/publish", json={"edits": {co["row_key"]: "Colorado SB 26-189"}})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["created"] == pv["counts"]["regulations"]
    db.expire_all()
    assert db.query(Regulation).filter_by(short_name="Colorado SB 26-189").count() == 1
    # a preview can only be published once
    assert client.post(f"/api/v1/admin/laws/import/{pv['preview_id']}/publish", json={"edits": {}}).status_code == 409


def test_import_rejects_non_workbook(client, db, people):
    admin, _ = people
    login_as(client, db, admin)
    r = client.post("/api/v1/admin/laws/import", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_non_admin_cannot_import_403(client, db, people):
    _, aud = people
    login_as(client, db, aud)
    with open(WORKBOOK, "rb") as fh:
        r = client.post("/api/v1/admin/laws/import", files={"file": ("x.xlsx", fh, "application/octet-stream")})
    assert r.status_code == 403


def test_laws_filter_by_geo_and_feature(client, db, people):
    admin, aud = people
    login_as(client, db, admin)
    pv = _import(client)
    client.post(f"/api/v1/admin/laws/import/{pv['preview_id']}/publish", json={"edits": {}})
    login_as(client, db, aud)
    groups = client.get("/api/v1/laws?codes=US-IL,US&feature=employment_hiring").json()
    codes = [g["jurisdiction"]["code"] for g in groups]
    assert codes == ["US-IL", "US"]
    il = groups[0]["laws"]
    assert any("Video Interview" in law["short_name"] for law in il)
    assert all(law["feature"] == "employment_hiring" for g in groups for law in g["laws"])
    assert all(law["summary"] for law in il)
    # developer-only laws are listed but flagged, and excluded on request
    ca = client.get("/api/v1/laws?codes=US-CA&feature=frontier_safety").json()[0]["laws"]
    assert all(law["applies_to"] == "developer" for law in ca)
    assert client.get("/api/v1/laws?codes=US-CA&feature=frontier_safety&exclude_developer=1").json() == []
    # free-text search
    hits = client.get("/api/v1/laws?codes=all&q=video interview").json()
    assert any("Video Interview" in law["short_name"] for g in hits for law in g["laws"])


def test_manual_edit_creates_version(client, db, people):
    admin, _ = people
    login_as(client, db, admin)
    pv = _import(client)
    client.post(f"/api/v1/admin/laws/import/{pv['preview_id']}/publish", json={"edits": {}})
    groups = client.get("/api/v1/laws?codes=US-IL").json()
    law = groups[0]["laws"][0]
    r = client.patch(f"/api/v1/laws/{law['id']}", json={"obligations_text": "Updated by Futran counsel.", "verify_flag": False})
    assert r.status_code == 200
    new = r.json()
    assert new["id"] != law["id"] and new["obligations_text"] == "Updated by Futran counsel."
    db.expire_all()
    assert db.get(Regulation, law["id"]).superseded_by_id == new["id"]
    assert db.query(MatrixVersion).filter_by(origin="manual").count() == 1
    r2 = client.post("/api/v1/laws", json={"jurisdiction_code": "US-NYC", "short_name": "NYC Int. 999 (hypothetical)", "feature": "employment_hiring", "type": "pending"})
    assert r2.status_code == 200 and r2.json()["origin"] == "manual"


def test_jurisdiction_admin_add_city_and_list(client, db, people):
    admin, aud = people
    login_as(client, db, admin)
    r = client.post("/api/v1/jurisdictions", json={"parent_code": "US-IL", "name": "Chicago", "level": "city", "aliases": ["Chicago, IL"]})
    assert r.status_code == 200 and r.json()["code"] == "US-IL-CHICAGO"
    login_as(client, db, aud)
    assert client.post("/api/v1/jurisdictions", json={"parent_code": "US-IL", "name": "Springfield", "level": "city"}).status_code == 403
    countries = client.get("/api/v1/jurisdictions?level=country").json()
    assert any(c["code"] == "DE" for c in countries)
    states = client.get("/api/v1/jurisdictions?parent=US").json()
    assert any(s["code"] == "US-NY" for s in states)
    resolved = client.get("/api/v1/jurisdictions/resolve?country=US&subdivision=US-NY&city=Brooklyn").json()
    assert [j["code"] for j in resolved] == ["US-NYC", "US-NY", "US"]


def test_law_summary_moves_parenthetical_to_end():
    from app.laws.models import Regulation
    from app.laws.service import law_summary

    r = Regulation(short_name="AI Video Interview Act", full_text="AI Video Interview Act (2020): notice, explanation and consent.")
    assert law_summary(r) == "Notice, explanation and consent. (2020)"
    r2 = Regulation(short_name="SB 947", full_text="SB 947: employers may not rely solely on an ADS.")
    assert law_summary(r2) == "Employers may not rely solely on an ADS."
    r3 = Regulation(short_name="X", full_text="X", obligations_text="Explicit obligations.")
    assert law_summary(r3) == "Explicit obligations."
