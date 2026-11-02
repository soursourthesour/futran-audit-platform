"""Risk heat map (spec §21 F13, screen 35): AI systems placed by inherent risk band (columns) and control maturity (rows)
from the existing scores, cells coloured by the residual band at the cell's centre, and findings by severity × domain.

Rulings: columns are the methodology's residual bands applied to the inherent score (0–24.9, 25–49.9, 50–74.9, 75–100);
rows are maturity 1, 2, 3 and 4–5 (as in the mockup). A cell's colour is the residual band of the cell's centre point
(inherent band midpoint, maturity midpoint 1.5, 2.5, 3.5 or 4.5) computed with the methodology's residual formula, so
the colours move if the methodology changes. Each system chip shows its own final rating; a knock-out can raise a system
above its cell. A score not yet locked by sign-off 5 is provisional (*).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engagements.models import Engagement
from app.findings.models import Finding
from app.scoring import engine, scale
from app.scoring import service as scoring
from app.systems.models import AISystem
from app.tenancy.models import Department

ROWS = ("4–5", "3", "2", "1")  # top to bottom
ROW_MID = {"1": 1.5, "2": 2.5, "3": 3.5, "4–5": 4.5}
BUILT_BY = {"in_house": "In-house", "vendor": "Vendor", "open_source_customized": "Open source, customized", "hybrid": "Hybrid"}
SEVERITIES = ("critical", "high", "medium", "low", "observation")


def columns(bands: list[dict]) -> list[dict]:
    mins = sorted(b["min"] for b in bands)
    out = []
    for i, lo in enumerate(mins):
        hi = mins[i + 1] if i + 1 < len(mins) else 100
        out.append({"label": f"{lo:g}–{hi - 0.1:g}" if i + 1 < len(mins) else f"{lo:g}–100", "min": lo, "max": hi})
    return out


def column_of(inherent: float | None, bands: list[dict]) -> int | None:
    if inherent is None:
        return None
    cols = columns(bands)
    return max(i for i, c in enumerate(cols) if inherent >= c["min"])


def row_of(maturity: float | None) -> str | None:
    if maturity is None:
        return None
    return "1" if maturity < 2 else "2" if maturity < 3 else "3" if maturity < 4 else "4–5"


def cell_bands(m: engine.Methodology) -> dict[str, list[str]]:
    cols = columns(m.bands)
    return {row: [engine.band(engine.residual((c["min"] + c["max"]) / 2, ROW_MID[row], m), m) for c in cols] for row in ROWS}


def _framework_of(ref: str) -> str:
    return ref.split(" ", 1)[0]


def findings_grid(db: Session, e: Engagement, m: engine.Methodology, *, approved_only: bool, framework: str | None = None, system_ids: set[str] | None = None) -> dict:
    stmt = select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None))
    if approved_only:
        stmt = stmt.where(Finding.status == "approved")
    domains = list(m.domains.items())
    rows = {sev: [0] * len(domains) for sev in SEVERITIES}
    unassigned = {sev: 0 for sev in SEVERITIES}
    total = 0
    for f in db.scalars(stmt):
        if framework and not any(_framework_of(r) == framework for r in f.control_refs or []):
            continue
        if system_ids is not None and f.ai_system_id is not None and f.ai_system_id not in system_ids:
            continue
        d = scoring._domain_of(f.template_section)
        total += 1
        keys = [k for k, _ in domains]
        if d in keys:
            rows[f.severity][keys.index(d)] += 1
        else:
            unassigned[f.severity] += 1
    return {"domains": [{"key": k, "label": label} for k, label in domains], "rows": [{"severity": s, "label": scale.labelled(s), "counts": rows[s], "unassigned": unassigned[s]} for s in SEVERITIES],
            "total": total}


def build(db: Session, e: Engagement, *, department: str | None = None, build_type: str | None = None, framework: str | None = None, approved_only: bool = False) -> dict:
    from app.systems.service import systems_for

    m = scoring.methodology(db)
    ko = {k["code"]: k["label"] for k in m.knockout_rules}
    grid = {row: [{"band": b, "systems": []} for b in bands] for row, bands in cell_bands(m).items()}
    systems = []
    for s in systems_for(db, e):
        if department and s.department_id != department:
            continue
        if build_type and s.built_by != build_type:
            continue
        row = scoring.latest(db, s)
        mm = scoring.methodology(db, row.methodology_version) if row else m
        inh, mat = (row.inherent, row.maturity) if row else (None, None)
        col, r = column_of(inh, mm.bands), row_of(mat)
        dept = db.get(Department, s.department_id) if s.department_id else None
        item = {"id": s.id, "reference_id": s.reference_id, "name": s.name, "built_by": s.built_by, "built_by_label": BUILT_BY.get(s.built_by or "", "Not recorded"),
                "department": dept.name if dept else None, "department_id": s.department_id, "inherent": inh, "maturity": mat, "residual": row.residual if row else None,
                "computed_rating": row.computed_rating if row else None, "final_rating": row.final_rating if row else None,
                "final_label": scale.labelled(row.final_rating) if row and row.final_rating else "Not rated",
                "residual_band": engine.band(row.residual, mm) if row and row.residual is not None else None,
                "knockouts": [ko.get(k, k) for k in (row.knockouts_triggered if row else [])], "provisional": not (row and row.locked_at is not None),
                "raised_by_knockout": bool(row and row.final_rating and row.computed_rating and scale.level(row.final_rating) > scale.level(row.computed_rating) and not row.override_rating),
                "override": bool(row and row.override_rating), "column": col if r is not None else None, "row": r if col is not None else None}
        systems.append(item)
        if item["column"] is not None:
            grid[r][col]["systems"].append({"id": s.id, "reference_id": s.reference_id, "final_rating": item["final_rating"], "provisional": item["provisional"]})
    ids = {x["id"] for x in systems} if (department or build_type) else None
    depts = [{"id": d.id, "name": d.name} for d in db.scalars(select(Department).where(Department.organization_id == e.client_id, Department.deleted_at.is_(None)).order_by(Department.name))]
    frameworks = sorted({_framework_of(r) for f in db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None))) for r in f.control_refs or []})
    return {"engagement": {"id": e.id, "audit_ref": e.audit_ref, "name": e.name, "stage": e.stage, "status": e.status}, "methodology_version": m.version,
            "columns": columns(m.bands), "rows": list(ROWS), "grid": grid, "systems": systems, "unplaced": [x["reference_id"] for x in systems if x["column"] is None],
            "findings_grid": findings_grid(db, e, m, approved_only=approved_only, framework=framework, system_ids=ids),
            "filters": {"departments": depts, "build_types": [{"key": k, "label": v} for k, v in BUILT_BY.items()], "frameworks": frameworks},
            "knockout_note": "Knock-out rules can raise a system above the band of its cell. Each chip shows the system's final rating."}
