"""Security review: action traces are append-only in the ORM and in the database, like the audit log."""
from datetime import datetime

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DatabaseError

from app.register.models import RegisterSystem
from app.tracing.models import ActionTrace
from tests.factories import make_org


def _row(db):
    org = make_org(db, name="ABC Corp")
    s = RegisterSystem(organization_id=org.id, reference="AIS-001", name="Invoice agent", type="agent", sourcing="vendor", stage="live")
    db.add(s)
    db.flush()
    t = ActionTrace(organization_id=org.id, register_system_id=s.id, at=datetime(2028, 3, 1, 10, 0), action="Approve payment", decision="blocked")
    db.add(t)
    db.commit()
    return t


def test_an_action_trace_cannot_be_edited_or_deleted_through_the_orm(db):
    t = _row(db)
    t.decision = "allowed"
    with pytest.raises(PermissionError):
        db.flush()
    db.rollback()
    db.delete(db.get(ActionTrace, t.id))
    with pytest.raises(PermissionError):
        db.flush()
    db.rollback()
    with pytest.raises(PermissionError):
        db.execute(update(ActionTrace).values(decision="allowed"))
    with pytest.raises(PermissionError):
        db.execute(delete(ActionTrace))


def test_the_database_refuses_edits_to_action_traces(db):
    t = _row(db)
    with pytest.raises(DatabaseError):
        db.connection().exec_driver_sql("UPDATE action_traces SET decision = 'allowed'")
    db.rollback()
    with pytest.raises(DatabaseError):
        db.connection().exec_driver_sql("DELETE FROM action_traces")
    db.rollback()
    assert db.execute(text("SELECT decision FROM action_traces WHERE id = :i"), {"i": t.id}).scalar() == "blocked"
