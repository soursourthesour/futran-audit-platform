"""Bias test runs on an audited AI system (spec §21 F11, screen 29) and what each run feeds: questionnaire answers 6.2.06,
5.1a.03 and 5.1a.05, a draft finding, the LL144 public summary and a bias test on the client's register.

Nothing a run computes reaches a finding, an answer, the public summary or the register until the auditor presses the
button for it; each of those steps is logged.
"""
from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.biascalc import dataset, stats
from app.biascalc.models import BiasTestRun
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.systems.models import AISystem
from app.tenancy.models import User

DEFAULTS = {"impact_ratio_threshold": 0.80, "small_category_share": 0.02, "exclude_small_categories": True}
MAX_FILE_MB = 20
CONTROL_REFS = ["NYC_LL144 6 RCNY § 5-301", "NIST_AI_RMF MEASURE 2.11", "EU_AI_ACT Art. 10"]


def bias_settings(db: Session, s: AISystem) -> dict:
    """Thresholds from the risk methodology the system is scored with (defaults 0.80 and 2%)."""
    from app.scoring.service import methodology
    from app.reference.models import RiskMethodology

    try:
        version = methodology(db, s.methodology_version).version
        row = db.scalar(select(RiskMethodology).where(RiskMethodology.version == version))
        cfg = dict(DEFAULTS, **((row.config or {}).get("bias_calculator") or {})) if row else dict(DEFAULTS)
    except Conflict:
        cfg = dict(DEFAULTS)
    return {"threshold": float(cfg["impact_ratio_threshold"]), "small_share": float(cfg["small_category_share"]), "exclude_small": bool(cfg["exclude_small_categories"])}


def null_compliance_band(unknown_pct: float) -> str:
    """5.1a.05 help text: Low under 20% excluded, Medium 20–50%, High over 50%. The auditor still decides (a documented
    rationale, or a design meant to avoid the audit, changes the rating)."""
    return "high" if unknown_pct > 50 else "medium" if unknown_pct >= 20 else "low"


def _flag(v) -> bool | None:
    if v in (None, ""):
        return None
    return str(v).strip().casefold() in ("1", "true", "yes", "on")


def runs_for(db: Session, s: AISystem) -> list[BiasTestRun]:
    return list(db.scalars(select(BiasTestRun).where(BiasTestRun.ai_system_id == s.id, BiasTestRun.deleted_at.is_(None)).order_by(BiasTestRun.run_at.desc(), BiasTestRun.created_at.desc())))


def get_run(db: Session, run_id: str) -> BiasTestRun:
    r = db.get(BiasTestRun, run_id)
    if r is None or r.deleted_at is not None:
        raise NotFound()
    return r


def lowest(results: dict) -> dict | None:
    """The lowest impact ratio across the sex, race/ethnicity and intersectional tables (excluded categories left out)."""
    best = None
    for dim in stats.DIMENSIONS:
        for c in (results.get("tables", {}).get(dim) or {}).get("categories", []):
            if c.get("impact_ratio") is not None and (best is None or c["impact_ratio"] < best["impact_ratio"]):
                best = {"dimension": dim, "key": c["key"], "label": c["label"], "impact_ratio": c["impact_ratio"]}
    return best


def below_threshold(results: dict) -> list[dict]:
    return [{"dimension": dim, "key": c["key"], "label": c["label"], "impact_ratio": c["impact_ratio"]}
            for dim in stats.DIMENSIONS for c in (results.get("tables", {}).get(dim) or {}).get("categories", []) if c.get("below_threshold")]


def unknown_pct(run: BiasTestRun) -> float | None:
    total = (run.results or {}).get("total")
    return round(100 * (run.unknown_count or 0) / total, 1) if total else None


def run_test(db: Session, settings, actor: User, s: AISystem, *, data: bytes | None, filename: str | None, file_id: str | None, method: str | None,
             data_source: str | None, exclude_small=None) -> BiasTestRun:
    from app.files.service import read, upload

    e = db.get(Engagement, s.engagement_id)
    errs: list[dict] = []
    if method not in stats.METHODS:
        errs.append({"field": "method", "message": "Choose the selection-rate method or the scoring-rate method."})
    source: FileObject | None = None
    if data is None:
        source = db.get(FileObject, file_id) if isinstance(file_id, str) and file_id else None
        if source is None or source.deleted_at is not None or source.engagement_id != e.id:
            errs.append({"field": "file_id", "message": "Choose a data file uploaded to this engagement, or upload one."})
        else:
            data, filename = read(settings, source), source.filename
    elif len(data) > MAX_FILE_MB * 1024 * 1024:
        errs.append({"field": "file", "message": f"Data files can be up to {MAX_FILE_MB} MB. Split the data by period or role."})
    if errs:
        raise Invalid(errors=errs)
    parsed = dataset.parse(data or b"")
    if not parsed.ok:
        raise Invalid("The data did not pass validation. Correct the rows listed and upload it again.", parsed.report["errors"])
    if method not in parsed.methods:
        need = "a selected column (yes or no)" if method == "selection_rate" else "a score column"
        raise Invalid(errors=[{"field": "method", "message": f"This method needs {need}. The file has {', '.join(parsed.report['columns'].values())}."}])
    cfg = bias_settings(db, s)
    keep = _flag(exclude_small)
    if keep is not None:
        cfg["exclude_small"] = keep
    res = stats.compute(parsed.rows, method=method, exclude_small=cfg["exclude_small"], small_share=cfg["small_share"], threshold=cfg["threshold"])
    out = res.as_dict()
    now = utcnow()
    run = BiasTestRun(organization_id=e.client_id, engagement_id=e.id, ai_system_id=s.id, dataset_filename=(filename or "data.csv")[:255], dataset_sha256=hashlib.sha256(data).hexdigest(),
                      data_source=(str(data_source or "").strip()[:4000] or None), method=method, categories=list(stats.DIMENSIONS), results=out, validation=parsed.report, settings=cfg,
                      unknown_count=res.unknown_count, excluded_categories=[f"{d}:{k}" for d, t in res.tables.items() for k in t.excluded], run_by=actor.id, run_at=now,
                      library_version=stats.LIBRARY_VERSION, created_by=actor.id)
    low = lowest(out)
    run.lowest_impact_ratio = low["impact_ratio"] if low else None
    db.add(run)
    db.flush()
    if source is not None:  # the client's upload: the run points at it, and retention covers it from now on
        run.dataset_file_id = source.id
    else:
        f = upload(db, settings, actor, data=data, filename=filename or "applicant-data.csv", content_type="text/csv", organization_id=e.client_id, engagement_id=e.id,
                   linked_type="bias_dataset", linked_id=run.id)
        run.dataset_file_id = f.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="bias_test.run", obj=run, after={"method": method, "rows": res.total, "unknown": res.unknown_count, "lowest": run.lowest_impact_ratio,
                                                                               "library_version": stats.LIBRARY_VERSION, "sha256": run.dataset_sha256},
                 summary=f"Ran the bias calculator on {s.reference_id} {s.name} ({res.total} rows)")
    return run


def feeds(db: Session, run: BiasTestRun) -> dict:
    from app.reports.service import requires_public_summary

    pct = unknown_pct(run)
    below = below_threshold(run.results or {})
    return {"q_6_2_06": run.lowest_impact_ratio, "q_5_1a_03": pct, "q_5_1a_05": null_compliance_band(pct) if pct is not None else None, "below_threshold": below,
            "draft_findings": 1 if below and not run.finding_ids else 0, "public_summary_required": requires_public_summary(db, db.get(Engagement, run.engagement_id))}


def raw_delete_on(db: Session, settings, run: BiasTestRun) -> date | None:
    """The end of the engagement retention period: completion date plus the engagement's retention years."""
    e = db.get(Engagement, run.engagement_id)
    if e.completed_at is None:
        return None
    years = e.retention_years or settings.retention_years_default
    d = e.completed_at.date()
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def run_out(db: Session, settings, run: BiasTestRun) -> dict:
    who = db.get(User, run.run_by) if run.run_by else None
    return {"id": run.id, "engagement_id": run.engagement_id, "ai_system_id": run.ai_system_id, "method": run.method, "method_label": stats.METHODS[run.method],
            "dataset_filename": run.dataset_filename, "dataset_file_id": run.dataset_file_id, "data_source": run.data_source, "results": run.results, "validation": run.validation,
            "settings": run.settings, "unknown_count": run.unknown_count, "unknown_pct": unknown_pct(run), "excluded_categories": run.excluded_categories,
            "lowest": lowest(run.results or {}), "run_by": who.name if who else None, "run_at": run.run_at.isoformat() if run.run_at else None, "library_version": run.library_version,
            "keep_raw_data": bool(run.keep_raw_data), "raw_deleted_at": run.raw_deleted_at.isoformat() if run.raw_deleted_at else None,
            "raw_delete_on": (d.isoformat() if (d := raw_delete_on(db, settings, run)) else None),
            "public_summary_at": run.public_summary_at.isoformat() if run.public_summary_at else None, "bias_test_id": run.bias_test_id, "finding_ids": run.finding_ids or [],
            "feeds": feeds(db, run)}


def client_run_out(db: Session, settings, run: BiasTestRun) -> dict:
    """What the client sees about its own raw data: the file, its deletion date and the keep choice. No results."""
    s = db.get(AISystem, run.ai_system_id)
    return {"id": run.id, "system": f"{s.reference_id} {s.name}", "dataset_filename": run.dataset_filename, "run_at": run.run_at.isoformat() if run.run_at else None,
            "keep_raw_data": bool(run.keep_raw_data), "raw_deleted_at": run.raw_deleted_at.isoformat() if run.raw_deleted_at else None,
            "raw_delete_on": (d.isoformat() if (d := raw_delete_on(db, settings, run)) else None)}


def _system(db: Session, run: BiasTestRun) -> tuple[AISystem, Engagement]:
    return db.get(AISystem, run.ai_system_id), db.get(Engagement, run.engagement_id)


def _run_note(run: BiasTestRun) -> str:
    return f"From the bias calculator run of {run.run_at.date().isoformat()} on {run.dataset_filename} ({stats.METHODS[run.method].lower()} method, {run.library_version})."


def apply_answers(db: Session, actor: User, run: BiasTestRun) -> dict:
    """Record 6.2.06 (lowest impact ratio), 5.1a.03 (unknown share) and the proposed 5.1a.05 rating as the auditor's answers."""
    from app.questionnaire.service import Target, save_response

    s, e = _system(db, run)
    f = feeds(db, run)
    applied, skipped = [], []
    for code, value in (("6.2.06", f["q_6_2_06"]), ("5.1a.03", f["q_5_1a_03"]), ("5.1a.05", f["q_5_1a_05"])):
        if value is None:
            skipped.append({"code": code, "reason": "The run has no figure for this question."})
            continue
        try:
            with db.begin_nested():
                save_response(db, actor, Target(e, s), code, {"value": value, "status": "answered", "detail": _run_note(run)}, futran=True)
            applied.append(code)
        except (Invalid, NotFound, Conflict) as exc:
            skipped.append({"code": code, "reason": exc.detail})
    audit.record(db, actor_id=actor.id, action="bias_test.apply_answers", obj=run, after={"applied": applied, "skipped": [x["code"] for x in skipped]},
                 summary=f"Recorded bias calculator figures as answers for {s.reference_id}")
    return {"applied": applied, "skipped": skipped}


def draft_findings(db: Session, actor: User, run: BiasTestRun) -> list[str]:
    """One draft finding listing every category below the threshold. Drafts go to the findings flow; never twice per run."""
    from app.findings.service import create_finding

    if run.finding_ids:
        return []
    below = below_threshold(run.results or {})
    if not below:
        return []
    s, e = _system(db, run)
    th = run.settings.get("threshold", 0.8)
    n = len(below)
    lines = "\n".join(f"- {b['label']}: {b['impact_ratio']:.2f} ({stats.DIMENSIONS[b['dimension']].lower()})" for b in below)
    desc = (f"The bias calculator found impact ratios below {th:.2f} for {s.name} using the {stats.METHODS[run.method].lower()} method defined in 6 RCNY § 5-301, "
            f"on {run.results.get('total')} records ({run.dataset_filename}).\n\n{lines}\n\n"
            "Risk: an impact ratio below four-fifths of the most selected category is the usual indicator of adverse impact (29 CFR § 1607.4(D)). "
            "Local Law 144 requires the ratios to be published; regulators and claimants read a low ratio as evidence the tool disadvantages that group.")
    f = create_finding(db, actor, e, {"title": f"Impact ratio below {th:.2f} for {n} categor{'y' if n == 1 else 'ies'}", "severity": "high", "template_section": "6.2",
                                      "description": desc, "ai_system_id": s.id, "source_question_ids": ["6.2.06"], "control_refs": CONTROL_REFS,
                                      "recommended_remediation": "Investigate the tool's features and thresholds for the groups listed, document the business justification "
                                                                 "or change the configuration, and re-run the bias test on new data before further use."})
    f.origin = "bias_run"
    run.finding_ids = [f.id]
    db.flush()
    audit.record(db, actor_id=actor.id, action="bias_test.draft_findings", obj=run, after={"finding": f.ref}, summary=f"Drafted finding {f.ref} from a bias calculator run")
    return [f.id]


JUSTIFICATION_MAX = 1000  # as the public summary keeps it
LEGACY_EXCLUSION_NOTE = "Excluded from the impact ratio calculations because"  # the note earlier versions wrote into the summary's notes


def summary_rows(run: BiasTestRun) -> tuple[list[dict], list[dict]]:
    """Every category in table order; an excluded category is a row marked excluded (and also listed in `excluded`)."""
    rows, excluded = [], []
    for dim, title in stats.DIMENSIONS.items():
        for c in (run.results.get("tables", {}).get(dim) or {}).get("categories", []):
            item = {"category": title, "group": c["label"], "applicants": c["applicants"], "selection_rate": round(c["rate"], 4), "rate_kind": "scoring" if run.method == "scoring_rate" else "selection"}
            if c.get("excluded"):
                excluded.append(item)
                rows.append(item | {"impact_ratio": None, "excluded": True})
            elif c.get("impact_ratio") is not None:
                rows.append(item | {"impact_ratio": round(c["impact_ratio"], 4)})
    return rows, excluded


def _hand_written(notes: str | None) -> str | None:
    """The summary's notes without the exclusion text earlier versions generated into them."""
    kept = [line for line in (notes or "").splitlines() if not line.startswith(LEGACY_EXCLUSION_NOTE)]
    return "\n".join(kept).strip() or None


def use_in_public_summary(db: Session, actor: User, run: BiasTestRun, justification: str | None) -> dict:
    """Write the run's tables into the LL144 public summary (§ 5-303): applicants, rates and impact ratios for every
    category, the unknown count and the data source. An excluded category needs the auditor's justification (§ 5-301(d)),
    which goes on its own row, so each use replaces it and the summary's hand-written notes are left as they are."""
    from app.reports.public_summary import current_summary, save_summary, summary_out

    s, e = _system(db, run)
    rows, excluded = summary_rows(run)
    justification = " ".join(str(justification or "").split())
    if excluded and not justification:
        raise Invalid(errors=[{"field": "justification", "message": "Give the justification for excluding categories under the small-category share. The rule requires it in the summary."}])
    if len(justification) > JUSTIFICATION_MAX:
        raise Invalid(errors=[{"field": "justification", "message": f"Keep the justification to {JUSTIFICATION_MAX:,} characters. It is published in the summary as written."}])
    rows = [r | {"justification": justification} if r.get("excluded") else r for r in rows]
    cur = current_summary(db, e)
    body = {"ai_system_id": s.id, "tool_name": (cur.tool_name if cur and cur.tool_name else s.name), "audit_date": run.run_at.date().isoformat(),
            "distribution_date": cur.distribution_date.isoformat() if cur and cur.distribution_date else None, "data_source": run.data_source or (cur.data_source if cur else None),
            "unknown_category_count": run.unknown_count, "impact_ratios": rows, "evidence_file_ids": list(cur.evidence_file_ids or []) if cur else [], "notes": _hand_written(cur.notes if cur else None)}
    save_summary(db, actor, e, body)
    run.public_summary_at, run.public_summary_by = utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="bias_test.public_summary", obj=run, after={"rows": len(rows), "excluded": len(excluded)}, summary=f"Used a bias calculator run in the public summary for {e.audit_ref}")
    return summary_out(db, e)


def record_as_bias_test(db: Session, actor: User, run: BiasTestRun) -> str:
    """A bias test on the client's register system linked to this audited system (existing BiasTest and history entry)."""
    from app.register.history import record_bias_test
    from app.register.models import RegisterSystem

    s, e = _system(db, run)
    if run.bias_test_id:
        raise Conflict("This run is already recorded as a bias test.")
    rs = db.get(RegisterSystem, s.register_system_id) if s.register_system_id else None
    if rs is None or rs.deleted_at is not None:
        raise Conflict("This system is not linked to a system in the client's AI register. Link it on the systems page first.")
    low = lowest(run.results)
    pct = unknown_pct(run)
    below = below_threshold(run.results)
    text = (f"Lowest impact ratio {low['impact_ratio']:.2f} ({low['label']})." if low else "No impact ratio could be calculated.") + \
           f" {run.unknown_count} {'person' if run.unknown_count == 1 else 'people'} in the unknown category, reported in the summary."
    bt, _ = record_bias_test(db, actor, rs, {"tested_on": run.run_at.date().isoformat(), "tester_type": "independent", "tester_name": "Futran Solutions",
                                             "method": f"{stats.METHODS[run.method]} impact ratios (6 RCNY § 5-301), {run.dataset_filename}",
                                             "groups_tested": "Sex; race/ethnicity; intersectional categories", "result": "flagged" if below else "passed", "unknown_share": pct,
                                             "result_text": text, "summary": f"Bias calculator run by Futran on {s.name}"})
    run.bias_test_id = bt.id
    db.flush()
    return bt.id


def set_keep(db: Session, actor: User, run: BiasTestRun, keep: bool) -> BiasTestRun:
    if run.raw_deleted_at is not None:
        raise Conflict("The raw data has already been deleted.")
    before = bool(run.keep_raw_data)
    run.keep_raw_data = bool(keep)
    audit.record(db, actor_id=actor.id, action="bias_test.keep_raw_data", obj=run, before={"keep": before}, after={"keep": run.keep_raw_data},
                 summary=f"{'Kept' if keep else 'Stopped keeping'} the raw applicant data {run.dataset_filename} beyond the retention period")
    return run
