"""Management responses (stage 7), sign-off 6 and remediation to close-out (stage 9). Spec §7, §9.6, §14."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Forbidden, Invalid
from app.engagements.models import Engagement
from app.findings.models import Finding
from app.remediation.models import RESPONSES, ManagementResponse, RemediationItem
from app.tenancy.models import User

OPEN = ("open", "in_progress", "reopened")
STATUS_LABEL = {"open": "Open", "in_progress": "In progress", "awaiting_verification": "Awaiting verification", "closed": "Closed", "reopened": "Reopened"}


def finding_department(db: Session, f: Finding) -> str | None:
    from app.inventory.models import UseCase
    from app.systems.models import AISystem

    s = db.get(AISystem, f.ai_system_id) if f.ai_system_id else None
    if s is not None and s.department_id:
        return s.department_id
    for uid in f.use_case_ids or []:
        uc = db.get(UseCase, uid)
        if uc is not None and uc.department_id:
            return uc.department_id
    return None


# ---- management responses (stage 7)
def approved_findings(db: Session, e: Engagement) -> list[Finding]:
    from app.findings.service import findings_for

    return [f for f in findings_for(db, e) if f.status == "approved"]


def response_for(db: Session, f: Finding) -> ManagementResponse | None:
    return db.scalar(select(ManagementResponse).where(ManagementResponse.finding_id == f.id, ManagementResponse.deleted_at.is_(None)))


def responses_for(db: Session, e: Engagement) -> list[ManagementResponse]:
    return list(db.scalars(select(ManagementResponse).where(ManagementResponse.engagement_id == e.id, ManagementResponse.deleted_at.is_(None))))


def assert_responding(db: Session, e: Engagement) -> None:
    from app.signoffs.service import current

    so = current(db, e, 6)
    if so is not None and so.status == "approved":
        raise Conflict("The remediation plan is accepted (sign-off 6). Responses can no longer change.")
    if e.stage != 7:
        raise Conflict("Management responses are given at stage 7, once the draft report is released.")
    if so is not None and so.status in ("pending", "in_review"):
        raise Conflict("The remediation plan is with the signers (sign-off 6). Ask them to return it to make changes.")


def _clean(db: Session, e: Engagement, data: dict) -> dict:
    errs = []
    resp = data.get("response")
    if resp not in RESPONSES:
        errs.append({"field": "response", "message": "Choose agree, partially agree or disagree."})
    action = str(data.get("planned_action") or "").strip()
    needs_plan = resp != "disagree"
    if needs_plan and not action:
        errs.append({"field": "planned_action", "message": "Describe the action you will take."})
    if resp == "disagree" and not action:
        errs.append({"field": "planned_action", "message": "Explain why you disagree."})
    owner = None
    oid = data.get("owner_user_id")
    if oid:
        owner = db.get(User, oid) if isinstance(oid, str) else None
        if owner is None or owner.organization_id != e.client_id or owner.deleted_at is not None or owner.status == "disabled":
            errs.append({"field": "owner_user_id", "message": "Choose a person in your organization."})
            owner = None
    elif needs_plan:
        errs.append({"field": "owner_user_id", "message": "Choose who owns the action."})
    due = None
    if data.get("due_date"):
        try:
            due = date.fromisoformat(str(data["due_date"]))
            if due < today():
                errs.append({"field": "due_date", "message": "The due date is in the past."})
        except ValueError:
            errs.append({"field": "due_date", "message": "Enter a date."})
    elif needs_plan:
        errs.append({"field": "due_date", "message": "Enter the date the action will be done."})
    if errs:
        raise Invalid(errors=errs)
    return {"response": resp, "planned_action": action[:4000], "owner_user_id": owner.id if owner else None, "due_date": due}


def respond(db: Session, actor: Actor, f: Finding, data: dict) -> ManagementResponse:
    """The client answers a finding. Only the response fields are taken: the finding's own text is Futran's (spec §6)."""
    e = db.get(Engagement, f.engagement_id)
    if f.status != "approved":
        raise Conflict("Only approved findings get a management response.")
    assert_responding(db, e)
    v = _clean(db, e, data)
    r = response_for(db, f)
    before = {"response": r.response, "planned_action": r.planned_action} if r else None
    if r is None:
        r = ManagementResponse(organization_id=e.client_id, engagement_id=e.id, finding_id=f.id, created_by=actor.id)
        db.add(r)
    for k, val in v.items():
        setattr(r, k, val)
    r.status, r.adequate, r.adequacy_note, r.reviewed_by, r.reviewed_at = "answered", None, None, None, None
    r.responded_by, r.responded_at, r.updated_by = actor.id, utcnow(), actor.id
    db.flush()
    _sync_item(db, e, f, r)
    audit.record(db, actor_id=actor.id, action="response.save", obj=r, before=before, after={"response": r.response, "planned_action": r.planned_action[:200]},
                 summary=f"{actor.user.name} responded to {f.ref}: {RESPONSES[r.response]}")
    return r


def _sync_item(db: Session, e: Engagement, f: Finding, r: ManagementResponse) -> None:
    """Keep the response's item in step with it while no work has started; an item already under way keeps its record."""
    item = db.scalar(select(RemediationItem).where(RemediationItem.response_id == r.id))
    started = item is not None and item.deleted_at is None and item.status not in ("open",)
    if started:
        return
    if r.response == "disagree":
        if item is not None and item.deleted_at is None:
            item.deleted_at = utcnow()
        return
    if item is None:
        item = RemediationItem(organization_id=e.client_id, engagement_id=e.id, finding_id=f.id, response_id=r.id, status="open", action=r.planned_action)
        db.add(item)
    item.deleted_at = None
    item.action, item.owner_user_id, item.due_date = r.planned_action, r.owner_user_id, r.due_date
    db.flush()


def adequacy_review(db: Session, settings, actor: User, r: ManagementResponse, adequate, note: str | None) -> ManagementResponse:
    """Futran checks each response before the client signs the plan (sign-off 6)."""
    from app.notifications.service import notify

    e = db.get(Engagement, r.engagement_id)
    assert_responding(db, e)
    if not isinstance(adequate, bool):
        raise Invalid(errors=[{"field": "adequate", "message": "Say whether the response is adequate."}])
    note = str(note or "").strip()
    if not adequate and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what the response is missing."}])
    r.adequate, r.adequacy_note, r.reviewed_by, r.reviewed_at = adequate, note[:4000] or None, actor.id, utcnow()
    r.status = "adequate" if adequate else "inadequate"
    f = db.get(Finding, r.finding_id)
    audit.record(db, actor_id=actor.id, action="response.adequacy", obj=r, after={"adequate": adequate, "note": r.adequacy_note}, summary=f"{actor.name} found the response to {f.ref} {'adequate' if adequate else 'inadequate'}")
    if not adequate and r.responded_by:
        notify(db, [db.get(User, r.responded_by)], "response_inadequate", f"{e.audit_ref}: update your response to {f.ref}", note, "/responses", engagement=e, settings=settings)
    return r


def signoff6_unmet(db: Session, e: Engagement, _scope=None) -> list[str]:
    if e.stage != 7:
        return ["Sign-off 6 opens at stage 7, once the draft report is released."]
    out = []
    for f in approved_findings(db, e):
        r = response_for(db, f)
        if r is None:
            out.append(f"{f.ref} {f.title} has no management response.")
        elif r.status == "answered":
            out.append(f"Futran has not finished the adequacy review of the response to {f.ref}.")
        elif r.status == "inadequate":
            out.append(f"Futran found the response to {f.ref} inadequate. Update it.")
    return out


def plan_statement(db: Session, e: Engagement) -> str:
    lines = [f"We accept the management responses and remediation plan for {e.audit_ref}."]
    for f in approved_findings(db, e):
        r = response_for(db, f)
        if r is None:
            continue
        owner = db.get(User, r.owner_user_id).name if r.owner_user_id else "no owner"
        due = f", due {r.due_date.isoformat()}" if r.due_date else ""
        lines.append(f"- {f.ref} ({RESPONSES[r.response]}): {r.planned_action} ({owner}{due})")
    return "\n".join(lines)


def management_responses_context(db: Session, e: Engagement, ctx: dict) -> None:
    """Adds the agreed responses to the final report (v1.1)."""
    rows = []
    for f in approved_findings(db, e):
        r = response_for(db, f)
        if r is not None:
            owner = db.get(User, r.owner_user_id).name if r.owner_user_id else ""
            rows.append({"ref": f.ref, "response": f"{RESPONSES[r.response]}. {r.planned_action or ''}".strip(), "owner": owner, "target_date": r.due_date.isoformat() if r.due_date else ""})
    if rows:
        ctx["management_responses"] = rows


# ---- remediation (stage 9)
def sync_commitments(db: Session, e: Engagement) -> None:
    """Governance commitments are tracked as remediation items, one item each."""
    from app.governance.models import Commitment

    linked = set(db.scalars(select(RemediationItem.commitment_id).where(RemediationItem.engagement_id == e.id, RemediationItem.commitment_id.is_not(None))))
    for c in db.scalars(select(Commitment).where(Commitment.engagement_id == e.id, Commitment.deleted_at.is_(None))):
        if c.id not in linked:
            db.add(RemediationItem(organization_id=e.client_id, engagement_id=e.id, commitment_id=c.id, action=c.description, owner_name=c.owner, due_date=c.target_date,
                                   status=c.status if c.status in STATUS_LABEL else "open"))
    db.flush()


def items_for(db: Session, e: Engagement) -> list[RemediationItem]:
    sync_commitments(db, e)
    return list(db.scalars(select(RemediationItem).where(RemediationItem.engagement_id == e.id, RemediationItem.deleted_at.is_(None)).order_by(RemediationItem.due_date, RemediationItem.created_at)))


def item_department(db: Session, item: RemediationItem) -> str | None:
    f = db.get(Finding, item.finding_id) if item.finding_id else None
    return finding_department(db, f) if f else None


def client_can_act(actor: Actor, db: Session, item: RemediationItem) -> bool:
    """The item's owner, the CAICO, or the Department Lead of the finding's department."""
    if actor.is_futran or actor.organization.id != item.organization_id:
        return False
    if item.owner_user_id == actor.id or actor.has_role("caico"):
        return True
    dept = item_department(db, item)
    return dept is not None and actor.has_role("dept_compliance_lead", "department", dept)


def _set_status(db: Session, item: RemediationItem, status: str) -> None:
    from app.governance.models import Commitment

    item.status = status
    if item.commitment_id:
        c = db.get(Commitment, item.commitment_id)
        if c is not None:
            c.status = status


def start(db: Session, actor: Actor, item: RemediationItem) -> RemediationItem:
    if not client_can_act(actor, db, item):
        raise Forbidden("Only the owner, their Department Lead or the CAICO updates this item.")
    if item.status not in ("open", "reopened"):
        raise Conflict("This item is already under way.")
    _set_status(db, item, "in_progress")
    audit.record(db, actor_id=actor.id, action="remediation.start", obj=item, summary=f"{actor.user.name} started remediation: {item.action[:100]}")
    return item


def mark_done(db: Session, settings, actor: Actor, item: RemediationItem, note: str | None) -> RemediationItem:
    from app.notifications.service import notify
    from app.findings.service import team_role_holders

    if not client_can_act(actor, db, item):
        raise Forbidden("Only the owner, their Department Lead or the CAICO marks this item done.")
    if item.status not in OPEN:
        raise Conflict("This item is already " + STATUS_LABEL[item.status].lower() + ".")
    _set_status(db, item, "awaiting_verification")
    item.done_note, item.marked_done_by, item.marked_done_at = (str(note or "").strip()[:4000] or None), actor.id, utcnow()
    item.verified_by = item.verified_at = item.verification_note = None
    e = db.get(Engagement, item.engagement_id)
    audit.record(db, actor_id=actor.id, action="remediation.done", obj=item, after={"note": item.done_note}, summary=f"{actor.user.name} marked remediation done: {item.action[:100]}")
    notify(db, team_role_holders(db, e, "auditor"), "remediation_done", f"{e.audit_ref}: a remediation item is ready to verify", item.action[:300],
           f"/clients/{e.client_id}/remediation", engagement=e, settings=settings)
    return item


def verify(db: Session, actor: User, item: RemediationItem, note: str | None) -> RemediationItem:
    note = str(note or "").strip()
    if item.status != "awaiting_verification" or item.verified_by:
        raise Conflict("Only an item marked done and not yet verified can be verified.")
    if not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what you checked."}])
    item.verified_by, item.verified_at, item.verification_note = actor.id, utcnow(), note[:4000]
    audit.record(db, actor_id=actor.id, action="remediation.verify", obj=item, after={"note": item.verification_note}, summary=f"{actor.name} verified remediation: {item.action[:100]}")
    return item


def close(db: Session, actor: User, item: RemediationItem) -> RemediationItem:
    if item.status != "awaiting_verification" or not item.verified_by:
        raise Conflict("An auditor verifies the item before it is closed.")
    if item.verified_by == actor.id:
        raise Forbidden("You verified this item, so another person closes it.")
    _set_status(db, item, "closed")
    item.closed_by, item.closed_at = actor.id, utcnow()
    audit.record(db, actor_id=actor.id, action="remediation.close", obj=item, summary=f"{actor.name} closed remediation: {item.action[:100]}")
    _complete_if_done(db, actor, db.get(Engagement, item.engagement_id))
    return item


def reopen(db: Session, actor: User, item: RemediationItem, note: str | None) -> RemediationItem:
    note = str(note or "").strip()
    if item.status not in ("awaiting_verification", "closed"):
        raise Conflict("Only an item marked done or closed can be reopened.")
    if not note:
        raise Invalid(errors=[{"field": "note", "message": "Say why the item is reopened."}])
    e = db.get(Engagement, item.engagement_id)
    if e.status == "completed":
        raise Conflict("The engagement is complete.")
    _set_status(db, item, "reopened")
    item.reopen_note = note[:4000]
    item.verified_by = item.verified_at = item.closed_by = item.closed_at = None
    audit.record(db, actor_id=actor.id, action="remediation.reopen", obj=item, after={"note": item.reopen_note}, summary=f"{actor.name} reopened remediation: {item.action[:100]}")
    return item


def _complete_if_done(db: Session, actor: User, e: Engagement) -> None:
    from app.engagements.gates import advance_if_ready

    advance_if_ready(db, actor, e)


def item_out(db: Session, item: RemediationItem) -> dict:
    f = db.get(Finding, item.finding_id) if item.finding_id else None
    name = lambda uid: db.get(User, uid).name if uid else None  # noqa: E731
    return {
        "id": item.id, "source": "commitment" if item.commitment_id else "finding", "action": item.action, "status": item.status, "status_label": STATUS_LABEL.get(item.status, item.status),
        "finding_ref": f.ref if f else None, "finding_title": f.title if f else None, "severity": f.severity if f else None,
        "owner": name(item.owner_user_id) or item.owner_name, "owner_user_id": item.owner_user_id, "due_date": item.due_date.isoformat() if item.due_date else None,
        "overdue": item.status in OPEN and item.due_date is not None and item.due_date < today(),
        "done_note": item.done_note, "marked_done_by": name(item.marked_done_by), "marked_done_at": item.marked_done_at.isoformat() if item.marked_done_at else None,
        "verified_by": name(item.verified_by), "verified_at": item.verified_at.isoformat() if item.verified_at else None, "verification_note": item.verification_note,
        "closed_by": name(item.closed_by), "closed_at": item.closed_at.isoformat() if item.closed_at else None, "reopen_note": item.reopen_note,
    }


def response_out(db: Session, f: Finding, r: ManagementResponse | None) -> dict:
    owner = db.get(User, r.owner_user_id) if r and r.owner_user_id else None
    return {
        "finding": {"id": f.id, "ref": f.ref, "title": f.title, "severity": f.severity, "description": f.description, "recommended_remediation": f.recommended_remediation},
        "id": r.id if r else None, "response": r.response if r else None, "planned_action": r.planned_action if r else None,
        "owner_user_id": r.owner_user_id if r else None, "owner": owner.name if owner else None, "due_date": r.due_date.isoformat() if r and r.due_date else None,
        "status": r.status if r else "needed", "adequacy_note": r.adequacy_note if r else None,
    }
