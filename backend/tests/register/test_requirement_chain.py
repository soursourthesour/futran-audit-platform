"""Requirement statuses follow the law through a Reference data edit (the Regulation row is replaced and its version
is copied under the new row): a "Met" stays met and does not block go-live."""
from tests.register.test_roles import _system, cat  # noqa: F401


def _edit(db, cat, field="enforcer", value="City Commission on Human Rights"):
    from app.laws.service import edit_law
    from app.regmaster.seed import ensure_versions
    from tests.factories import make_org, make_user

    futran = make_org(db, type="futran", name="Futran Solutions X")
    admin = make_user(db, futran, roles=["admin"], name="Ann Admin", email="ann@futran.test")
    new = edit_law(db, admin, cat.a.id, {field: value})
    db.flush()
    ensure_versions(db)
    db.commit()
    return new


def test_status_survives_a_reference_data_edit(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a",))
    r = client.put(f"/api/v1/register/{s['id']}/requirements/{cat.req_a1.id}", json={"status": "met", "note": "Done"})
    assert r.status_code == 200, r.text
    _edit(db, cat)
    rows = client.get(f"/api/v1/register/{s['id']}/requirements").json()["rows"]
    a01 = next(x for x in rows if x["code"] == "A-01")
    assert a01["status"] == "met", a01
    assert a01["carried_from_previous_version"] is True


def test_status_can_be_changed_again_after_the_edit(client, db, reg, cat):
    s = _system(client, reg, cat, laws=("a",))
    client.put(f"/api/v1/register/{s['id']}/requirements/{cat.req_a1.id}", json={"status": "met", "note": "Done"})
    _edit(db, cat)
    rows = client.get(f"/api/v1/register/{s['id']}/requirements").json()["rows"]
    a01 = next(x for x in rows if x["code"] == "A-01")
    r = client.put(f"/api/v1/register/{s['id']}/requirements/{a01['id']}", json={"status": "partly_met", "note": "Notice still to send"})
    assert r.status_code == 200, r.text
    rows = client.get(f"/api/v1/register/{s['id']}/requirements").json()["rows"]
    assert next(x for x in rows if x["code"] == "A-01")["status"] == "partly_met"
