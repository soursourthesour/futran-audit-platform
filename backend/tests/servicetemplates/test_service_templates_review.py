"""G-06 review fix: nobody approves a template version they edited at any point, not only the last editor."""
from app.servicetemplates import service as svc
from tests.servicetemplates.test_service_templates import w  # noqa: F401


def test_a_dual_role_user_who_edited_earlier_cannot_approve_after_someone_else_edits_and_submits(w):
    v = svc.latest_version(w.db, "ma_due_diligence")
    w.as_(w.both)  # Chief Auditor and Futran Admin
    assert w.client.put(f"/api/v1/service-template-versions/{v.id}", json={"deliverables": ["Red-flag memo"]}).status_code == 200
    w.as_(w.admin)
    assert w.client.put(f"/api/v1/service-template-versions/{v.id}", json={"default_stages": ["Inventory", "Exposure"]}).status_code == 200
    assert w.client.post(f"/api/v1/service-template-versions/{v.id}/submit").status_code == 200
    w.as_(w.both)
    assert w.client.post(f"/api/v1/service-template-versions/{v.id}/approve", json={}).status_code == 403
    w.as_(w.chief)
    assert w.client.post(f"/api/v1/service-template-versions/{v.id}/approve", json={}).status_code == 200
