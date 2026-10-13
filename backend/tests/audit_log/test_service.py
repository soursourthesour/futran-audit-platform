import pytest

from app.audit_log import service as audit
from app.audit_log.models import AuditLog
from app.tenancy.service import create_organization, create_user


def test_audit_record_stores_before_after(db):
    org = create_organization(db, name="ABC Corp", type="client")
    u = create_user(db, org, name="Priya Shah", email="p@abc.com")
    entry = audit.record(db, actor_id=u.id, action="user.update", obj=u, before={"job_title": None}, after={"job_title": "Head of HR"})
    db.flush()
    assert entry.object_type == "User"
    assert entry.object_id == u.id
    assert entry.organization_id == org.id
    assert entry.before == {"job_title": None}
    assert entry.after == {"job_title": "Head of HR"}
    rows = audit.query(db, organization_id=org.id, object_id=u.id)
    assert [r.action for r in rows] == ["user.update"]


def test_audit_log_is_append_only(db):
    org = create_organization(db, name="ABC Corp", type="client")
    entry = audit.record(db, actor_id=None, action="org.create", obj=org, before=None, after={"name": "ABC Corp"})
    db.commit()
    entry.action = "tampered"
    with pytest.raises(PermissionError):
        db.flush()
    db.rollback()
    entry = db.get(AuditLog, entry.id)
    db.delete(entry)
    with pytest.raises(PermissionError):
        db.flush()
