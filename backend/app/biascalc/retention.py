"""Raw applicant data retention (spec §21 F11): the uploaded rows are deleted at the end of the engagement retention period
(completion date plus the engagement's retention years) unless the client chose to keep them. The run's results stay.
The text extracted from the file for the copilot holds the same rows, so it goes with the file. Each run is purged on its
own: one that fails is logged and left for the next day, and the others still go."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import DocumentText
from app.audit_log import service as audit
from app.biascalc.models import BiasTestRun
from app.biascalc.service import raw_delete_on
from app.files.models import FileObject
from app.files.storage import get_storage

log = logging.getLogger(__name__)

def purge_expired_raw_data(db: Session, settings, now: datetime) -> int:
    n = 0
    runs = db.scalars(select(BiasTestRun).where(BiasTestRun.deleted_at.is_(None), BiasTestRun.raw_deleted_at.is_(None), BiasTestRun.dataset_file_id.is_not(None)))
    for run in list(runs):
        if run.keep_raw_data:
            continue
        due = raw_delete_on(db, settings, run)
        if due is None or due > now.date():
            continue
        try:
            with db.begin_nested():  # the file is deleted from storage last, so a failure leaves the database as it was
                f = db.get(FileObject, run.dataset_file_id)
                shared = db.scalar(select(BiasTestRun.id).where(BiasTestRun.dataset_file_id == run.dataset_file_id, BiasTestRun.id != run.id, BiasTestRun.keep_raw_data.is_(True)))
                gone = f is not None and f.deleted_at is None and shared is None
                if gone:
                    for dt in db.scalars(select(DocumentText).where(DocumentText.file_id == f.id)):
                        db.delete(dt)
                    f.deleted_at = now
                run.raw_delete_on, run.raw_deleted_at, run.dataset_file_id = due, now, None
                audit.record(db, actor_id=None, action="bias_test.raw_data_deleted", obj=run, after={"file": run.dataset_filename, "due": due.isoformat()},
                             summary=f"Deleted the raw applicant data {run.dataset_filename} at the end of the retention period")
                db.flush()
                if gone:
                    get_storage(settings).delete(f.storage_key)
        except Exception:
            log.exception("Could not delete the raw applicant data of bias test run %s; it is retried on the next run of the job", run.id)
            continue
        n += 1
    db.flush()
    return n
