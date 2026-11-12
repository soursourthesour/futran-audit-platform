"""Release 2 R2 sales desk: the Sales home (SM-01), stale opportunities and the weekly digest (§4.3 rule 5, §4.10),
email from the rep's own mailbox with replies threading back (§4.3 rule 4), the records linked to an opportunity (SM-04),
and the daily removal of lost prospects after 24 months (R2-Q10 default)."""
from __future__ import annotations

import importlib
import logging
from datetime import date, datetime, time, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Conflict
from app.sales.models import (OPEN_STAGES, PIPELINE_STAGES, STAGE_LABELS, STAGE_PROBABILITY, STALE_DAYS, WORK_KINDS, Opportunity, OpportunityActivity,
                              OpportunityContact)
from app.tenancy.models import Organization, RoleAssignment, User

log = logging.getLogger(__name__)
PURGE_AFTER_DAYS = 730  # lost prospects: 24 months unless reopened (R2-Q10)
NEW_AUTO_DAYS = 7


def _dt(now) -> datetime:
    return now if isinstance(now, datetime) else datetime.combine(now, time(6, 0))


def _module(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


# ---- activity and stale
def last_touches(db: Session, ids: list[str]) -> dict[str, datetime]:
    """The last activity a person logged on each opportunity (calls, emails, meetings, notes, tasks, proposals)."""
    if not ids:
        return {}
    rows = db.execute(select(OpportunityActivity.opportunity_id, func.max(OpportunityActivity.at)).where(
        OpportunityActivity.opportunity_id.in_(ids), OpportunityActivity.kind.in_(WORK_KINDS)).group_by(OpportunityActivity.opportunity_id)).all()
    return {oid: at for oid, at in rows}


def last_touch(o: Opportunity, touches: dict[str, datetime]) -> datetime:
    return max(x for x in (o.last_activity_at, touches.get(o.id), o.created_at) if x is not None)


def is_stale(o: Opportunity, touches: dict[str, datetime], now: datetime | None = None) -> bool:
    if o.stage not in OPEN_STAGES or o.stage == "on_hold":
        return False
    return (now or utcnow()) - last_touch(o, touches) > timedelta(days=STALE_DAYS)


def touch(o: Opportunity, at: datetime | None = None) -> None:
    o.last_activity_at = max(x for x in (o.last_activity_at, at or utcnow()) if x is not None)


def users_with(db: Session, futran_org_id: str | None, roles: tuple[str, ...]) -> list[User]:
    q = select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(RoleAssignment.role.in_(roles), RoleAssignment.deleted_at.is_(None),
                                                                                   User.deleted_at.is_(None), User.status != "disabled")
    if futran_org_id:
        q = q.where(User.organization_id == futran_org_id)
    return list({u.id: u for u in db.scalars(q)}.values())


# ---- the Sales home (SM-01)
def _quarter_start(now: datetime) -> datetime:
    return datetime(now.year, 3 * ((now.month - 1) // 3) + 1, 1)


def _brief(db: Session, o: Opportunity) -> dict:
    org = db.get(Organization, o.organization_id)
    return {"id": o.id, "name": o.name or o.service, "company": org.name if org else "", "stage": o.stage, "stage_label": STAGE_LABELS.get(o.stage, o.stage),
            "value": o.value, "next_step": o.next_step, "next_step_due": o.next_step_due.isoformat() if o.next_step_due else None}


def _proposals_out(db: Session, opp_ids: list[str]) -> tuple[int, int]:
    """Proposals out (sent or viewed, latest versions) and how many expire within 5 days. Zero until R4 lands."""
    mod = _module("app.proposals.models")
    if mod is None or not opp_ids:
        return 0, 0
    P = mod.Proposal
    rows = list(db.scalars(select(P).where(P.opportunity_id.in_(opp_ids), P.status.in_(("sent", "viewed", "changes_requested")))))
    soon = date.today() + timedelta(days=5)
    return len(rows), sum(1 for p in rows if p.valid_until and p.valid_until <= soon)


def _approvals(db: Session, actor, opps: list[Opportunity]) -> list[dict]:
    """Approvals waiting on me (I decide), and my own requests still waiting on someone else."""
    roles = actor.role_names
    out: list[dict] = []
    if "chief_auditor" in roles:
        for o in db.scalars(select(Opportunity).where(Opportunity.needs_ca_approval.is_(True), Opportunity.ca_decision.is_(None),
                                                      Opportunity.approval_requested_at.is_not(None), Opportunity.stage.in_(OPEN_STAGES))):
            out.append({"kind": "to_decide", "opportunity_id": o.id, "label": f"{_brief(db, o)['company']}: {o.name or o.service}", "rule": "Independence",
                        "approver": "Chief Auditor", "link": f"/sales/opportunities/{o.id}"})
    for o in opps:
        if o.owner_id == actor.id and o.needs_ca_approval and o.ca_decision is None and o.approval_requested_at is not None and "chief_auditor" not in roles:
            out.append({"kind": "waiting", "opportunity_id": o.id, "label": f"{_brief(db, o)['company']}: {o.name or o.service}", "rule": "Independence",
                        "approver": "Chief Auditor", "link": f"/sales/opportunities/{o.id}"})
    mod = _module("app.proposals.models")
    if mod is not None:
        P, AR = mod.Proposal, mod.ApprovalRequest
        pending = list(db.scalars(select(AR).where(AR.status == "pending")))
        for r in pending:
            p = db.get(P, r.proposal_id)
            if p is None:
                continue
            o = db.get(Opportunity, p.opportunity_id)
            label = f"{_brief(db, o)['company'] if o else ''} v{p.version}: {r.rule} {r.message or ''}".strip()
            if r.approver_role in roles and r.requested_by != actor.id:
                out.append({"kind": "to_decide", "opportunity_id": p.opportunity_id, "label": label[:200], "rule": r.rule, "approver": r.approver_role, "link": "/sales/approvals"})
            elif r.requested_by == actor.id:
                out.append({"kind": "waiting", "opportunity_id": p.opportunity_id, "label": label[:200], "rule": r.rule, "approver": r.approver_role,
                            "link": f"/sales/opportunities/{p.opportunity_id}"})
    return out


def home(db: Session, actor, scope: str, can_team: bool) -> dict:
    now = utcnow()
    team = scope == "team" and can_team
    stmt = select(Opportunity)
    if not team:
        stmt = stmt.where(Opportunity.owner_id == actor.id)
    opps = [o for o in db.scalars(stmt) if not _deleted_org(db, o)]
    touches = last_touches(db, [o.id for o in opps])
    open_ = [o for o in opps if o.stage in OPEN_STAGES]
    q0 = _quarter_start(now)
    won_q = [o for o in opps if o.stage == "won" and o.closed_at and o.closed_at >= q0]
    out_n, expiring = _proposals_out(db, [o.id for o in open_])
    by_stage = []
    for st in PIPELINE_STAGES:
        rows = [o for o in open_ if o.stage == st or (st == "new" and o.stage == "contacted")]
        by_stage.append({"stage": st, "label": STAGE_LABELS[st], "count": len(rows), "value": sum(o.value or 0 for o in rows)})
    by_stage.append({"stage": "won", "label": "Won (QTD)", "count": len(won_q), "value": sum(o.value or 0 for o in won_q)})
    steps = sorted([o for o in open_ if o.next_step], key=lambda o: (o.next_step_due or date.max, o.created_at))
    task_rows = list(db.scalars(select(OpportunityActivity).where(OpportunityActivity.opportunity_id.in_([o.id for o in open_]), OpportunityActivity.kind == "task",
                                                                   OpportunityActivity.done_at.is_(None)).order_by(OpportunityActivity.due_on))) if open_ else []
    by_id = {o.id: o for o in opps}
    stale = sorted([o for o in open_ if is_stale(o, touches, now)], key=lambda o: last_touch(o, touches))
    since = now - timedelta(days=NEW_AUTO_DAYS)
    auto_stmt = select(Opportunity).where(Opportunity.trigger != "manual", Opportunity.created_at >= since).order_by(Opportunity.created_at.desc())
    new_auto = [o for o in db.scalars(auto_stmt) if (team or o.owner_id in (actor.id, None)) and not _deleted_org(db, o)]
    from app.sales.models import TRIGGER_LABELS

    return {
        "scope": "team" if team else "mine", "can_see_team": can_team,
        "kpis": {"open_pipeline": sum(o.value or 0 for o in open_), "open_count": len(open_),
                 "weighted": round(sum((o.value or 0) * STAGE_PROBABILITY.get(o.stage, 0) for o in open_)), "proposals_out": out_n, "proposals_expiring": expiring,
                 "won_this_quarter": sum(o.value or 0 for o in won_q), "won_count": len(won_q)},
        "by_stage": by_stage,
        "next_steps": [_brief(db, o) for o in steps[:12]],
        "tasks": [{"id": t.id, "opportunity_id": t.opportunity_id, "summary": t.summary, "due_on": t.due_on.isoformat() if t.due_on else None,
                   "company": _brief(db, by_id[t.opportunity_id])["company"]} for t in task_rows[:12]],
        "stale": [_brief(db, o) | {"days": (now - last_touch(o, touches)).days} for o in stale[:12]],
        "approvals": _approvals(db, actor, opps),
        "recent_wins": [_brief(db, o) | {"closed_at": o.closed_at.isoformat()} for o in sorted(won_q, key=lambda o: o.closed_at, reverse=True)[:6]],
        "new_automatic": [_brief(db, o) | {"trigger_label": TRIGGER_LABELS.get(o.trigger, o.trigger), "why_now": o.why_now} for o in new_auto[:8]],
    }


def _deleted_org(db: Session, o: Opportunity) -> bool:
    org = db.get(Organization, o.organization_id)
    return org is None or org.deleted_at is not None


# ---- the weekly stale digest (owner and Sales Managers), once per ISO week, catching up later in the week
def run_stale_digest(db: Session, settings: Settings, now) -> int:
    from app.notifications.models import Notification
    from app.notifications.service import notify

    now = _dt(now)
    week_start = datetime.combine((now - timedelta(days=now.weekday())).date(), time(0, 0))
    opps = [o for o in db.scalars(select(Opportunity).where(Opportunity.stage.in_(OPEN_STAGES))) if not _deleted_org(db, o)]
    touches = last_touches(db, [o.id for o in opps])
    stale = [o for o in opps if is_stale(o, touches, now)]
    if not stale:
        return 0
    recipients: dict[str, tuple[User, list[Opportunity]]] = {}
    for o in stale:
        owner = db.get(User, o.owner_id) if o.owner_id else None
        if owner is not None:
            recipients.setdefault(owner.id, (owner, []))[1].append(o)
    for m in users_with(db, None, ("sales_manager",)):
        recipients.setdefault(m.id, (m, []))[1].extend(x for x in stale if x not in recipients[m.id][1])
    sent = 0
    for uid, (u, rows) in recipients.items():
        if not rows or db.scalar(select(Notification.id).where(Notification.user_id == uid, Notification.kind == "sales_stale_digest", Notification.created_at >= week_start).limit(1)):
            continue
        lines = []
        for o in sorted(rows, key=lambda x: last_touch(x, touches)):
            org = db.get(Organization, o.organization_id)
            owner = db.get(User, o.owner_id) if o.owner_id else None
            lines.append(f"{org.name if org else ''}: {o.name or o.service} · {(now - last_touch(o, touches)).days} days without activity"
                         + (f" · {owner.name}" if owner and owner.id != uid else ""))
        n = len(rows)
        made = notify(db, [u], "sales_stale_digest", f"{n} stale {'opportunity' if n == 1 else 'opportunities'} this week", "\n".join(lines), "/sales/opportunities?stale=1",
               settings=settings, email_template="notification")
        for x in made:
            x.created_at = now  # the week this digest counts for
        sent += 1
    return sent


# ---- lost prospects: deleted after 24 months unless reopened (daily, logged)
def _on_legal_hold(db: Session, org_id: str) -> bool:
    """R7's evidence vault legal holds, when installed: a held organization is never deleted."""
    svc = _module("app.vault.service")
    for fn in ("is_on_hold", "on_legal_hold", "has_legal_hold", "org_on_hold"):
        if svc is not None and hasattr(svc, fn):
            try:
                return bool(getattr(svc, fn)(db, org_id))
            except TypeError:
                continue
    mod = _module("app.vault.models")
    LH = getattr(mod, "LegalHold", None) if mod is not None else None
    if LH is None:
        return False
    q = select(LH).where(LH.organization_id == org_id)
    for h in db.scalars(q):
        if getattr(h, "deleted_at", None) is None and getattr(h, "released_at", None) is None and getattr(h, "status", "active") in ("active", "open", None):
            return True
    return False


def run_lost_prospect_purge(db: Session, settings: Settings, now) -> int:
    now = _dt(now)
    cutoff = now - timedelta(days=PURGE_AFTER_DAYS)
    n = 0
    for org in list(db.scalars(select(Organization).where(Organization.type == "prospect", Organization.status == "prospect"))):
        opps = list(db.scalars(select(Opportunity).where(Opportunity.organization_id == org.id)))
        if not opps or any(o.stage != "lost" for o in opps):
            continue  # reopened, or still being worked
        last = max((o.closed_at or o.updated_at or o.created_at) for o in opps)
        if last > cutoff or _on_legal_hold(db, org.id):
            continue
        _delete_prospect(db, org, opps)
        n += 1
    db.flush()
    return n


def _delete_prospect(db: Session, org: Organization, opps: list[Opportunity]) -> None:
    """Remove the prospect and its sales records (contacts are personal data). Rows other workstreams keep about these
    opportunities (questionnaires, estimates, proposals) go first; a module that is not installed is skipped."""
    ids = [o.id for o in opps]
    name = org.name
    _delete_children(db, ids)
    for model in (OpportunityContact, OpportunityActivity):
        for row in db.scalars(select(model).where(model.opportunity_id.in_(ids))):
            db.delete(row)
    db.flush()
    for o in opps:
        db.delete(o)
    db.flush()
    db.delete(org)
    audit.record(db, actor_id=None, actor_name="Scheduler", action="prospect.deleted", object_type="Organization", object_id=org.id,
                 organization_id=org.id, summary=f"Lost prospect {name} deleted after 24 months without a reopened opportunity")


def _delete_children(db: Session, opp_ids: list[str]) -> None:
    """Other workstreams' rows keyed to these opportunities, deepest first. Guarded: each module may not be installed."""
    plan = [
        ("app.proposals.models", [("ProposalLine", "proposal_id", "Proposal"), ("ApprovalRequest", "proposal_id", "Proposal"), ("ProposalLink", "proposal_id", "Proposal"),
                                  ("ProposalEvent", "proposal_id", "Proposal"), ("Acceptance", "proposal_id", "Proposal")], "Proposal"),
        ("app.scoping.models", [("ScopingAnswer", "questionnaire_id", "ScopingQuestionnaire"), ("QuestionnaireSend", "questionnaire_id", "ScopingQuestionnaire")],
         "ScopingQuestionnaire"),
        ("app.catalog.models", [], "Estimate"),
    ]
    for modname, children, parent_name in plan:
        mod = _module(modname)
        parent = getattr(mod, parent_name, None) if mod is not None else None
        if parent is None or not hasattr(parent, "opportunity_id"):
            continue
        parent_ids = list(db.scalars(select(parent.id).where(parent.opportunity_id.in_(opp_ids))))
        if not parent_ids:
            continue
        for child_name, fk, _ in children:
            child = getattr(mod, child_name, None)
            if child is None or not hasattr(child, fk):
                continue
            for row in db.scalars(select(child).where(getattr(child, fk).in_(parent_ids))):
                db.delete(row)
        db.flush()
        for row in db.scalars(select(parent).where(parent.id.in_(parent_ids))):
            db.delete(row)
        db.flush()


# ---- email from the rep's own mailbox (§4.3 rule 4, v0.6.1 §27.1)
def send_email(db: Session, settings: Settings, actor_user: User, o: Opportunity, to: list[str], subject: str, body: str) -> OpportunityActivity:
    """Sent from the rep's connected mailbox, with the thread reference in the subject so replies come back and show on
    the opportunity (the reply sync stores them on the thread; the timeline reads them from there)."""
    from app.mail import adminlog, delivery
    from app.mail.models import MailRecipient, MailSend, MailThread
    from app.mail.sending import next_subject_ref
    from app.mail.service import render_layout

    futran_id = actor_user.organization_id  # Futran's sales data: never the client's mailbox
    sender = delivery.resolve_sender(db, settings, futran_id, prefer="me", user_id=actor_user.id)
    if sender.user_connection is None:
        raise Conflict("Connect your own mailbox first (Email > My mailbox). Sales emails go from your mailbox so replies come back to this opportunity.")
    now = utcnow()
    html = render_layout("".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in body.split("\n\n")))
    ms = MailSend(organization_id=futran_id, kind="system", mode="direct", template_key="sales_email", template_name="Sales email", subject=subject[:300],
                  channel=sender.channel, sender_user_id=actor_user.id, sender_label=sender.label, recipient_count=len(to), sent_by=actor_user.id,
                  sent_by_name=actor_user.name, related_type="Opportunity", related_id=o.id, status="queued", retain_until=adminlog.retain_until(now), created_by=actor_user.id)
    db.add(ms)
    db.flush()
    ref = next_subject_ref(db)
    thread = MailThread(organization_id=futran_id, send_id=ms.id, user_connection_id=sender.user_connection.id, subject_ref=ref)
    db.add(thread)
    db.flush()
    env = delivery.Envelope(to=list(to), cc=[], subject=f"{subject} [{ref}]", html=html, text=body)
    msg = delivery.record(db, organization_id=futran_id, env=env, stored=None, template_key="sales_email", related=o, actor_id=actor_user.id, mail_send_id=ms.id,
                          channel=sender.channel)
    res = delivery.deliver(db, settings, sender, env, msg)
    for addr in to:
        db.add(MailRecipient(organization_id=futran_id, send_id=ms.id, email=addr.lower(), status="sent" if res.ok else "bounced", error=None if res.ok else res.error,
                             provider_message_id=res.provider_message_id, provider_thread_id=res.provider_thread_id, last_event_at=now, attempts=1))
    ms.status, ms.sent_at = "sent", now
    if res.provider_thread_id:
        thread.provider_thread_id = res.provider_thread_id
    adminlog.write(db, organization_id=futran_id, category="send", action="system_send", actor_name=actor_user.name, send_id=ms.id,
                   summary=f"Sales email to {', '.join(to)[:300]}" + ("" if res.ok else " (not delivered)"))
    if not res.ok:
        raise Conflict(f"The email was not sent: {res.error or 'delivery failed'}")
    a = OpportunityActivity(opportunity_id=o.id, kind="email", summary=f"{subject}\n\n{body}"[:4000], by_id=actor_user.id, at=now, mail_thread_id=thread.id,
                            mail_send_id=ms.id, to_addresses=[t.lower() for t in to])
    db.add(a)
    touch(o, now)
    db.flush()
    return a


def replies_for(db: Session, thread_ids: list[str]) -> dict[str, list[dict]]:
    from app.mail.models import MailReply

    if not thread_ids:
        return {}
    out: dict[str, list[dict]] = {}
    for r in db.scalars(select(MailReply).where(MailReply.thread_id.in_(thread_ids), MailReply.kind == "reply").order_by(MailReply.received_at)):
        out.setdefault(r.thread_id, []).append({"id": r.id, "from": r.from_address, "at": r.received_at.isoformat(), "subject": r.subject, "snippet": r.snippet})
    return out


# ---- records linked to an opportunity (SM-04), each from its own workstream when installed
def linked(db: Session, o: Opportunity) -> dict:
    out: dict = {"questionnaire": None, "estimates": [], "proposals": [], "order": None}
    scoping = _module("app.scoping.service")
    if scoping is not None and hasattr(scoping, "current"):
        try:
            q = scoping.current(db, o.id)
        except Exception:  # noqa: BLE001  (a workstream's helper failing must not hide the record)
            log.exception("scoping.current failed")
            q = None
        if q is not None:
            out["questionnaire"] = {"id": q.id, "version": q.version, "status": q.status, "mode": q.mode, "link": f"/sales/opportunities/{o.id}/scoping"}
    cat = _module("app.catalog.models")
    E = getattr(cat, "Estimate", None) if cat is not None else None
    if E is not None and hasattr(E, "opportunity_id"):
        for e in db.scalars(select(E).where(E.opportunity_id == o.id)):
            out["estimates"].append({"id": e.id, "name": getattr(e, "name", None) or "Estimate", "version": getattr(e, "version", None), "link": f"/sales/estimate?id={e.id}"})
    prop = _module("app.proposals.models")
    P = getattr(prop, "Proposal", None) if prop is not None else None
    if P is not None:
        for p in db.scalars(select(P).where(P.opportunity_id == o.id).order_by(P.version)):
            out["proposals"].append({"id": p.id, "version": p.version, "status": p.status, "title": p.title, "sent_at": p.sent_at.isoformat() if p.sent_at else None,
                                     "link": f"/sales/proposals/{p.id}"})
    com = _module("app.commercial.models")
    Order = getattr(com, "Order", None) if com is not None else None
    if Order is not None and hasattr(Order, "opportunity_id"):
        order = db.scalar(select(Order).where(Order.opportunity_id == o.id).limit(1))
        if order is not None:
            out["order"] = {"id": order.id, "ref": getattr(order, "ref", None), "status": order.status, "link": f"/sales/opportunities/{o.id}/handoff"}
    return out
