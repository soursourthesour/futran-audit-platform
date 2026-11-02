"""Policy builder (spec §21 F7, screen 27): template → answers → draft → edits → CAICO approval → publish → staff
acknowledgment (reusing the attestation link pattern) → the commitment closes with the policy as evidence."""
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.governance.models import Commitment
from app.mail.models import MailRecipient, MailSend
from tests.factories import login_as

API = "/api/v1"


def _start(client, w, **kw):
    r = client.post(f"{API}/policies", json={"template_code": "acceptable_use", "commitment_id": w["commitment"].id} | kw)
    assert r.status_code == 200, r.text
    return r.json()


ANSWERS = {"approved_tools": ["Microsoft Copilot (company account)", "ATS screening"], "personal_accounts": "not_allowed",
           "prohibited_data": ["client_data", "personal_data", "source_code"], "policy_owner": "Maria Lopez, Chief AI Compliance Officer"}


def test_library_lists_ten_templates_and_the_open_commitment(client, db, world):
    login_as(client, db, world["caico"])
    r = client.get(f"{API}/policies")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["templates"]) == 10
    assert body["templates"][0]["version"]
    [c] = body["commitments"]
    assert c["id"] == world["commitment"].id and c["suggested_template"] == "acceptable_use"
    assert body["can"]["edit"] and body["can"]["approve"]


def test_start_from_template_fills_company_and_renders_a_draft(client, db, world):
    login_as(client, db, world["admin"])
    p = _start(client, world)
    assert p["status"] == "draft" and p["template"]["version"] == "1.0"
    assert p["answers"]["company_name"] == "ABC Corp"
    assert p["blocks"][0]["text"] == "ABC Corp AI Acceptable Use Policy"
    assert p["commitment"]["description"] == "Create AI acceptable use policy"
    # a second policy cannot claim the same commitment
    r = client.post(f"{API}/policies", json={"template_code": "acceptable_use", "commitment_id": world["commitment"].id})
    assert r.status_code == 409


def test_answers_regenerate_and_edits_are_kept(client, db, world):
    login_as(client, db, world["caico"])
    p = _start(client, world)
    r = client.put(f"{API}/policies/{p['id']}/answers", json={"answers": p["answers"] | ANSWERS, "regenerate": True})
    assert r.status_code == 200, r.text
    assert any("ATS screening" in (b.get("items") or []) for b in r.json()["blocks"])
    blocks = r.json()["blocks"] + [{"type": "paragraph", "text": "Added by ABC."}]
    r = client.put(f"{API}/policies/{p['id']}/text", json={"blocks": blocks})
    assert r.status_code == 200 and r.json()["edited"] is True
    r = client.put(f"{API}/policies/{p['id']}/text", json={"blocks": [{"type": "table", "rows": []}]})
    assert r.status_code == 422
    # saving answers without regenerating keeps the edited text
    r = client.put(f"{API}/policies/{p['id']}/answers", json={"answers": p["answers"] | ANSWERS | {"personal_accounts": "public_only"}, "regenerate": False})
    assert r.json()["blocks"][-1] == {"type": "paragraph", "text": "Added by ABC."}


def test_contributor_cannot_edit_and_other_client_cannot_see(client, db, world):
    login_as(client, db, world["caico"])
    p = _start(client, world)
    login_as(client, db, world["contrib"])
    assert client.get(f"{API}/policies/{p['id']}").status_code in (403, 404)
    login_as(client, db, world["other_caico"])
    assert client.get(f"{API}/policies/{p['id']}").status_code == 404
    assert client.get(f"{API}/policies").json()["policies"] == []
    login_as(client, db, world["dpo"])
    r = client.put(f"{API}/policies/{p['id']}/answers", json={"answers": p["answers"] | ANSWERS})
    assert r.status_code == 200


def test_send_for_approval_needs_complete_answers_and_only_caico_approves(client, db, world):
    login_as(client, db, world["admin"])
    p = _start(client, world)
    r = client.post(f"{API}/policies/{p['id']}/submit")
    assert r.status_code == 422 and any(e["field"] == "approved_tools" for e in r.json()["errors"])
    client.put(f"{API}/policies/{p['id']}/answers", json={"answers": p["answers"] | ANSWERS, "regenerate": True})
    assert client.post(f"{API}/policies/{p['id']}/submit").json()["status"] == "awaiting_approval"
    assert client.put(f"{API}/policies/{p['id']}/text", json={"blocks": [{"type": "paragraph", "text": "x"}]}).status_code == 409
    assert client.post(f"{API}/policies/{p['id']}/approve", json={}).status_code == 403
    login_as(client, db, world["caico"])
    r = client.post(f"{API}/policies/{p['id']}/return", json={"note": "Add the HR screening tool."})
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["return_note"] == "Add the HR screening tool."


def _publish(client, db, w, ack=True):
    login_as(client, db, w["caico"])
    p = _start(client, w)
    client.put(f"{API}/policies/{p['id']}/answers", json={"answers": p["answers"] | ANSWERS, "regenerate": True})
    client.post(f"{API}/policies/{p['id']}/submit")
    body = {"acknowledgment": {"reminder_days": [3, 7]}} if ack else {}
    r = client.post(f"{API}/policies/{p['id']}/approve", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_approve_publishes_closes_the_commitment_and_starts_acknowledgments(client, db, world):
    p = _publish(client, db, world)
    assert p["status"] == "published" and p["published_at"] and p["review_due"]
    assert p["published_file"]["filename"].endswith(".pdf")
    db.expire_all()
    c = db.get(Commitment, world["commitment"].id)
    assert c.status == "closed"
    s = db.scalar(select(MailSend).where(MailSend.campaign_type == "policy_ack", MailSend.campaign_id == p["id"]))
    assert s is not None and s.recipient_count >= 3
    assert p["acknowledgments"]["sent"] >= 3 and p["acknowledgments"]["acknowledged"] == 0
    assert db.scalar(select(AuditLog).where(AuditLog.action == "policy.publish")) is not None
    # the published PDF is downloadable by the client and is the commitment's evidence
    r = client.get(f"{API}/files/{p['published_file']['id']}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    gov = client.get(f"{API}/policies").json()
    assert gov["commitments"] == []  # closed commitments are no longer offered


def test_published_policy_is_locked_and_a_new_version_supersedes_it(client, db, world):
    p = _publish(client, db, world, ack=False)
    assert client.put(f"{API}/policies/{p['id']}/text", json={"blocks": [{"type": "paragraph", "text": "x"}]}).status_code == 409
    r = client.post(f"{API}/policies/{p['id']}/new-version")
    assert r.status_code == 200
    v2 = r.json()
    assert v2["version_no"] == 2 and v2["status"] == "draft" and v2["blocks"] == p["blocks"]
    client.post(f"{API}/policies/{v2['id']}/submit")
    client.post(f"{API}/policies/{v2['id']}/approve", json={})
    assert client.get(f"{API}/policies/{p['id']}").json()["status"] == "retired"


def test_employee_acknowledges_through_the_personal_link(client, db, world, settings):
    from app.mail.sending import token_hash  # noqa: F401
    import re
    from app.mail.models import OutboxMessage

    p = _publish(client, db, world)
    msg = next(m for m in db.scalars(select(OutboxMessage)) if "hannah@abc.test" in (m.to or []))
    token = re.search(r"/m/([A-Za-z0-9_\-]+)", msg.body_text).group(1)
    client.cookies.clear()
    v = client.get(f"{API}/public/m/{token}")
    assert v.status_code == 200 and v.json()["kind"] == "policy_ack"
    assert v.json()["title"] == "AI acceptable use policy" and v.json()["blocks"][0]["type"] == "heading"
    r = client.post(f"{API}/public/m/{token}/attestation", json={"confirm": True})
    assert r.status_code == 200
    login_as(client, db, world["caico"])
    got = client.get(f"{API}/policies/{p['id']}").json()["acknowledgments"]
    assert got["acknowledged"] == 1
    rows = client.get(f"{API}/policies/{p['id']}/acknowledgments").json()["rows"]
    assert [r["email"] for r in rows if r["acknowledged_at"]] == ["hannah@abc.test"]
