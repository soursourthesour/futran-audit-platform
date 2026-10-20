"""The Clients page: one row per client the Futran user can see, with its current engagement."""
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401


def test_clients_list_shows_visible_clients_with_engagement(client, db, live, people):
    cid, e, maria = live
    login_as(client, db, people["chief"])
    rows = client.get("/api/v1/clients").json()["clients"]
    row = next(r for r in rows if r["id"] == cid)
    assert row["name"] == "ABC Corp" and row["industry"] == "Staffing and recruitment" and "New York" in row["headquarters"]
    assert row["engagement"]["audit_ref"] == e.audit_ref and row["engagement"]["stage_label"].startswith("2")
    login_as(client, db, people["aud2"])  # not on ABC's team
    assert all(r["id"] != cid for r in client.get("/api/v1/clients").json()["clients"])
    login_as(client, db, maria)
    assert client.get("/api/v1/clients").status_code == 404
