"""The public bias audit summary (NYC LL144 and laws flagged public_summary) and sign-off 8. Impact ratios are entered
by hand from the bias audit; the evidence is linked, not computed here."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Conflict, Invalid
from app.engagements.models import Engagement
from app.reports.models import PublicSummary
from app.reports.service import requires_public_summary
from app.tenancy.models import User


def current_summary(db: Session, e: Engagement) -> PublicSummary | None:
    return db.scalar(select(PublicSummary).where(PublicSummary.engagement_id == e.id, PublicSummary.deleted_at.is_(None)))


def _locked(db: Session, e: Engagement) -> bool:
    from app.signoffs.service import current

    so = current(db, e, 8)
    return so is not None and so.status in ("pending", "in_review", "approved")


def _date(v, field: str, errs: list):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        errs.append({"field": field, "message": "Enter a date."})
        return None


def _ratios(rows, errs: list) -> list[dict]:
    if not isinstance(rows, list):
        errs.append({"field": "impact_ratios", "message": "Enter the impact ratios as rows."})
        return []
    out = []
    for i, row in enumerate(rows[:200]):
        row = row if isinstance(row, dict) else {}
        category, group = " ".join(str(row.get("category") or "").split())[:80], " ".join(str(row.get("group") or "").split())[:120]
        try:
            rate = float(row.get("selection_rate")) if row.get("selection_rate") not in (None, "") else None
            ratio = float(row.get("impact_ratio"))
        except (TypeError, ValueError):
            errs.append({"field": f"impact_ratios.{i}", "message": f"Row {i + 1}: enter the impact ratio as a number."})
            continue
        if not category or not group:
            errs.append({"field": f"impact_ratios.{i}", "message": f"Row {i + 1}: enter the category and the group."})
        if rate is not None and not 0 <= rate <= 1:
            errs.append({"field": f"impact_ratios.{i}", "message": f"Row {i + 1}: the selection rate is between 0 and 1."})
        if not 0 <= ratio <= 1:
            errs.append({"field": f"impact_ratios.{i}", "message": f"Row {i + 1}: the impact ratio is between 0 and 1 (the most selected group is 1)."})
        out.append({"category": category, "group": group, "selection_rate": rate, "impact_ratio": ratio})
    return out


def save_summary(db: Session, actor: User, e: Engagement, data: dict) -> PublicSummary:
    from app.files.models import FileObject
    from app.systems.models import AISystem

    if not requires_public_summary(db, e):
        raise Conflict("This engagement does not need a public summary. It is needed when NYC Local Law 144, or another law that requires one, is in scope.")
    if _locked(db, e):
        raise Conflict("The public summary is with the CAICO for sign-off 8. To change it, ask them to return it.")
    errs: list = []
    sid = data.get("ai_system_id") or None
    if sid:
        sys = db.get(AISystem, sid) if isinstance(sid, str) else None
        if sys is None or sys.engagement_id != e.id or sys.deleted_at is not None:
            errs.append({"field": "ai_system_id", "message": "Choose a system from this engagement."})
    ids = data.get("evidence_file_ids") or []
    files = [db.get(FileObject, i) for i in ids] if isinstance(ids, list) and all(isinstance(i, str) for i in ids) else None
    if files is None or any(f is None or f.engagement_id != e.id or f.deleted_at is not None for f in files):
        errs.append({"field": "evidence_file_ids", "message": "Link evidence from this engagement."})
    unknown = data.get("unknown_category_count")
    if unknown not in (None, "") and (not str(unknown).isdigit()):
        errs.append({"field": "unknown_category_count", "message": "Enter a whole number."})
    vals = {
        "ai_system_id": sid, "tool_name": (" ".join(str(data.get("tool_name") or "").split())[:200]) or None,
        "audit_date": _date(data.get("audit_date"), "audit_date", errs), "distribution_date": _date(data.get("distribution_date"), "distribution_date", errs),
        "data_source": (str(data.get("data_source") or "").strip()[:4000]) or None, "notes": (str(data.get("notes") or "").strip()[:4000]) or None,
        "unknown_category_count": int(unknown) if str(unknown or "").isdigit() else None, "impact_ratios": _ratios(data.get("impact_ratios") or [], errs),
        "evidence_file_ids": list(dict.fromkeys(ids)) if files is not None else [],
    }
    if errs:
        raise Invalid(errors=errs)
    s = current_summary(db, e)
    if s is None:
        s = PublicSummary(organization_id=e.client_id, engagement_id=e.id, created_by=actor.id)
        db.add(s)
    for k, v in vals.items():
        setattr(s, k, v)
    s.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="public_summary.save", obj=s, after={"tool_name": s.tool_name, "rows": len(s.impact_ratios)}, summary=f"Updated the public summary for {e.audit_ref}")
    return s


def summary_text(s: PublicSummary) -> str:
    lines = [f"Bias audit summary: {s.tool_name}", f"Date of the bias audit: {s.audit_date.isoformat() if s.audit_date else 'not recorded'}",
             f"Distribution date of the tool: {s.distribution_date.isoformat() if s.distribution_date else 'not recorded'}", f"Data used: {s.data_source}"]
    if s.unknown_category_count is not None:
        lines.append(f"Individuals in an unknown category: {s.unknown_category_count}")
    lines.append("Impact ratios:")
    for r in s.impact_ratios or []:
        rate = f"selection rate {r['selection_rate']:.2f}, " if r.get("selection_rate") is not None else ""
        lines.append(f"- {r['category']} · {r['group']}: {rate}impact ratio {r['impact_ratio']:.2f}")
    return "\n".join(lines)


def summary_unmet(db: Session, e: Engagement, _scope=None) -> list[str]:
    if not requires_public_summary(db, e):
        return ["This engagement does not need a public summary."]
    out = [] if e.stage >= 8 else ["The public summary is approved at stage 8 (final report)."]
    s = current_summary(db, e)
    if s is None or not s.tool_name:
        out.append("Name the tool the summary covers.")
    if s is None or not s.audit_date:
        out.append("Enter the date of the bias audit.")
    if s is None or not s.data_source:
        out.append("Describe the data the bias audit used.")
    if s is None or not s.impact_ratios:
        out.append("Enter at least one impact ratio.")
    return out


def summary_statement(db: Session, e: Engagement) -> str | None:
    s = current_summary(db, e)
    return summary_text(s) if s is not None else None


def summary_out(db: Session, e: Engagement) -> dict:
    s = current_summary(db, e)
    base = {"required": requires_public_summary(db, e)}
    if s is None:
        return base | {"summary": None, "text": None}
    return base | {"summary": {"ai_system_id": s.ai_system_id, "tool_name": s.tool_name, "audit_date": s.audit_date.isoformat() if s.audit_date else None,
                               "distribution_date": s.distribution_date.isoformat() if s.distribution_date else None, "data_source": s.data_source, "notes": s.notes,
                               "unknown_category_count": s.unknown_category_count, "impact_ratios": s.impact_ratios or [], "evidence_file_ids": s.evidence_file_ids or []},
                   "text": summary_text(s)}
