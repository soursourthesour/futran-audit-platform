"""Board readout pack (catalog A-13, Release 2 B6): an export from a signed report. One-page summary, heat map, top 5
findings and roadmap, as PDF. PowerPoint is not produced: the platform has no PowerPoint library (python-pptx is not
installed and Release 2 adds no Python dependencies).

The pack is drawn from the same content as the report and only while it still matches the signed final report (its
content hash), so the board never sees anything the signed report does not say."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.engagements.models import Engagement
from app.reports.models import Report
from app.scoring import scale

SEVERITY_ORDER = ("critical", "high", "medium", "low", "observation")


def signed_report(db: Session, e: Engagement) -> Report | None:
    return db.scalar(select(Report).where(Report.engagement_id == e.id, Report.version == "v1.1", Report.status == "final", Report.deleted_at.is_(None))
                     .order_by(Report.created_at.desc()).limit(1))


def _cell(v) -> str:
    return " ".join(str(v if v is not None else "").replace("|", "/").split()) or "—"


def readout_markdown(db: Session, e: Engagement) -> str:
    from app.reports.service import _content_data, _hash

    r = signed_report(db, e)
    if r is None:
        raise Conflict("The board readout pack is exported from a signed final report. Sign the final report (v1.1) first.")
    data = _content_data(db, e)
    if _hash(data) != r.content_hash:
        raise Conflict("The report has changed since the final version was signed. Issue a corrected final report before exporting the board readout.")
    s, c = data["summary"], data["counts"]
    signed = f"{r.signed_at:%d %B %Y}" if r.signed_at else "signed"
    client = (data.get("client") or {}).get("name") or ""
    lines = [f"# Board readout: {client}" if client else "# Board readout", "",
             f"{e.audit_ref or ''} · From the final audit report ({signed}) · Futran Audit Platform", "",
             "## One-page summary", "",
             f"**Overall rating:** {data['overall_rating']} · **Overall maturity:** {data['overall_maturity']}", "",
             f"**Findings:** {c['total']} in total: " + ", ".join(f"{c[k]} {scale.label(k) or k.capitalize()}".lower() for k in SEVERITY_ORDER if c.get(k)) + ".", ""]
    if s.get("most_significant_title"):
        lines += [f"**Most significant finding:** {s['most_significant_ref']} {s['most_significant_title']}", ""]
    if s.get("most_significant_text"):
        lines += [s["most_significant_text"], ""]
    if s.get("strengths"):
        lines += [f"**Strengths:** {s['strengths']}", ""]
    if s.get("immediate_actions"):
        lines += [f"**Immediate actions:** {s['immediate_actions']}", ""]
    lines += ['<div class="pagebreak"></div>', "", "## Heat map", "", "| System | Department | Inherent | Residual | Rating |", "|---|---|---|---|---|"]
    for sys in data["systems"]:
        lines.append(f"| {_cell(sys['ref'] + ' ' + sys['name'])} | {_cell(sys['department'])} | {_cell(sys['inherent'])} | {_cell(sys['residual'])} | "
                     f"{scale.labelled(sys['rating_key']) if sys.get('rating_key') else _cell(sys['rating'])} |")
    if not data["systems"]:
        lines.append("| No systems in scope | | | | |")
    lines += ["", "| Severity | Findings |", "|---|---|"] + [f"| {scale.labelled(k)} | {c.get(k, 0)} |" for k in SEVERITY_ORDER if k in c]
    top = sorted(data["findings"], key=lambda f: (SEVERITY_ORDER.index(f["severity"]) if f["severity"] in SEVERITY_ORDER else 9, f["ref"] or ""))[:5]
    lines += ["", "## Top 5 findings", "", "| Ref | Finding | Severity | System | Owner |", "|---|---|---|---|---|"]
    lines += [f"| {_cell(f['ref'])} | {_cell(f['title'])} | {scale.labelled(f['severity'], f['severity_label'])} | {_cell(f['system_or_scope'])} | {_cell(f['owner'])} |" for f in top]
    if not top:
        lines.append("| | No findings | | | |")
    lines += ["", "## Roadmap", "", "| Ref | Action | Priority | Owner | Target |", "|---|---|---|---|---|"]
    lines += [f"| {_cell(x['ref'])} | {_cell(x['action'])} | {_cell(x['priority'])} | {_cell(x['owner'])} | {_cell(x['target_date'])} |" for x in data["roadmap"]]
    if not data["roadmap"]:
        lines.append("| | No roadmap items | | | |")
    return "\n".join(lines) + "\n"


def readout_pdf(db: Session, e: Engagement) -> bytes:
    from app.documents.pdf import to_pdf

    return to_pdf(readout_markdown(db, e), "Board readout", {"audit_ref": e.audit_ref or ""})
