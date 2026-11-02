"""Raw applicant data retention (spec §21 F11): the uploaded rows are deleted at the end of the engagement retention period
(completion date plus the engagement's retention years) unless the client chose to keep them. The run's results stay."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.biascalc.models import BiasTestRun
from app.biascalc.service import raw_delete_on
from app.files.models import FileObject
from app.files.storage import get_storage


def purge_expired_raw_data(db: Session, settings, now: datetime) -> int:
    n = 0
    runs = db.scalars(select(BiasTestRun).where(BiasTestRun.deleted_at.is_(None), BiasTestRun.raw_deleted_at.is_(None), BiasTestRun.dataset_file_id.is_not(None)))
    for run in list(runs):
        if run.keep_raw_data:
            continue
        due = raw_delete_on(db, settings, run)
        if due is None or due > now.date():
            continue
        f = db.get(FileObject, run.dataset_file_id)
        shared = db.scalar(select(BiasTestRun.id).where(BiasTestRun.dataset_file_id == run.dataset_file_id, BiasTestRun.id != run.id, BiasTestRun.keep_raw_data.is_(True)))
        if f is not None and f.deleted_at is None and shared is None:
            get_storage(settings).delete(f.storage_key)
            f.deleted_at = now
        run.raw_delete_on, run.raw_deleted_at, run.dataset_file_id = due, now, None
        audit.record(db, actor_id=None, action="bias_test.raw_data_deleted", obj=run, after={"file": run.dataset_filename, "due": due.isoformat()},
                     summary=f"Deleted the raw applicant data {run.dataset_filename} at the end of the retention period")
        n += 1
    db.flush()
    return n
