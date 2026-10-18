"""The audit report (template §12–13, spec §18.7–18.8): content, versions, declarations, sign-off 7 and the client
acknowledgement. The public summary (sign-off 8) is in `public_summary`."""
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid
from app.engagements.models import ClientRequirement, Engagement
from app.findings.models import Finding
from app.reports.models import CLIENT_DECLARATIONS, FUTRAN_DECLARATIONS, PRIORITIES, VERSIONS, Declaration, Report, ReportNarrative, RoadmapItem
from app.tenancy.models import Department, Organization, User

VERSION_LABEL = {v: f"{label} {v}" for v, label in VERSIONS.items()}
STATUS_TEXT = {"v0.1": "Draft for internal review", "v0.2": "Lead review", "v1.0": "Draft issued to the client", "v1.1": "Final"}
SEVERITY_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "observation": "Observation"}
GROUP_LABEL = {"critical": "Critical findings", "high": "High findings", "medium": "Medium findings", "low": "Low findings", "observation": "Observations"}
DUE_TEXT = {"critical": "30 days", "high": "60–90 days", "medium": "6 months", "low": "Next annual cycle", "observation": "12-month roadmap"}
RATING_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
BUILT_BY = {"in_house": "In house", "vendor": "Vendor", "open_source_customized": "Open source, customized", "hybrid": "Hybrid"}
ACK_NOTICE = "Signing confirms you have received and read this report. It does not mean you agree with every finding."
COMMITMENT_TEXT = {"plan": "The client has reviewed the findings and agrees to develop a remediation plan within 30 days.",
                   "disputes": "The client disputes the following findings: {refs}."}
STRENGTHS_MESSAGE = "Add the greatest strengths observed. Always include genuine positives."

# Task 31 adds management responses to the final report through this hook: fn(db, engagement, context) -> None
CONTEXT_HOOKS: list[Callable[[Session, Engagement, dict], None]] = []


@dataclass
class ReportContent:
    version: str
    markdown: str
    content_hash: str
    data: dict


# ---- people
def team_holders(db: Session, e: Engagement, role: str) -> list[User]:
    from app.findings.service import team_role_holders

    return team_role_holders(db, e, role)


def required_declarations(db: Session, e: Engagement) -> list[str]:
    """Lead Auditor and Engagement Manager always; the Quality Reviewer only when one is on the team (§18.8)."""
    kinds = ["lead_auditor", "engagement_manager"]
    if team_holders(db, e, "qa_reviewer"):
        kinds.append("quality_reviewer")
    return kinds


DECLARATION_ROLE = {"lead_auditor": "chief_auditor", "engagement_manager": "engagement_manager", "quality_reviewer": "qa_reviewer"}


# ---- templates
def _template_body(db: Session, key: str) -> tuple[str, str]:
    from app.reference.templates import TEMPLATE_DIR
    from app.reference.models import DocumentTemplate

    t = db.scalar(select(DocumentTemplate).where(DocumentTemplate.key == key, DocumentTemplate.active.is_(True)))
    if t is not None:
        return t.body, f"v{t.version}"
    return (TEMPLATE_DIR / f"{key}.md.j2").read_text(), "v1"


def render(db: Session, key: str, context: dict) -> tuple[str, str]:
    from app.reference.templates import render_string

    body, version = _template_body(db, key)
    return render_string(body, context), version


def _names(db: Session, e: Engagement) -> dict:
    from app.initiation.context import TYPE_LABELS, fmt
    from app.engagements.wizard import FRAMEWORKS

    org = db.get(Organization, e.client_id)
    period = " to ".join(x for x in (fmt(e.period_start), fmt(e.period_end)) if x)
    return {"client": {"name": org.name, "industry": org.industry},
            "engagement": {"audit_ref": e.audit_ref, "type_label": TYPE_LABELS.get(e.type, e.type), "period": period, "methodology_version": e.methodology_version,
                           "frameworks": ", ".join(FRAMEWORKS.get(f, f) for f in e.frameworks or [])}}


def declaration_text(db: Session, e: Engagement, kind: str) -> tuple[str, str]:
    key = "lead_auditor_declaration" if kind == "lead_auditor" else "client_declaration"
    try:
        return render(db, key, _names(db, e))
    except Exception:  # an admin-edited template that no longer renders: fall back to the template wording
        n = _names(db, e)
        if kind == "lead_auditor":
            return f"I confirm that this audit was conducted in accordance with {e.methodology_version} and that the findings accurately reflect the evidence gathered during the engagement.", "default"
        return (f"By signing, I confirm that {n['client']['name']} has received the Futran Solutions AI Governance Audit Report ref {e.audit_ref} "
                "and that the information provided during the audit was accurate to the best of my knowledge."), "default"


# ---- narrative and roadmap (§12.1, §12.2)
def narrative(db: Session, e: Engagement) -> ReportNarrative | None:
    return db.scalar(select(ReportNarrative).where(ReportNarrative.engagement_id == e.id, ReportNarrative.deleted_at.is_(None)))


def assert_editable(db: Session, e: Engagement) -> None:
    if latest(db, e, "v1.0", released=True) is not None:
        raise Conflict("The client draft has been released. The executive summary and roadmap can no longer change.")


def save_narrative(db: Session, actor: User, e: Engagement, data: dict) -> ReportNarrative:
    assert_editable(db, e)
    n = narrative(db, e)
    if n is None:
        n = ReportNarrative(organization_id=e.client_id, engagement_id=e.id, created_by=actor.id)
        db.add(n)
    fid = data.get("most_significant_finding_id") or None
    if fid is not None:
        f = db.get(Finding, fid) if isinstance(fid, str) else None
        if f is None or f.engagement_id != e.id or f.deleted_at is not None:
            raise Invalid(errors=[{"field": "most_significant_finding_id", "message": "Choose a finding from this engagement."}])
    before = {"strengths": n.strengths}
    n.most_significant_finding_id = fid
    for key, limit in (("most_significant_text", 6000), ("strengths", 6000), ("immediate_actions", 6000), ("narrative", 8000)):
        setattr(n, key, (str(data.get(key) or "").strip()[:limit]) or None)
    n.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="report.summary", obj=n, before=before, after={"strengths": n.strengths}, summary=f"Updated the executive summary for {e.audit_ref}")
    return n


def roadmap(db: Session, e: Engagement) -> list[RoadmapItem]:
    return list(db.scalars(select(RoadmapItem).where(RoadmapItem.engagement_id == e.id, RoadmapItem.deleted_at.is_(None)).order_by(RoadmapItem.ref)))


def _clean_roadmap(db: Session, e: Engagement, data: dict) -> dict:
    from datetime import date

    errs, out = [], {}
    action = " ".join(str(data.get("action") or "").split())
    if not action:
        errs.append({"field": "action", "message": "Describe the recommended action."})
    out["action"] = action[:2000]
    out["owner"] = (" ".join(str(data.get("owner") or "").split())[:160]) or None
    if data.get("priority") not in PRIORITIES:
        errs.append({"field": "priority", "message": "Choose critical, high, medium or low."})
    out["priority"] = data.get("priority")
    td = data.get("target_date")
    try:
        out["target_date"] = date.fromisoformat(td) if td else None
    except (TypeError, ValueError):
        errs.append({"field": "target_date", "message": "Enter a date."})
    out["how_futran_can_help"] = (str(data.get("how_futran_can_help") or "").strip()[:2000]) or None
    ids = data.get("finding_ids") or []
    fs = [db.get(Finding, i) for i in ids] if isinstance(ids, list) and all(isinstance(i, str) for i in ids) else None
    if fs is None or any(f is None or f.engagement_id != e.id or f.deleted_at is not None for f in fs):
        errs.append({"field": "finding_ids", "message": "Choose findings from this engagement."})
    else:
        out["finding_ids"] = list(dict.fromkeys(ids))
    if errs:
        raise Invalid(errors=errs)
    return out


def add_roadmap_item(db: Session, actor: User, e: Engagement, data: dict) -> RoadmapItem:
    assert_editable(db, e)
    v = _clean_roadmap(db, e, data)
    used = list(db.scalars(select(RoadmapItem.ref).where(RoadmapItem.engagement_id == e.id)))  # deleted refs are not reused
    n = max((int(r[2:]) for r in used if r[2:].isdigit()), default=0) + 1
    item = RoadmapItem(organization_id=e.client_id, engagement_id=e.id, ref=f"R-{n:02d}", created_by=actor.id, **v)
    db.add(item)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise Conflict("Someone added a roadmap item at the same time. Try again.") from None
    audit.record(db, actor_id=actor.id, action="roadmap.add", obj=item, after={"ref": item.ref, "action": item.action[:200]}, summary=f"Added roadmap item {item.ref}")
    return item


def update_roadmap_item(db: Session, actor: User, item: RoadmapItem, data: dict) -> RoadmapItem:
    e = db.get(Engagement, item.engagement_id)
    assert_editable(db, e)
    v = _clean_roadmap(db, e, data)
    for k, val in v.items():
        setattr(item, k, val)
    item.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="roadmap.edit", obj=item, after={"action": item.action[:200]}, summary=f"Edited roadmap item {item.ref}")
    return item


def delete_roadmap_item(db: Session, actor: User, item: RoadmapItem) -> None:
    assert_editable(db, db.get(Engagement, item.engagement_id))
    item.deleted_at = utcnow()
    audit.record(db, actor_id=actor.id, action="roadmap.delete", obj=item, summary=f"Removed roadmap item {item.ref}")


def roadmap_out(db: Session, r: RoadmapItem) -> dict:
    refs = [f.ref for f in (db.get(Finding, i) for i in r.finding_ids or []) if f is not None]
    return {"id": r.id, "ref": r.ref, "action": r.action, "owner": r.owner, "priority": r.priority, "target_date": r.target_date.isoformat() if r.target_date else None,
            "how_futran_can_help": r.how_futran_can_help, "finding_ids": r.finding_ids or [], "finding_refs": refs}


# ---- content
def _content_data(db: Session, e: Engagement) -> dict:
    """Everything the report states, with no version label and no signatures. Its hash tells whether a signed version
    still matches what would be generated now."""
    from app.findings.service import findings_for
    from app.inventory.models import UseCase
    from app.laws.models import Regulation
    from app.reference.frameworks import control_label
    from app.reference.models import Jurisdiction
    from app.scoring.service import engagement_rollup, latest as latest_score, methodology
    from app.systems.models import Vendor
    from app.systems.service import systems_for

    m = methodology(db)
    sys_names = {}
    systems = []
    for s in systems_for(db, e):
        sys_names[s.id] = f"{s.reference_id} {s.name}"
        row = latest_score(db, s)
        dept = db.get(Department, s.department_id) if s.department_id else None
        vendor = db.get(Vendor, s.vendor_id) if s.vendor_id else None
        ucs = [u.name for u in (db.get(UseCase, i) for i in s.use_case_ids or []) if u is not None]
        systems.append({"ref": s.reference_id, "name": s.name, "built_by": BUILT_BY.get(s.built_by or "", "Not recorded"), "vendor": vendor.legal_name if vendor else "",
                        "department": dept.name if dept else "", "use_cases": ", ".join(ucs),
                        "inherent": row.inherent if row else None, "maturity": row.maturity if row else None, "residual": row.residual if row else None,
                        "rating": RATING_LABEL.get(row.final_rating or "", "Not rated") if row else "Not scored"})
    findings = []
    for f in findings_for(db, e):
        if f.status != "approved":
            continue
        findings.append({"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "severity_label": SEVERITY_LABEL[f.severity], "system": sys_names.get(f.ai_system_id or "", ""),
                         "owner": f.proposed_owner or "", "due": DUE_TEXT[f.severity], "description": f.description, "remediation": f.recommended_remediation,
                         "section": f.template_section, "controls": ", ".join(control_label(db, r) for r in f.control_refs or [])})
    counts = {k: sum(1 for f in findings if f["severity"] == k) for k in SEVERITY_LABEL}
    counts["total"] = len(findings)
    sc = engagement_rollup(db, e)
    n = narrative(db, e)
    top = next((f for f in findings if n and f["id"] == n.most_significant_finding_id), None)
    laws = []
    for r in db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.in_scope.is_(True), ClientRequirement.deleted_at.is_(None)).order_by(ClientRequirement.created_at)):
        reg = db.get(Regulation, r.regulation_id) if r.regulation_id else None
        j = db.get(Jurisdiction, reg.jurisdiction_id) if reg else None
        laws.append({"name": reg.short_name if reg else (r.free_text or ""), "jurisdiction": j.name if j else "", "citation": (reg.citation if reg else "") or ""})
    data = {
        **_names(db, e),
        "lead_auditor": ", ".join(u.name for u in team_holders(db, e, "chief_auditor")),
        "overall_rating": RATING_LABEL.get(sc.overall_rating or "", "Not rated"),
        "overall_maturity": sc.overall_maturity if sc.overall_maturity is not None else "Not scored",
        "counts": counts,
        "summary": {"most_significant_ref": top["ref"] if top else None, "most_significant_title": top["title"] if top else None,
                    "most_significant_text": n.most_significant_text if n else None, "strengths": n.strengths if n else None,
                    "immediate_actions": n.immediate_actions if n else None, "critical": [{"ref": f["ref"], "title": f["title"]} for f in findings if f["severity"] == "critical"]},
        "findings": findings,
        "findings_by_severity": [{"label": GROUP_LABEL[k], "items": [f for f in findings if f["severity"] == k]} for k in SEVERITY_LABEL if counts[k]],
        "systems": systems,
        "scorecard": {"domains": [{"label": label, "score": sc.domain_scores.get(key, "Not scored")} for key, label in m.domains.items()], "narrative": n.narrative if n else None},
        "roadmap": [{"ref": r.ref, "action": r.action, "owner": r.owner or "", "priority": SEVERITY_LABEL[r.priority], "target_date": r.target_date.isoformat() if r.target_date else "",
                     "how_futran_can_help": r.how_futran_can_help or ""} for r in roadmap(db, e)],
        "laws": laws,
    }
    for hook in CONTEXT_HOOKS:
        hook(db, e, data)
    return data


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _declarations_block(db: Session, e: Engagement, signed_on: Report | None, final: Report | None) -> dict:
    from app.initiation.context import fmt

    text, _ = declaration_text(db, e, "lead_auditor")
    rows = {d.kind: d for d in (declarations_for(db, signed_on) if signed_on else [])}
    kinds = required_declarations(db, e) if signed_on is None else [k for k in FUTRAN_DECLARATIONS if k in rows or k in required_declarations(db, e)]
    futran = [{"label": FUTRAN_DECLARATIONS[k], "name": rows[k].typed_name if k in rows else "", "signed_at": fmt(rows[k].signed_at.date()) if k in rows else "Not signed"} for k in kinds]
    client = None
    acks = {d.kind: d for d in (declarations_for(db, final) if final else [])}
    if "client_acknowledgement" in acks:
        a, c = acks["client_acknowledgement"], acks.get("client_remediation_commitment")
        client = {"name": a.typed_name, "title": a.title or "", "signed_at": fmt(a.signed_at.date()), "commitment": c.text if c else ""}
    return {"lead_auditor_text": text, "futran": futran, "no_qa": "quality_reviewer" not in kinds, "client_text": declaration_text(db, e, "client_acknowledgement")[0], "client": client}


def build_report(db: Session, e: Engagement, version: str, *, signed_on: Report | None = None, final: Report | None = None) -> ReportContent:
    """The report as it stands. From the lead review version on, the executive summary must name genuine strengths."""
    from app.initiation.context import fmt
    from app.core.clock import today

    if version not in VERSIONS:
        raise Invalid(errors=[{"field": "version", "message": "Choose v0.1, v0.2, v1.0 or v1.1."}])
    data = _content_data(db, e)
    if version != "v0.1" and not (data["summary"]["strengths"] or "").strip():
        raise Invalid("The executive summary is not complete.", [{"field": "strengths", "message": STRENGTHS_MESSAGE}])
    content_hash = _hash(data)
    ctx = {**data, "report": {"version": version, "version_label": VERSION_LABEL[version], "status_text": STATUS_TEXT[version], "date": fmt(today())},
           "declarations": _declarations_block(db, e, signed_on, final)}
    md, _ = render(db, "report", ctx)
    return ReportContent(version=version, markdown=md, content_hash=content_hash, data=data)


# ---- versions
def reports_for(db: Session, e: Engagement) -> list[Report]:
    return list(db.scalars(select(Report).where(Report.engagement_id == e.id, Report.deleted_at.is_(None)).order_by(Report.created_at.desc())))


def latest(db: Session, e: Engagement, version: str, *, released: bool = False) -> Report | None:
    stmt = select(Report).where(Report.engagement_id == e.id, Report.version == version, Report.deleted_at.is_(None))
    if released:
        stmt = stmt.where(Report.released_to_client_at.is_not(None))
    return db.scalar(stmt.order_by(Report.created_at.desc()).limit(1))


def _store(db: Session, settings, actor: User, e: Engagement, content: ReportContent, **fields) -> Report:
    from app.documents.docx import to_docx
    from app.documents.pdf import to_pdf
    from app.files.service import upload

    r = Report(organization_id=e.client_id, engagement_id=e.id, version=content.version, body_md=content.markdown, content_hash=content.content_hash, created_by=actor.id, **fields)
    db.add(r)
    db.flush()
    title = f"AI governance audit report {content.version}"
    base = f"{e.audit_ref} {title}".replace("/", "-")
    common = {"organization_id": e.client_id, "engagement_id": e.id, "linked_type": "report", "linked_id": r.id}
    meta = {"audit_ref": e.audit_ref}
    r.docx_file_id = upload(db, settings, actor, data=to_docx(content.markdown, title, meta), filename=f"{base}.docx", content_type=None, **common).id
    r.pdf_file_id = upload(db, settings, actor, data=to_pdf(content.markdown, title, meta), filename=f"{base}.pdf", content_type=None, **common).id
    db.flush()
    return r


def generate(db: Session, settings, actor: User, e: Engagement, version: str) -> Report:
    """Draft v0.1 at any time from fieldwork on; lead review v0.2 once sign-off 5 has locked the findings."""
    from app.signoffs.service import is_approved

    if version not in ("v0.1", "v0.2"):
        raise Invalid(errors=[{"field": "version", "message": "Generate the draft (v0.1) or the lead review version (v0.2). v1.0 and v1.1 are issued, not generated."}])
    if e.stage < 5:
        raise Conflict("The report is drafted from fieldwork on.")
    if version == "v0.2" and not is_approved(db, e, 5):
        raise Conflict("Sign-off 5 (final risk tiers and findings) must be approved before the lead review version.")
    if latest(db, e, "v1.0", released=True) is not None:
        raise Conflict("The client draft has been released. The next version is the final report.")
    r = _store(db, settings, actor, e, build_report(db, e, version))
    audit.record(db, actor_id=actor.id, action="report.generate", obj=r, after={"version": version, "content_hash": r.content_hash}, summary=f"Generated the {VERSION_LABEL[version]} report for {e.audit_ref}")
    return r


# ---- declarations (§18.8)
def declarations_for(db: Session, r: Report) -> list[Declaration]:
    return list(db.scalars(select(Declaration).where(Declaration.report_id == r.id, Declaration.deleted_at.is_(None)).order_by(Declaration.signed_at)))


def _norm(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def _check_name(user: User, typed_name: str) -> str:
    if _norm(typed_name) != _norm(user.name):
        raise Invalid("Type your name exactly as it appears on your account.", [{"field": "typed_name", "message": f"Type your full name: {user.name}."}])
    return " ".join(typed_name.split())


def _record(db: Session, actor: User, e: Engagement, r: Report, kind: str, typed_name: str, text: str, text_version: str | None, request=None, **extra) -> Declaration:
    d = Declaration(organization_id=e.client_id, engagement_id=e.id, report_id=r.id, kind=kind, user_id=actor.id, typed_name=typed_name, title=actor.job_title, text=text,
                    text_version=text_version, signed_at=utcnow(), ip=request.client.host if request is not None and request.client else None,
                    document_sha256=hashlib.sha256(r.body_md.encode()).hexdigest(), **extra)
    db.add(d)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise Conflict("This declaration has already been signed.") from None
    return d


def declare(db: Session, actor: User, r: Report, kind: str, typed_name: str, request=None) -> Declaration:
    """A Futran declaration on the lead review version. Each is signed by the engagement's holder of that role, and no one
    signs twice on the same report."""
    e = db.get(Engagement, r.engagement_id)
    if kind not in FUTRAN_DECLARATIONS:
        raise Invalid(errors=[{"field": "kind", "message": "Choose the Lead Auditor, Engagement Manager or Quality Reviewer declaration."}])
    if r.version != "v0.2" or r.id != getattr(latest(db, e, "v0.2"), "id", None):
        raise Conflict("Declarations are signed on the latest lead review version (v0.2).")
    if latest(db, e, "v1.0", released=True) is not None:
        raise Conflict("The client draft has been released.")
    role = DECLARATION_ROLE[kind]
    if actor.id not in {u.id for u in team_holders(db, e, role)}:
        raise Forbidden(f"Only the engagement's {FUTRAN_DECLARATIONS[kind]} signs this declaration.")
    rows = {d.kind: d for d in declarations_for(db, r)}
    if kind in rows:
        raise Conflict("This declaration has already been signed.")
    mine = next((d for d in rows.values() if d.user_id == actor.id), None)
    if mine is not None:
        raise Conflict(f"You have already signed this report as {FUTRAN_DECLARATIONS[mine.kind]}. Another person signs as {FUTRAN_DECLARATIONS[kind]}.")
    name = _check_name(actor, typed_name)
    text, version = declaration_text(db, e, "lead_auditor") if kind == "lead_auditor" else (f"{FUTRAN_DECLARATIONS[kind]} sign-off of the report {VERSION_LABEL[r.version]}.", None)
    d = _record(db, actor, e, r, kind, name, text, version, request)
    audit.record(db, actor_id=actor.id, action="report.declaration", obj=d, after={"kind": kind, "report": r.version, "sha256": d.document_sha256}, summary=f"{actor.name} signed the {FUTRAN_DECLARATIONS[kind]} declaration on {e.audit_ref} {r.version}")
    return d


# ---- v1.0: the client draft
def release_unmet(db: Session, e: Engagement) -> list[str]:
    from app.signoffs.service import is_approved

    if latest(db, e, "v1.0", released=True) is not None:
        return ["The client draft has already been released."]
    out = [] if is_approved(db, e, 5) else ["Sign-off 5 (final risk tiers and findings) is not approved yet."]
    v02 = latest(db, e, "v0.2")
    if v02 is None:
        return out + ["Generate the lead review version (v0.2) and have it signed."]
    rows = {d.kind for d in declarations_for(db, v02)}
    for kind in required_declarations(db, e):
        if kind not in rows:
            out.append(f"The {FUTRAN_DECLARATIONS[kind]} declaration is not signed.")
    try:
        now = build_report(db, e, "v0.2").content_hash
    except Invalid as exc:
        return out + [m["message"] for m in exc.errors]
    if now != v02.content_hash:
        out.append("The report has changed since the lead review version was signed. Generate v0.2 again and sign it.")
    return out


def release_client_draft(db: Session, settings, actor: User, e: Engagement) -> Report:
    """v1.0 goes to the client once sign-off 5 and the Futran declarations are complete (§18.8)."""
    from app.engagements.gates import advance_if_ready
    from app.notifications.service import notify
    from app.tenancy.people import active_holders

    unmet = release_unmet(db, e)
    if unmet:
        raise Conflict("The client draft can't be released yet.", [{"field": "release", "message": m} for m in unmet])
    v02 = latest(db, e, "v0.2")
    r = _store(db, settings, actor, e, build_report(db, e, "v1.0", signed_on=v02), status="released", based_on_id=v02.id, released_to_client_at=utcnow(), released_by=actor.id)
    audit.record(db, actor_id=actor.id, action="report.release", obj=r, after={"version": "v1.0", "based_on": v02.id}, summary=f"Released the client draft report (v1.0) for {e.audit_ref}")
    org = db.get(Organization, e.client_id)
    notify(db, active_holders(db, org, "caico") + active_holders(db, org, "exec_sponsor"), "report_released", f"{e.audit_ref}: the draft audit report is ready",
           "Read the findings and prepare your management responses.", "/report", engagement=e, settings=settings)
    advance_if_ready(db, actor, e)
    return r


# ---- v1.1: the final report and sign-off 7
def final_unmet(db: Session, e: Engagement, _scope=None) -> list[str]:
    out = []
    if e.stage < 8:
        out.append("The final report is signed at stage 8, after sign-off 6 (management responses).")
    if latest(db, e, "v1.0", released=True) is None:
        out.append("Release the client draft (v1.0) first.")
    v11 = latest(db, e, "v1.1")
    if v11 is None or v11.status != "draft":
        out.append("Prepare the final report (v1.1) first.")
    return out


def final_statement(db: Session, e: Engagement) -> str | None:
    v11 = latest(db, e, "v1.1")
    if v11 is None:
        return None
    return f"Final report {e.audit_ref} {VERSION_LABEL['v1.1']}. Document SHA-256 {hashlib.sha256(v11.body_md.encode()).hexdigest()}."


def prepare_final(db: Session, settings, actor, e: Engagement):
    """Generate v1.1 and send sign-off 7 to the Chief Auditor."""
    from app.signoffs.service import current, submit_signoff

    so = current(db, e, 7)
    if so is not None and so.status in ("pending", "in_review", "approved"):
        raise Conflict("Sign-off 7 is already " + ("approved." if so.status == "approved" else "waiting for the Chief Auditor."))
    unmet = [m for m in final_unmet(db, e) if "Prepare the final" not in m]
    if unmet:
        raise Conflict("The final report can't be prepared yet.", [{"field": "final", "message": m} for m in unmet])
    v10 = latest(db, e, "v1.0", released=True)
    v02 = db.get(Report, v10.based_on_id) if v10.based_on_id else None
    r = _store(db, settings, actor.user, e, build_report(db, e, "v1.1", signed_on=v02), status="draft", based_on_id=v02.id if v02 else None)
    audit.record(db, actor_id=actor.id, action="report.generate", obj=r, after={"version": "v1.1"}, summary=f"Prepared the final report (v1.1) for {e.audit_ref}")
    so = submit_signoff(db, settings, actor, e, 7, statement=final_statement(db, e))
    return r, so


def issue_final(db: Session, settings, actor, so) -> Report:
    """Sign-off 7 approved: v1.1 is final and goes to the client, who acknowledges receipt."""
    from app.notifications.service import notify
    from app.tenancy.people import active_holders

    e = db.get(Engagement, so.engagement_id)
    r = latest(db, e, "v1.1")
    if r is None or so.statement != final_statement(db, e):
        raise Conflict("The final report changed after it was sent for signature. Prepare it again.")
    r.status, r.signed_by, r.signed_at, r.released_to_client_at, r.released_by = "final", actor.id, utcnow(), utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="report.final", obj=r, after={"version": "v1.1", "signed_by": actor.id}, summary=f"Issued the final report (v1.1) for {e.audit_ref}")
    org = db.get(Organization, e.client_id)
    notify(db, active_holders(db, org, "caico") + active_holders(db, org, "exec_sponsor"), "sign_off_awaiting", f"{e.audit_ref}: please acknowledge the final audit report",
           ACK_NOTICE, "/report", engagement=e, settings=settings)
    return r


# ---- client acknowledgement and remediation commitment (§13.2)
def acknowledgement_unmet(db: Session, e: Engagement) -> list[str]:
    r = latest(db, e, "v1.1")
    if r is None or r.status != "final":
        return ["The final report has not been issued yet."]
    if any(d.kind == "client_acknowledgement" for d in declarations_for(db, r)):
        return ["The final report has already been acknowledged."]
    return []


def acknowledge(db: Session, settings, actor, e: Engagement, typed_name: str, commitment: str | None, disputed_refs: list | None, request=None) -> Report:
    from app.engagements.gates import advance_if_ready
    from app.findings.service import findings_for

    unmet = acknowledgement_unmet(db, e)
    if unmet:
        raise Conflict(unmet[0])
    errs = []
    if commitment not in COMMITMENT_TEXT:
        errs.append({"field": "commitment", "message": "Choose whether you will develop a remediation plan or dispute findings."})
    approved = {f.ref for f in findings_for(db, e) if f.status == "approved"}
    refs = list(dict.fromkeys(str(x).strip().upper() for x in (disputed_refs or []) if str(x).strip()))
    if commitment == "disputes" and (not refs or any(x not in approved for x in refs)):
        errs.append({"field": "disputed_refs", "message": "List the findings you dispute, using their references (for example F-001)."})
    if errs:
        raise Invalid(errors=errs)
    name = _check_name(actor.user, typed_name)
    r = latest(db, e, "v1.1")
    text, version = declaration_text(db, e, "client_acknowledgement")
    a = _record(db, actor.user, e, r, "client_acknowledgement", name, text, version, request)
    ctext = COMMITMENT_TEXT[commitment].format(refs=", ".join(refs))
    _record(db, actor.user, e, r, "client_remediation_commitment", name, ctext, None, request, commitment=commitment, disputed_finding_refs=refs if commitment == "disputes" else [])
    audit.record(db, actor_id=actor.id, action="report.acknowledged", obj=a, after={"commitment": commitment, "disputed": refs}, summary=f"{actor.user.name} acknowledged the final report for {e.audit_ref}")
    advance_if_ready(db, actor.user, e)
    return r


def declaration_out(d: Declaration) -> dict:
    return {"kind": d.kind, "label": {**FUTRAN_DECLARATIONS, **CLIENT_DECLARATIONS}.get(d.kind, d.kind), "signed_by": d.typed_name, "title": d.title,
            "signed_at": d.signed_at.isoformat(), "text": d.text, "commitment": d.commitment, "disputed_refs": d.disputed_finding_refs or []}


def report_out(db: Session, r: Report, futran: bool) -> dict:
    out = {"id": r.id, "version": r.version, "version_label": VERSION_LABEL[r.version], "status": r.status, "created_at": r.created_at.isoformat(),
           "docx_file_id": r.docx_file_id, "pdf_file_id": r.pdf_file_id, "released_to_client_at": r.released_to_client_at.isoformat() if r.released_to_client_at else None,
           "signed_at": r.signed_at.isoformat() if r.signed_at else None, "declarations": [declaration_out(d) for d in declarations_for(db, r)]}
    if futran:
        out["content_hash"] = r.content_hash
    return out


# ---- public summary (sign-off 8): when a law in scope needs one
LL144 = re.compile(r"\b(?:LL\s*144|local law (?:no\.?\s*)?144)\b", re.I)


def requires_public_summary(db: Session, e: Engagement) -> bool:
    """NYC LL144, or any law in scope flagged public_summary, needs the published bias audit summary."""
    from app.laws.models import Regulation

    if e.type == "ll144_bias_audit":
        return True
    rows = db.execute(select(Regulation.public_summary, Regulation.short_name, Regulation.citation).join(ClientRequirement, ClientRequirement.regulation_id == Regulation.id)
                      .where(ClientRequirement.engagement_id == e.id, ClientRequirement.in_scope.is_(True), ClientRequirement.deleted_at.is_(None)))
    return any(flag or LL144.search(f"{name or ''} {cite or ''}") for flag, name, cite in rows)
