"""Service template library (Release 2 B6, screen G-06).

Each Release 2 engagement type has a service template: sections, checklists, question bank questions (by code, read
through the v0.6.1 §18.1 engine), deliverables, default stages, report template and master price list codes. The Futran
Admin maintains a version while it is a draft and submits it; the Chief Auditor approves it before use (never their own
work); an approved version is fixed and supersedes the version before it. Other workstreams read the approved content
with `approved_version` / `checklist_for` (R6b: Copilot readiness and EU AI Act workspaces).

Seeded content is only what the spec (B6) gives, as drafts awaiting approval: the LL144 applicability map heading and
the candidate-notice and public-summary checklists (from the NYC LL144 rules already in the frameworks seed), the
Copilot readiness checks, the EU AI Act readiness articles and dates, ISO/IEC 42001 clauses 4-10 and Annex A (from the
frameworks seed), the §9.2 vendor due diligence questions, and the M&A due diligence sections. The 8 LL144 cases, the
Annex IV list items and the Agent Assure 15-point items are not in hand and are not invented.
"""
from __future__ import annotations

from datetime import datetime

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.policy.sod import assert_not_self_approval
from app.servicetemplates.models import ServiceTemplate, ServiceTemplateVersion
from app.servicetemplates.types import ENGAGEMENT_TYPES, NEW_ENGAGEMENT_TYPES, ORIGINAL_ENGAGEMENT_TYPES
from app.tenancy.models import User

STATUS_LABELS = {"draft": "Draft", "awaiting_approval": "Awaiting Chief Auditor", "approved": "In use", "superseded": "Superseded"}
LIST_FIELDS = ("sections", "checklists", "question_codes", "deliverables", "default_stages", "catalog_codes", "key_dates")
BUILTIN = {  # the v0.6.1 audits run on the existing question bank and report template
    "initial_assessment": ("Futran AI System Audit", "Template 1.0 and Addendum 5.1a (question bank)", ["A-02", "A-03", "A-06"], "FATF"),
    "ll144_bias_audit": ("LL144 Bias Audit", "Template 1.0, LL144 sections", ["L-01", "L-02", "L-04", "L-05"], "FATF"),
    "annual_review": ("Annual review", "Carries forward the prior engagement (v0.6.1 F16)", ["A-14"], "FATF"),
}


def _seeds_dir():
    from app.reference.jurisdictions import SEEDS

    return SEEDS


def _framework(code: str) -> dict[str, str]:
    data = yaml.safe_load((_seeds_dir() / "frameworks.yaml").read_text())
    fw = next((f for f in data["frameworks"] if f["code"] == code), {"controls": []})
    return {c["code"]: c["title"] for c in fw["controls"]}


# EU AI Act article headings not in the frameworks seed: the regulation's own article titles.
EU_TITLES = {"Art. 11": "Technical documentation", "Art. 12": "Record-keeping", "Art. 15": "Accuracy, robustness and cybersecurity",
             "Art. 17": "Quality management system", "Art. 43": "Conformity assessment",
             "Art. 72": "Post-market monitoring by providers and post-market monitoring plan for high-risk AI systems"}


def _seed_content() -> dict[str, dict]:
    ll = _framework("NYC_LL144")
    eu = {**EU_TITLES, **_framework("EU_AI_ACT")}
    iso = _framework("ISO_42001")
    clauses = [str(n) for n in range(4, 11)]
    annex = [c for c in iso if c.startswith("A.")]

    def eu_item(section: str, art: str) -> dict:
        return {"section": section, "code": art, "text": f"{art} {eu.get(art, '')}".strip(), "evidence": True}

    return {
        "ll144_applicability": {
            "name": "LL144 Applicability (8-case map)", "owner": "FATF", "codes": ["L-03"],
            "sections": [{"code": "MAP", "title": "8-case staffing applicability map (LL144_8Case_Staffing_Applicability_Map.xlsx)",
                          "note": "The eight cases load from FATF's workbook, which is not yet supplied."},
                         {"code": "NOTICE", "title": "Candidate notice: 10 business days", "note": None},
                         {"code": "SUMMARY", "title": "Public summary of the bias audit", "note": None}],
            "checklists": [{"section": "NOTICE", "code": "Admin. Code § 20-871(b)", "text": ll["Admin. Code § 20-871(b)"], "evidence": True},
                           {"section": "NOTICE", "code": "6 RCNY § 5-304", "text": ll["6 RCNY § 5-304"], "evidence": True},
                           {"section": "SUMMARY", "code": "Admin. Code § 20-871(a)(2)", "text": ll["Admin. Code § 20-871(a)(2)"], "evidence": True},
                           {"section": "SUMMARY", "code": "6 RCNY § 5-303", "text": ll["6 RCNY § 5-303"], "evidence": True}]},
        "copilot_readiness": {
            "name": "M365 Copilot Readiness", "owner": "Microsoft practice", "codes": ["X-04"],
            "sections": [{"code": "BLUEPRINT", "title": "Microsoft Pilot / Deploy / Operate oversharing blueprint", "note": "Each check maps to the blueprint."}],
            "checklists": [{"section": "BLUEPRINT", "code": f"CR-{i:02d}", "text": t, "evidence": True} for i, t in enumerate(
                ("Oversharing report", "Sensitivity labels", "DLP for Copilot", "Restricted content discovery", "Audit logging", "Usage policy", "User training"), start=1)]},
        "eu_ai_act_readiness": {
            "name": "EU AI Act Conformity Readiness", "owner": "FRD", "codes": ["X-03", "A-11"],
            "sections": [{"code": "APPLICABILITY", "title": "Applicability", "note": None}, {"code": "ROLE", "title": "Role (provider / deployer)", "note": None},
                         {"code": "CLASSIFICATION", "title": "Classification", "note": None},
                         {"code": "DEPLOYER", "title": "Deployer duties (Art. 4, 14, 26, 27, 50)", "note": None},
                         {"code": "PROVIDER", "title": "Provider duties (Art. 9-15, 17, 43, 72)", "note": None},
                         {"code": "ANNEX_IV", "title": "Annex IV technical documentation list", "note": "The list items are not in the spec and are not seeded."},
                         {"code": "INCIDENTS", "title": "Art. 73 incident reporting", "note": None}],
            "checklists": [eu_item("DEPLOYER", a) for a in ("Art. 4", "Art. 14", "Art. 26", "Art. 27", "Art. 50")]
                          + [eu_item("PROVIDER", f"Art. {n}") for n in (9, 10, 11, 12, 13, 14, 15, 17, 43, 72)]
                          + [eu_item("INCIDENTS", "Art. 73")],
            "key_dates": [{"label": "Annex III high-risk systems", "date": "2027-12-02", "source": "Regulation (EU) 2026/1744"},
                          {"label": "Annex I high-risk systems", "date": "2028-08-02", "source": "Regulation (EU) 2026/1744"}]},
        "iso42001_readiness": {
            "name": "ISO/IEC 42001 Readiness", "owner": "FATF", "codes": ["X-02"],
            "sections": [{"code": "CLAUSES", "title": "Clauses 4-10", "note": None}, {"code": "ANNEX_A", "title": "Annex A controls", "note": None}],
            "checklists": [{"section": "CLAUSES", "code": c, "text": f"Clause {c} {iso[c]}", "evidence": True} for c in clauses if c in iso]
                          + [{"section": "ANNEX_A", "code": c, "text": f"{c} {iso[c]}", "evidence": True} for c in annex]},
        "vendor_due_diligence": {
            "name": "Vendor AI Due Diligence", "owner": "FATF", "codes": ["A-08"],
            "sections": [{"code": "VENDOR", "title": "One section per vendor", "note": "The v0.6.1 §9.2 questions, asked for each vendor."}],
            "questions": [f"9.2.0{i}" for i in range(1, 9)]},
        "ma_due_diligence": {
            "name": "M&A AI Due Diligence", "owner": "FATF", "codes": ["X-05"],
            "sections": [{"code": f"MA-{i}", "title": t, "note": None} for i, t in enumerate(("Target AI inventory", "Regulatory exposure", "Open litigation", "Red-flag summary"), start=1)]},
        # Types the spec names without content: a template row with no version until the owner supplies it.
        "vendor_sponsored_audit": {"name": "Vendor-Sponsored LL144 Audit", "owner": "FATF", "codes": ["L-10"], "empty": True},
        "agent_assurance": {"name": "Agent Assure record", "owner": "FATF", "codes": ["AA-01", "AA-02", "AA-03", "AA-04", "AA-05", "AA-06"], "empty": True,
                            "note": "Waiting on content: FATF supplies the 15-point check."},
        "training_workshop": {"name": "Workshop record", "owner": "FTLC", "codes": ["M-08a", "M-08b"], "empty": True},
        "advisory_retainer": {"name": "Retainer record", "owner": "Sales Manager", "codes": ["M-12", "M-13", "X-01"], "empty": True},
    }


def seed(db: Session) -> str:
    """Create each new type's template and, where the spec gives content, a 0.1 draft. Idempotent: never touches a
    template or version that exists."""
    made = 0
    for t, c in _seed_content().items():
        tpl = db.scalar(select(ServiceTemplate).where(ServiceTemplate.engagement_type == t))
        if tpl is not None:
            continue
        tpl = ServiceTemplate(engagement_type=t, name=c["name"], content_owner=c["owner"], note=c.get("note"))
        db.add(tpl)
        db.flush()
        made += 1
        if c.get("empty"):
            continue
        db.add(ServiceTemplateVersion(template_id=tpl.id, version="0.1", status="draft", sections=c.get("sections", []), checklists=c.get("checklists", []),
                                      question_codes=c.get("questions", []), catalog_codes=c["codes"], key_dates=c.get("key_dates", []), deliverables=[], default_stages=[],
                                      change_note="Starter content from the Release 2 spec (B6)."))
    db.flush()
    return f"{made} service templates added" if made else "already loaded"


# ---------------------------------------------------------------- reads other workstreams use
def template_for(db: Session, engagement_type: str) -> ServiceTemplate | None:
    return db.scalar(select(ServiceTemplate).where(ServiceTemplate.engagement_type == engagement_type))


def versions(db: Session, tpl: ServiceTemplate) -> list[ServiceTemplateVersion]:
    rows = list(db.scalars(select(ServiceTemplateVersion).where(ServiceTemplateVersion.template_id == tpl.id)))
    return sorted(rows, key=lambda v: tuple(int(x) for x in v.version.split(".")), reverse=True)


def latest_version(db: Session, engagement_type: str) -> ServiceTemplateVersion | None:
    tpl = template_for(db, engagement_type)
    vs = versions(db, tpl) if tpl else []
    return vs[0] if vs else None


def approved_version(db: Session, engagement_type: str) -> ServiceTemplateVersion | None:
    """The version in use for an engagement type: approved by the Chief Auditor. None until one is approved."""
    tpl = template_for(db, engagement_type)
    return next((v for v in versions(db, tpl) if v.status == "approved"), None) if tpl else None


def checklist_for(db: Session, engagement_type: str, *, include_draft: bool = False) -> list[dict]:
    """The approved template's checklist items ({section, code, text, evidence}); with include_draft, the latest
    version's when none is approved yet (a workspace can show them marked as not yet approved)."""
    v = approved_version(db, engagement_type) or (latest_version(db, engagement_type) if include_draft else None)
    return [dict(c) for c in (v.checklists if v else [])]


def questions(db: Session, v: ServiceTemplateVersion) -> list[dict]:
    """The version's questions, read from the active question bank (the v0.6.1 §18.1 engine), in the version's order."""
    from app.questionnaire.models import Question
    from app.questionnaire.seed import active_template_version

    tv = active_template_version(db)
    if tv is None or not v.question_codes:
        return []
    by = {q.code: q for q in db.scalars(select(Question).where(Question.template_version_id == tv.id, Question.code.in_(v.question_codes)))}
    return [{"code": c, "label": by[c].label, "type": by[c].type, "options": by[c].options, "section_title": by[c].section_title, "help": by[c].help_text}
            for c in v.question_codes if c in by]


# ---------------------------------------------------------------- maintenance and approval
def _load(db: Session, version_id: str) -> ServiceTemplateVersion:
    v = db.get(ServiceTemplateVersion, version_id)
    if v is None:
        raise NotFound()
    return v


def _clean_list(name: str, value, errors: list) -> list:
    if not isinstance(value, list):
        errors.append({"field": name, "message": "Send a list."})
        return []
    if name in ("deliverables", "default_stages", "catalog_codes", "question_codes"):
        out = [" ".join(str(x).split())[:300] for x in value if str(x).strip()]
        return out
    out = []
    for i, x in enumerate(value):
        if not isinstance(x, dict):
            errors.append({"field": f"{name}.{i}", "message": "Each entry needs its fields."})
            continue
        if name == "sections" and not str(x.get("title") or "").strip():
            errors.append({"field": f"{name}.{i}.title", "message": "Give the section a title."})
        if name == "checklists" and not str(x.get("text") or "").strip():
            errors.append({"field": f"{name}.{i}.text", "message": "Write the checklist item."})
        out.append({k: (v if not isinstance(v, str) else " ".join(v.split())[:1000]) for k, v in x.items()})
    return out


def update_version(db: Session, user: User, version_id: str, data: dict) -> ServiceTemplateVersion:
    v = _load(db, version_id)
    if v.status != "draft":
        raise Conflict("Only a draft changes. Start a new version to change an approved or submitted one.")
    errors: list = []
    before = {k: getattr(v, k) for k in (*LIST_FIELDS, "report_template", "change_note")}
    new = {k: _clean_list(k, data[k], errors) for k in LIST_FIELDS if k in data}
    if "report_template" in data:
        new["report_template"] = " ".join(str(data["report_template"] or "").split())[:120] or None
    if "change_note" in data:
        new["change_note"] = " ".join(str(data["change_note"] or "").split())[:2000] or None
    if errors:
        raise Invalid(errors=errors)
    for k, val in new.items():
        setattr(v, k, val)
    v.updated_by, v.updated_at = user.id, utcnow()
    tpl = db.get(ServiceTemplate, v.template_id)
    changed = [k for k in before if before[k] != getattr(v, k)]
    audit.record(db, actor_id=user.id, action="service_template.edited", object_type="ServiceTemplateVersion", object_id=v.id, organization_id=user.organization_id,
                 before={k: before[k] for k in changed}, after={k: getattr(v, k) for k in changed},
                 summary=f"Edited {tpl.name} {v.version}: {', '.join(changed) or 'no change'}")
    db.flush()
    return v


def new_version(db: Session, user: User, template_id: str) -> ServiceTemplateVersion:
    tpl = db.get(ServiceTemplate, template_id)
    if tpl is None:
        raise NotFound()
    vs = versions(db, tpl)
    if any(x.status in ("draft", "awaiting_approval") for x in vs):
        raise Conflict("This template already has a version in progress. Finish or approve it first.")
    base = vs[0] if vs else None
    major, minor = (int(x) for x in base.version.split(".")) if base else (0, 0)
    v = ServiceTemplateVersion(template_id=tpl.id, version=f"{major}.{minor + 1}", status="draft", created_by=user.id, updated_by=user.id,
                               **{k: list(getattr(base, k) or []) if base else [] for k in LIST_FIELDS}, report_template=base.report_template if base else None,
                               change_note=None)
    db.add(v)
    db.flush()
    audit.record(db, actor_id=user.id, action="service_template.version_started", object_type="ServiceTemplateVersion", object_id=v.id, organization_id=user.organization_id,
                 summary=f"Started {tpl.name} {v.version}{f' from {base.version}' if base else ''}")
    return v


def submit(db: Session, user: User, version_id: str) -> ServiceTemplateVersion:
    v = _load(db, version_id)
    if v.status != "draft":
        raise Conflict("Only a draft can be sent for approval.")
    if not (v.sections or v.checklists or v.question_codes):
        raise Invalid(errors=[{"field": "sections", "message": "Add at least one section, checklist item or question before sending it for approval."}])
    v.status, v.submitted_by, v.submitted_at, v.returned_note = "awaiting_approval", user.id, utcnow(), None
    tpl = db.get(ServiceTemplate, v.template_id)
    audit.record(db, actor_id=user.id, action="service_template.submitted", object_type="ServiceTemplateVersion", object_id=v.id, organization_id=user.organization_id,
                 summary=f"Sent {tpl.name} {v.version} to the Chief Auditor for approval")
    _notify_chief(db, tpl, v, user)
    db.flush()
    return v


def _notify_chief(db: Session, tpl: ServiceTemplate, v: ServiceTemplateVersion, user: User) -> None:
    from app.notifications.service import notify
    from app.tenancy.models import Organization, RoleAssignment

    chiefs = list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).join(Organization, Organization.id == User.organization_id)
                             .where(Organization.type == "futran", RoleAssignment.role == "chief_auditor", RoleAssignment.deleted_at.is_(None), User.status == "active",
                                    User.id != user.id)))
    if chiefs:
        notify(db, chiefs, "service_template_approval", f"Approve {tpl.name} {v.version}",
               f"{user.name} sent the {tpl.name} service template, version {v.version}, for approval. It is not used until you approve it.",
               "/staff/admin/service-templates")


def approve(db: Session, user: User, version_id: str, note: str | None) -> ServiceTemplateVersion:
    v = _load(db, version_id)
    if v.status != "awaiting_approval":
        raise Conflict("Only a version sent for approval can be approved.")
    assert_not_self_approval(user.id, v.created_by, v.updated_by, v.submitted_by)
    tpl = db.get(ServiceTemplate, v.template_id)
    for old in versions(db, tpl):
        if old.status == "approved":
            old.status = "superseded"
    v.status, v.approved_by, v.approved_at, v.approval_note = "approved", user.id, utcnow(), " ".join((note or "").split())[:2000] or None
    audit.record(db, actor_id=user.id, action="service_template.approved", object_type="ServiceTemplateVersion", object_id=v.id, organization_id=user.organization_id,
                 summary=f"Approved {tpl.name} {v.version} for use")
    db.flush()
    return v


def return_version(db: Session, user: User, version_id: str, note: str | None) -> ServiceTemplateVersion:
    v = _load(db, version_id)
    if v.status != "awaiting_approval":
        raise Conflict("Only a version sent for approval can be returned.")
    note = " ".join((note or "").split())
    if len(note) < 5:
        raise Invalid(errors=[{"field": "note", "message": "Say what needs to change."}])
    v.status, v.returned_note = "draft", note[:2000]
    tpl = db.get(ServiceTemplate, v.template_id)
    audit.record(db, actor_id=user.id, action="service_template.returned", object_type="ServiceTemplateVersion", object_id=v.id, organization_id=user.organization_id,
                 summary=f"Returned {tpl.name} {v.version}: {note[:200]}")
    db.flush()
    return v


# ---------------------------------------------------------------- read models
def _name(db: Session, uid: str | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.name if u else None


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def version_out(db: Session, v: ServiceTemplateVersion, *, full: bool = False) -> dict:
    out = {"id": v.id, "template_id": v.template_id, "version": v.version, "status": v.status, "status_label": STATUS_LABELS[v.status],
           "sections_count": len(v.sections or []), "checklists_count": len(v.checklists or []), "questions_count": len(v.question_codes or []),
           "catalog_codes": v.catalog_codes or [], "key_dates": v.key_dates or [], "approved_by": _name(db, v.approved_by), "approved_at": _iso(v.approved_at),
           "submitted_by": _name(db, v.submitted_by), "submitted_at": _iso(v.submitted_at), "returned_note": v.returned_note, "change_note": v.change_note,
           "updated_at": _iso(v.updated_at)}
    if full:
        out.update({k: getattr(v, k) or [] for k in LIST_FIELDS})
        out["report_template"] = v.report_template
        out["approval_note"] = v.approval_note
        out["questions"] = questions(db, v)
    return out


def library(db: Session) -> list[dict]:
    rows = []
    for t, label in ENGAGEMENT_TYPES.items():
        if t in ORIGINAL_ENGAGEMENT_TYPES:
            name, detail, codes, owner = BUILTIN[t]
            rows.append({"engagement_type": t, "type_label": label, "builtin": True, "template": {"id": None, "name": name, "content_owner": owner, "note": detail},
                         "latest": None, "in_use": None, "catalog_codes": codes, "status_label": "In use (v0.6.1)", "versions": []})
            continue
        tpl = template_for(db, t)
        vs = versions(db, tpl) if tpl else []
        latest = vs[0] if vs else None
        in_use = next((v for v in vs if v.status == "approved"), None)
        status = ("Not started" if tpl is None or (latest is None and not tpl.note) else "Waiting on content" if latest is None else
                  "In use" if latest.status == "approved" else STATUS_LABELS[latest.status])
        rows.append({"engagement_type": t, "type_label": label, "builtin": False,
                     "template": {"id": tpl.id, "name": tpl.name, "content_owner": tpl.content_owner, "note": tpl.note} if tpl else None,
                     "latest": version_out(db, latest) if latest else None, "in_use": version_out(db, in_use) if in_use else None,
                     "catalog_codes": (latest.catalog_codes if latest else (_seed_content().get(t, {}).get("codes") or [])), "status_label": status,
                     "versions": [version_out(db, v) for v in vs]})
    return rows


__all__ = ["NEW_ENGAGEMENT_TYPES", "approved_version", "checklist_for", "latest_version", "questions", "seed", "template_for"]
