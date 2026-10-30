from sqlalchemy import select

from app.laws.models import Regulation
from app.notifications.models import Notification
from app.register.models import ChangeLog, RegisterSystem
from tests.register.conftest import new_system


def _three(client, reg):
    reg.as_(reg.caico)
    a = new_system(client, name="Résumé screening", department_id=reg.hr.id, owner_user_id=reg.hr_user.id)
    b = new_system(client, name="Benefits Q&A agent", type="agent", sourcing="in_house", department_id=reg.hr.id, stage="ready_for_go_live")
    c = new_system(client, name="Interview scheduling agent", type="agent", department_id=reg.hr.id, stage="in_development")
    return a, b, c


def _law(db, name_part):
    return db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None), Regulation.short_name.ilike(f"%{name_part}%"))).first()


def test_bulk_needs_reason(client, db, reg):
    a, b, c = _three(client, reg)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], b["id"]], "changes": {"owner_user_id": reg.hr_lead.id}, "reason": " "})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "reason"


def test_bulk_applies_only_changed_fields_and_logs_reason(client, db, reg):
    a, b, c = _three(client, reg)
    reg.as_(reg.hr_lead)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], b["id"], c["id"]], "changes": {"owner_user_id": reg.hr_lead.id, "bias_next_due": "2026-12-15"},
                                                   "reason": "Assigning owners before the go-live review."})
    assert r.status_code == 200, r.text
    assert r.json()["systems_changed"] == 3
    db.expire_all()
    for sid in (a["id"], b["id"], c["id"]):
        s = db.get(RegisterSystem, sid)
        assert s.owner_user_id == reg.hr_lead.id and s.bias_next_due.isoformat() == "2026-12-15"
        assert s.purpose == "Ranks applicants for recruiters."  # untouched
    rows = db.scalars(select(ChangeLog).where(ChangeLog.field == "owner_user_id")).all()
    assert len(rows) == 3 and {r.reason for r in rows} == {"Assigning owners before the go-live review."}
    assert len({r.batch_id for r in rows}) == 1 and rows[0].batch_id
    assert {r.old_value for r in rows} == {"Hana Ito", None}


def test_bulk_never_sets_live(client, db, reg):
    a, b, c = _three(client, reg)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [b["id"]], "changes": {"stage": "live"}, "reason": "Go"})
    assert r.status_code == 409 and "Live" in r.json()["detail"]


def test_bulk_stage_change(client, db, reg):
    a, b, c = _three(client, reg)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], c["id"]], "changes": {"stage": "in_development"}, "reason": "Procurement started."})
    assert r.status_code == 200
    assert r.json()["systems_changed"] == 1  # c was already in development


def test_bulk_is_all_or_nothing_on_permissions(client, db, reg):
    reg.as_(reg.caico)
    a = new_system(client, name="HR tool", department_id=reg.hr.id)
    f = new_system(client, name="Finance tool", department_id=reg.fin.id)
    reg.as_(reg.hr_lead)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], f["id"]], "changes": {"purpose": "x"}, "reason": "Tidy"})
    assert r.status_code == 404
    db.expire_all()
    assert db.get(RegisterSystem, a["id"]).purpose == "Ranks applicants for recruiters."


def test_bulk_preview_counts_without_saving(client, db, reg):
    a, b, c = _three(client, reg)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], b["id"]], "changes": {"owner_user_id": reg.hr_lead.id}, "reason": "x", "preview": True})
    assert r.status_code == 200
    body = r.json()
    assert body["preview"] is True and body["change_count"] == 2 and body["systems_changed"] == 2
    db.expire_all()
    assert db.get(RegisterSystem, b["id"]).owner_user_id is None


def test_bulk_add_and_remove_law(client, db, reg, matrix):
    a, b, c = _three(client, reg)
    law = _law(db, "144") or db.scalars(select(Regulation).where(Regulation.superseded_by_id.is_(None))).first()
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], b["id"]], "add_regulation_ids": [law.id], "reason": "Hiring in New York."})
    assert r.status_code == 200, r.text
    assert [l["short_name"] for l in client.get(f"/api/v1/register/{a['id']}").json()["laws"]] == [law.short_name]
    # a Department Head's removal waits for the AI Compliance Officer
    reg.as_(reg.hr_lead)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"]], "remove_regulation_ids": [law.id], "reason": "No New York hiring."})
    assert r.status_code == 200
    laws = client.get(f"/api/v1/register/{a['id']}").json()["laws"]
    assert laws[0]["status"] == "removal_pending"
    assert db.scalar(select(Notification).where(Notification.user_id == reg.caico.id, Notification.kind == "register_law_removal")) is not None


def test_dept_lead_cannot_bulk_add_law_to_company_wide(client, db, reg, matrix):
    reg.as_(reg.caico)
    cw = new_system(client, name="Copilot", type="embedded_feature", company_wide=True)
    reg.as_(reg.hr_lead)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [cw["id"]], "changes": {"purpose": "x"}, "reason": "x"})
    assert r.status_code == 403


def test_request_bias_test_notifies_owners(client, db, reg):
    a, b, c = _three(client, reg)
    r = client.post("/api/v1/register/bulk", json={"system_ids": [a["id"]], "request_bias_test": {"due": "2026-12-01"}, "reason": "Annual LL144 audit."})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RegisterSystem, a["id"]).bias_next_due.isoformat() == "2026-12-01"
    n = db.scalar(select(Notification).where(Notification.user_id == reg.hr_user.id, Notification.kind == "register_bias_test_requested"))
    assert n is not None and "Résumé screening" in n.title


def test_bulk_failure_after_the_changes_leaves_every_system_as_it_was(client, db, reg, monkeypatch):
    """The bulk edit applies to every selected system or to none, even when something fails after the per-system
    changes (the savepoint must not commit them on its own)."""
    import pytest

    a, b, c = _three(client, reg)
    reg.as_(reg.hr_lead)

    import app.notifications.service as notifications

    def boom(*args, **kw):
        raise RuntimeError("notifications unavailable")

    monkeypatch.setattr(notifications, "notify", boom)  # runs after the per-system changes
    with pytest.raises(RuntimeError):
        client.post("/api/v1/register/bulk", json={"system_ids": [a["id"], b["id"]], "changes": {"purpose": "Changed in bulk"}, "reason": "Tidy",
                                                   "request_bias_test": {"due": "2026-12-01"}})
    db.expire_all()
    assert {db.get(RegisterSystem, x["id"]).purpose for x in (a, b)} != {"Changed in bulk"}
    assert db.scalars(select(ChangeLog).where(ChangeLog.reason == "Tidy")).first() is None
