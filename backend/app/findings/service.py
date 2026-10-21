"""Findings (spec §9.6, §18.6): drafting by auditors. Review and approval: see `review` below (Task 29)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid
from app.engagements.models import Engagement
from app.findings.models import SEVERITIES, Finding
from app.inventory.models import UseCase
from app.scoring.scale import RESPONSE_DAYS as DEFAULT_DUE_DAYS  # response time by severity: one scale for the platform
from app.systems.models import AISystem
from app.tenancy.models import User

EDITABLE = ("draft", "returned")


def findings_for(db: Session, e: Engagement) -> list[Finding]:
    return list(db.scalars(select(Finding).where(Finding.engagement_id == e.id, Finding.deleted_at.is_(None)).order_by(Finding.ref)))


def _question_codes(db: Session) -> set[str]:
    from app.questionnaire.models import Question
    from app.questionnaire.seed import active_template_version

    tv = active_template_version(db)
    return set(db.scalars(select(Question.code).where(Question.template_version_id == tv.id))) if tv else set()


def _clean(db: Session, e: Engagement, data: dict, partial: bool) -> dict:
    out: dict = {}
    errs = []

    def text(key: str, limit: int, required: bool = False):
        if key in data or not partial:
            v = " ".join(str(data.get(key) or "").split()) if key == "title" else str(data.get(key) or "").strip()
            if required and not v:
                errs.append({"field": key, "message": "Enter a title." if key == "title" else "This is required."})
            out[key] = v[:limit] or None

    text("title", 300, required=True)
    text("description", 20000)
    text("recommended_remediation", 8000)
    text("proposed_owner", 160)
    text("template_section", 8)
    if "severity" in data or not partial:
        if data.get("severity") not in SEVERITIES:
            errs.append({"field": "severity", "message": "Choose critical, high, medium, low or observation."})
        else:
            out["severity"] = data["severity"]
    if "control_refs" in data:
        refs = data.get("control_refs")
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            errs.append({"field": "control_refs", "message": "Choose the controls this finding relates to."})
        else:
            out["control_refs"] = list(dict.fromkeys(r.strip()[:200] for r in refs if r.strip()))[:20]
    if "use_case_ids" in data:
        ids = data.get("use_case_ids")
        ok = isinstance(ids, list) and all(isinstance(i, str) for i in ids)
        ucs = [db.get(UseCase, i) for i in ids] if ok else []
        if not ok or any(u is None or u.engagement_id != e.id or u.deleted_at is not None for u in ucs):
            errs.append({"field": "use_case_ids", "message": "Choose use cases from this engagement."})
        else:
            out["use_case_ids"] = list(dict.fromkeys(ids))
    if "ai_system_id" in data:
        sid = data.get("ai_system_id")
        s = db.get(AISystem, sid) if isinstance(sid, str) and sid else None
        if sid and (s is None or s.engagement_id != e.id or s.deleted_at is not None):
            errs.append({"field": "ai_system_id", "message": "Choose a system from this engagement."})
        else:
            out["ai_system_id"] = s.id if s else None
    if "source_question_ids" in data:
        codes = data.get("source_question_ids")
        known = _question_codes(db)
        if not isinstance(codes, list) or not all(isinstance(c, str) and c.strip() in known for c in codes):
            errs.append({"field": "source_question_ids", "message": "Choose questions from the audit questionnaire."})
        else:
            out["source_question_ids"] = list(dict.fromkeys(c.strip() for c in codes))[:20]
    if "null_compliance_flag" in data:
        out["null_compliance_flag"] = data.get("null_compliance_flag") is True
    if errs:
        raise Invalid(errors=errs)
    return out


def assert_open(db: Session, e: Engagement) -> None:
    """Sign-off 5 locks the findings, the final tiers and the scores."""
    from app.signoffs.service import current

    so = current(db, e, 5)
    if so is not None and so.status == "approved":
        raise Conflict("Findings are locked: sign-off 5 is approved.")


def create_finding(db: Session, actor: User, e: Engagement, data: dict) -> Finding:
    from app.questionnaire.service import next_finding_ref

    assert_open(db, e)
    v = _clean(db, e, data, partial=False)
    f = Finding(organization_id=e.client_id, engagement_id=e.id, ref=next_finding_ref(db, e), author_id=actor.id, status="draft", origin="manual",
                source_question_ids=v.pop("source_question_ids", []), control_refs=v.pop("control_refs", []), use_case_ids=v.pop("use_case_ids", []), created_by=actor.id, **v)
    db.add(f)
    db.flush()
    audit.record(db, actor_id=actor.id, action="finding.create", obj=f, after={"ref": f.ref, "severity": f.severity, "title": f.title}, summary=f"Drafted finding {f.ref}: {f.title[:120]}")
    return f


def update_finding(db: Session, actor: User, f: Finding, data: dict) -> Finding:
    if f.status not in EDITABLE:
        raise Conflict("Only a draft or returned finding can be edited.")
    e = db.get(Engagement, f.engagement_id)
    assert_open(db, e)
    v = _clean(db, e, data, partial=True)
    before = {k: getattr(f, k) for k in v}
    for k, val in v.items():
        setattr(f, k, val)
    if f.author_id is None:  # an auto-drafted finding becomes the editing auditor's
        f.author_id = actor.id
    f.editor_ids = list(dict.fromkeys([*(f.editor_ids or []), actor.id]))
    f.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="finding.edit", obj=f, before=before, after=v, summary=f"Edited finding {f.ref}")
    return f


def finding_out(db: Session, f: Finding, viewer_is_futran: bool = True) -> dict:
    author = db.get(User, f.author_id) if f.author_id else None
    approver = db.get(User, f.approved_by) if f.approved_by else None
    s = db.get(AISystem, f.ai_system_id) if f.ai_system_id else None
    ucs = [u for u in (db.get(UseCase, i) for i in f.use_case_ids or []) if u is not None]
    out = {
        "id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "status": f.status, "description": f.description, "recommended_remediation": f.recommended_remediation,
        "control_refs": f.control_refs or [], "use_case_ids": f.use_case_ids or [], "use_cases": [u.name for u in ucs], "ai_system_id": f.ai_system_id,
        "system": f"{s.reference_id} {s.name}" if s else None, "template_section": f.template_section, "null_compliance_flag": f.null_compliance_flag, "proposed_owner": f.proposed_owner,
        "approved_at": f.approved_at.isoformat() if f.approved_at else None, "approved_by": approver.name if approver else None,
    }
    if viewer_is_futran:
        out |= {"author_id": f.author_id, "author": author.name if author else ("Raised automatically" if f.origin != "manual" else None), "origin": f.origin,
                "review_comment": f.review_comment, "review_role": f.review_role, "source_question_ids": f.source_question_ids or [], "not_yet_in_place": f.not_yet_in_place,
                "submitted_at": f.submitted_at.isoformat() if f.submitted_at else None}
    return out


# ---- review (spec §6 rules 2 and 5, §18.6)
def team_role_holders(db: Session, e: Engagement, role: str) -> list[User]:
    from app.engagements.models import EngagementTeam

    return list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(EngagementTeam.engagement_id == e.id, EngagementTeam.role == role, EngagementTeam.deleted_at.is_(None))))


def submit(db: Session, settings, actor: User, f: Finding) -> Finding:
    """To the Chief Auditor; a finding the Chief Auditor wrote goes to the QA Reviewer instead."""
    from app.notifications.service import notify

    if f.status not in EDITABLE:
        raise Conflict("This finding has already been submitted.")
    e = db.get(Engagement, f.engagement_id)
    assert_open(db, e)
    if not f.title or f.severity not in SEVERITIES:
        raise Invalid(errors=[{"field": "title", "message": "Give the finding a title and a severity."}])
    chiefs = {u.id for u in team_role_holders(db, e, "chief_auditor")}
    author = f.author_id or actor.id
    # a finding the Chief Auditor wrote, edited or submitted goes to the QA Reviewer (the Chief cannot approve it)
    role = "qa_reviewer" if chiefs & {author, actor.id, *(f.editor_ids or [])} else "chief_auditor"
    reviewers = team_role_holders(db, e, role)
    if role == "qa_reviewer" and not reviewers:
        raise Conflict("A finding the Chief Auditor wrote or edited goes to the QA Reviewer. Add a QA Reviewer to the engagement team first.")
    f.author_id = author
    f.status, f.review_role, f.submitted_at, f.submitted_by, f.review_comment = "submitted", role, utcnow(), actor.id, None
    audit.record(db, actor_id=actor.id, action="finding.submit", obj=f, after={"review_role": role}, summary=f"Submitted finding {f.ref} for approval")
    notify(db, [u for u in reviewers if u.id != author], "finding_submitted", f"{e.audit_ref}: finding {f.ref} is waiting for your approval", f.title, f"/clients/{e.client_id}/findings", engagement=e, settings=settings)
    _advance(db, actor, e)
    if f.severity == "critical":
        notify(db, team_role_holders(db, e, "chief_auditor"), "critical_finding", f"{e.audit_ref}: Critical finding {f.ref}", f"{f.title}. Critical findings are reported to the Lead Auditor at once (§18.6).",
               f"/clients/{e.client_id}/findings", engagement=e, settings=settings, email_template="notification")
    return f


def _assert_reviewer(db: Session, actor: User, f: Finding) -> Engagement:
    e = db.get(Engagement, f.engagement_id)
    if f.status != "submitted":
        raise Conflict("This finding is not waiting for approval.")
    if actor.id in {f.author_id, f.submitted_by, *(f.editor_ids or [])}:
        raise Forbidden("You wrote or edited this finding, so you cannot approve it.")
    if actor.id not in {u.id for u in team_role_holders(db, e, f.review_role or "chief_auditor")}:
        raise Forbidden("This finding is with the " + ("QA Reviewer." if f.review_role == "qa_reviewer" else "Chief Auditor."))
    return e


def approve(db: Session, actor: User, f: Finding, comment: str | None) -> Finding:
    e = _assert_reviewer(db, actor, f)
    assert_open(db, e)
    f.status, f.approved_by, f.approved_at, f.review_comment = "approved", actor.id, utcnow(), (str(comment or "").strip() or None)
    audit.record(db, actor_id=actor.id, action="finding.approve", obj=f, after={"comment": f.review_comment}, summary=f"Approved finding {f.ref}")
    return f


def return_(db: Session, settings, actor: User, f: Finding, comment: str | None) -> Finding:
    from app.notifications.service import notify

    comment = " ".join(str(comment or "").split())
    if not comment:
        raise Invalid(errors=[{"field": "comment", "message": "Say what needs to change."}])
    e = _assert_reviewer(db, actor, f)
    f.status, f.review_comment = "returned", comment[:4000]
    audit.record(db, actor_id=actor.id, action="finding.return", obj=f, after={"comment": f.review_comment}, summary=f"Returned finding {f.ref} to its author")
    notify(db, [db.get(User, f.author_id)] if f.author_id else [], "finding_returned", f"Finding {f.ref} was returned to you", comment, f"/clients/{e.client_id}/findings", engagement=e, settings=settings)
    return f


def dismiss(db: Session, actor: User, f: Finding, reason: str | None) -> None:
    """A draft that should not stand is withdrawn with a reason. Its number is not reused."""
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this is not a finding."}])
    if f.status not in EDITABLE:
        raise Conflict("Only a draft or returned finding can be dismissed.")
    assert_open(db, db.get(Engagement, f.engagement_id))
    f.deleted_at = utcnow()
    from app.findings.models import DraftFindingLink

    for link in db.scalars(select(DraftFindingLink).where(DraftFindingLink.finding_id == f.id, DraftFindingLink.dismissed_at.is_(None))):
        link.dismissed_at, link.dismissed_by, link.dismissed_reason = utcnow(), actor.id, reason[:2000]
    audit.record(db, actor_id=actor.id, action="finding.dismiss", obj=f, after={"reason": reason}, summary=f"Dismissed finding {f.ref}: {reason[:120]}")
    _advance(db, actor, db.get(Engagement, f.engagement_id))


def _advance(db: Session, actor: User, e: Engagement) -> None:
    """The last finding submitted (or dismissed) can complete fieldwork."""
    from app.engagements.gates import advance_if_ready

    db.flush()
    advance_if_ready(db, actor, e)


def signoff5_unmet(db: Session, e: Engagement, _scope=None) -> list[str]:
    if e.stage < 6:
        return ["Sign-off 5 opens at stage 6, once every finding is submitted."]
    from app.engagements.gates import client_review_unmet

    return client_review_unmet(db, e) + [f"{f.ref} {f.title} is not approved yet." for f in findings_for(db, e) if f.status != "approved"]


def _lock_on_signoff5(db: Session, settings, actor, so) -> None:
    from app.scoring.service import lock_scores

    lock_scores(db, db.get(Engagement, so.engagement_id), actor.user)
