"""Monitoring check "Training below target" (spec §21 F12 and F3): one outcome per department with AI literacy
assignments. Below the client's target: attention until the target date, failed after it. Reads only."""
from sqlalchemy import select

from app.core.clock import today
from app.monitoring.registry import CheckOutcome, register_check
from app.tenancy.models import Department
from app.training.models import TrainingAssignment, TrainingProgram


def training_below_target(db, org) -> list[CheckOutcome]:
    rows = list(db.scalars(select(TrainingAssignment).where(TrainingAssignment.organization_id == org.id, TrainingAssignment.deleted_at.is_(None))))
    if not rows:
        return [CheckOutcome(None, "AI literacy training", "not_started", "No AI literacy modules have been assigned yet.", "/training")]
    prog = db.scalar(select(TrainingProgram).where(TrainingProgram.organization_id == org.id, TrainingProgram.deleted_at.is_(None)))
    target = prog.target_pct if prog else 80
    by = prog.target_date if prog else None
    names = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org.id))}
    out = []
    for dept_id in sorted({a.department_id for a in rows}, key=lambda d: names.get(d, "~")):
        mine = [a for a in rows if a.department_id == dept_id]
        done = sum(a.status == "completed" for a in mine)
        pct = round(100 * done / len(mine))
        label = names.get(dept_id, "No department recorded")
        detail = f"{pct}% complete ({done} of {len(mine)}), target {target}%" + (f" by {by:%d %b %Y}" if by else "")
        if pct >= target:
            status = "healthy"
        else:
            status = "failed" if by is not None and by < today() else "attention"
        out.append(CheckOutcome(dept_id, label, status, detail, "/training", action="send_reminder" if status != "healthy" else None))
    return out


register_check("training_below_target", "AI literacy training below target", "medium", "monthly", "department", training_below_target)
