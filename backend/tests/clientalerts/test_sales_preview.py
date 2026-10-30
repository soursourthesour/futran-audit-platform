"""Security review: the Sales Team previews only the add-on alerts it approves, and never the client's recipient list."""
from app.clientalerts.service import _queue, ensure_rules, queue_for_change
from tests.clientalerts.test_client_alerts import law  # noqa: F401  (fixture)
from tests.factories import login_as


def _addon_send(db, settings, lit):
    rule = next(r for r in ensure_rules(db) if r.trigger == "tracing_addon")
    s = _queue(db, settings, rule, lit["abc"].id, "tracing:abc", "Tracing recommended for Résumé screening", [lit["screening"].id], [], None, owner_id=lit["sales"].id)
    db.commit()
    return s


def test_sales_cannot_preview_a_chief_auditor_alert(client, db, lit, law, settings):
    s = queue_for_change(db, settings, law[2])[0]
    db.commit()
    login_as(client, db, lit["sales"])
    assert client.get(f"/api/v1/alerts/sends/{s.id}/preview").status_code == 403
    assert [i["id"] for g in client.get("/api/v1/alerts/queue").json()["groups"] for i in g["items"]] == []


def test_sales_preview_of_its_addon_alert_has_no_recipient_list(client, db, lit, settings):
    s = _addon_send(db, settings, lit)
    login_as(client, db, lit["sales"])
    q = client.get("/api/v1/alerts/queue").json()
    assert [i["id"] for g in q["groups"] for i in g["items"]] == [s.id]
    pv = client.get(f"/api/v1/alerts/sends/{s.id}/preview")
    assert pv.status_code == 200, pv.text
    assert "maria@abc.test" not in pv.text and pv.json()["to"] == []
    login_as(client, db, lit["chief"])  # the Chief Auditor still sees who it goes to
    assert client.get(f"/api/v1/alerts/sends/{s.id}/preview").json()["to"] == ["maria@abc.test"]
