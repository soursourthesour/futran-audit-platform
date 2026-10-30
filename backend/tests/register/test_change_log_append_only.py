"""Security review: the register change log is append-only in the ORM and in the database, like the audit log."""
import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DatabaseError

from app.register.models import ChangeLog
from tests.factories import make_org


def _row(db):
    org = make_org(db, name="ABC Corp")
    row = ChangeLog(organization_id=org.id, entity="RegisterSystem", entity_id="s1", field="stage", old_value="pilot", new_value="live", reason="Go-live approved")
    db.add(row)
    db.commit()
    return row


def test_a_change_log_row_cannot_be_edited_or_deleted_through_the_orm(db):
    row = _row(db)
    row.new_value = "retired"
    with pytest.raises(PermissionError):
        db.flush()
    db.rollback()
    db.delete(db.get(ChangeLog, row.id))
    with pytest.raises(PermissionError):
        db.flush()
    db.rollback()
    with pytest.raises(PermissionError):
        db.execute(update(ChangeLog).values(reason="x"))
    with pytest.raises(PermissionError):
        db.execute(delete(ChangeLog))


def test_the_database_refuses_edits_to_the_change_log(db):
    row = _row(db)
    with pytest.raises(DatabaseError):
        db.connection().exec_driver_sql("UPDATE change_log SET reason = 'x'")
    db.rollback()
    with pytest.raises(DatabaseError):
        db.connection().exec_driver_sql("DELETE FROM change_log")
    db.rollback()
    assert db.execute(text("SELECT reason FROM change_log WHERE id = :i"), {"i": row.id}).scalar() == "Go-live approved"
