"""AI rule 4: AI features are off for an engagement until the Chief Auditor turns them on, recording the client's
consent; while off, AI endpoints return 403 and the screens hide every AI control."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from tests.ai.conftest import CONSENT, enable_ai
from tests.factories import login_as


def test_off_by_default_and_only_the_chief_auditor_turns_it_on_with_the_consent_note(client, db, ai_sys):
    w = ai_sys
    login_as(client, db, w.people["aud"])
    st = client.get(f"/api/v1/engagements/{w.e.id}/ai").json()
    assert st["enabled"] is False and st["can_manage"] is False
    assert client.post(f"/api/v1/systems/{w.s.id}/copilot/prefill", json={"sub_section": "6.1"}).status_code == 403
    assert client.put(f"/api/v1/engagements/{w.e.id}/ai", json={"enabled": True, "consent_note": CONSENT}).status_code == 403

    login_as(client, db, w.people["chief"])
    r = client.put(f"/api/v1/engagements/{w.e.id}/ai", json={"enabled": True, "consent_note": "  "})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "consent_note"
    r = client.put(f"/api/v1/engagements/{w.e.id}/ai", json={"enabled": True, "consent_note": CONSENT})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["consent_note"] == CONSENT and r.json()["enabled_by"] == "Cara Chief"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "ai.features_enabled")) is not None

    login_as(client, db, w.people["aud"])
    st = client.get(f"/api/v1/engagements/{w.e.id}/ai").json()
    assert st["enabled"] is True and st["can_use_copilot"] is True and st["can_view_log"] is False
    login_as(client, db, w.maria)
    assert client.get(f"/api/v1/engagements/{w.e.id}/ai").json() == {"enabled": True}  # clients never see Futran's copilot


def test_turning_it_off_closes_the_ai_endpoints_again(client, db, ai_sys):
    w = ai_sys
    enable_ai(client, db, w)
    assert client.put(f"/api/v1/engagements/{w.e.id}/ai", json={"enabled": False}).status_code == 200
    login_as(client, db, w.people["aud"])
    r = client.post(f"/api/v1/systems/{w.s.id}/copilot/ask", json={"question": "Who validates the model?"})
    assert r.status_code == 403 and "off for this engagement" in r.json()["detail"]
