"""Wires insights into the report and the sign-off flow: Appendix D (heat map), Appendix E (lineage), Appendix F
(year-over-year for an annual review) and the benchmarking snapshot when the final report is signed."""
from sqlalchemy.orm import Session

from app.engagements.models import Engagement
from app.reports import register as _reports  # noqa: F401  sign-off 7's own hook goes first
from app.reports import service as reports
from app.scoring import scale
from app.signoffs import service as so_svc


def report_context(db: Session, e: Engagement, data: dict) -> None:
    from app.insights import heatmap, lineage

    hm = heatmap.build(db, e, approved_only=True)
    placed = [s for s in hm["systems"] if s["column"] is not None]
    if hm["systems"]:
        rows = []
        for r in hm["rows"]:
            cells = []
            for cell in hm["grid"][r]:
                refs = ", ".join(c["reference_id"] + ("*" if c["provisional"] else "") for c in cell["systems"])
                cells.append({"text": f"{scale.label(cell['band'])}: {refs}" if refs else scale.label(cell["band"])})
            rows.append({"label": f"Maturity {r}", "cells": cells})
        fg = hm["findings_grid"]
        data["heatmap"] = {"columns": hm["columns"], "rows": rows, "domains": [d["label"] for d in fg["domains"]], "provisional": any(s["provisional"] for s in placed),
                           "unplaced": ", ".join(hm["unplaced"]),
                           "finding_rows": [{"label": r["label"], "counts": r["counts"]} for r in fg["rows"] if any(r["counts"])]}
    data["lineage"] = lineage.report_lineage(db, e)
    if e.prior_engagement_id:
        from app.annual.service import year_over_year

        data["year_over_year"] = year_over_year(db, e)


if report_context not in reports.CONTEXT_HOOKS:
    reports.CONTEXT_HOOKS.append(report_context)


from app.insights.benchmark import snapshot_on_signoff  # noqa: E402

if snapshot_on_signoff not in so_svc.ON_APPROVED.setdefault(7, []):
    so_svc.ON_APPROVED[7].append(snapshot_on_signoff)
