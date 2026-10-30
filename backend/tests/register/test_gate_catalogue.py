"""If the role catalogue failed to load, every system would have zero required roles and pass the go-live gate. The
gate refuses go-live instead and says why."""
from app.notifications.models import Notification
from tests.register.conftest import new_system

MESSAGE = "The governance role catalogue has not loaded. Ask Futran to check the platform."


def test_go_live_is_refused_while_the_role_catalogue_is_empty(client, db, reg):
    reg.as_(reg.hr_lead)
    s = new_system(client, department_id=reg.hr.id, stage="in_development")
    r = client.post(f"/api/v1/register/{s['id']}/go-live/submit")
    assert r.status_code == 409 and r.json()["detail"] == MESSAGE
    reg.as_(reg.caico)
    assert client.patch(f"/api/v1/register/{s['id']}", json={"stage": "ready_for_go_live", "reason": "Ready"}).status_code == 200
    gate = client.get(f"/api/v1/register/{s['id']}").json()["gate"]
    assert gate["state"] == "blocked" and gate["label"] == MESSAGE
