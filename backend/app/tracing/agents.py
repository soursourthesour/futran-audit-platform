"""AI agent oversight (spec §21 F14): registration, decision samples for the auditor, the override-rate trend, alerts on
permission changes, and decision logs pushed through the public API.

- Registration is on a register system of type "agent". The client keeps it (the same people who edit the register row).
  Saving it writes one change-log line per changed field. A change to what the agent may do (tools, permissions, approval
  points, autonomy, rate limits) notifies the Chief AI Compliance Officer, the system owner and the Futran audit team.
- Decision logs are the system's ActionTrace rows. The auditor draws a simple random sample without replacement from the
  decisions in a period, ordered by time then id, with Python's `random.Random(seed).sample`. The seed, the period and the
  population size are kept, so anyone can draw the same sample again from the same log.
- Override rate (template 7.1.04): per calendar month, the share of the agent's actions handed to a person ("escalated").
  A month with 20 or more actions and no hand-off is flagged: a rate near zero can mean the human review is a formality.
"""
import random
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.register.models import RegisterSystem
from app.tracing.models import AGENT_AUTONOMY, TOOL_ACCESS, VERDICTS, ActionTrace, AgentDecisionReview, AgentDecisionSample, AgentRegistration
from app.tenancy.models import RoleAssignment, User

PERMISSION_FIELDS = ("tools", "permissions", "approval_points", "autonomy_level", "rate_limits")
CHANGE_FIELDS = {"tools": "agent_tools", "permissions": "agent_permissions", "approval_points": "agent_approval_points", "autonomy_level": "autonomy_level",
                 "kill_switch": "agent_kill_switch", "kill_switch_tested_on": "agent_kill_switch_tested_on", "rate_limits": "agent_rate_limits"}
AUTONOMY_LABELS = {"suggest_only": "Suggests only", "acts_with_approval": "Acts with approval", "autonomous": "Acts on its own"}
VERDICT_LABELS = {"appropriate": "Appropriate", "inappropriate": "Inappropriate", "needs_follow_up": "Needs follow-up"}
MAX_SAMPLE = 200
FLAG_MIN_ACTIONS = 20
TREND_MONTHS = 6


def registration(db: Session, s: RegisterSystem) -> AgentRegistration | None:
    return db.scalar(select(AgentRegistration).where(AgentRegistration.register_system_id == s.id, AgentRegistration.deleted_at.is_(None)))


def registration_out(r: AgentRegistration | None) -> dict | None:
    if r is None:
        return None
    return {"tools": r.tools or [], "permissions": r.permissions or [], "approval_points": r.approval_points or [], "autonomy_level": r.autonomy_level,
            "autonomy_label": AUTONOMY_LABELS.get(r.autonomy_level), "kill_switch": r.kill_switch, "kill_switch_tested_on": r.kill_switch_tested_on.isoformat() if r.kill_switch_tested_on else None,
            "rate_limits": r.rate_limits, "version": r.version, "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def _lines(v, field: str, errs: list) -> list[str]:
    if v in (None, ""):
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        errs.append({"field": field, "message": "Give a list of short statements."})
        return []
    return [" ".join(x.split())[:300] for x in v if x.strip()][:50]


def clean(data: dict) -> dict:
    errs: list = []
    tools = []
    raw = data.get("tools") or []
    if not isinstance(raw, list):
        errs.append({"field": "tools", "message": "List the tools the agent can call."})
        raw = []
    for i, t in enumerate(raw[:100]):
        name = " ".join(str((t or {}).get("name") or "").split())[:120] if isinstance(t, dict) else ""
        access = (t or {}).get("access") if isinstance(t, dict) else None
        if not name or access not in TOOL_ACCESS:
            errs.append({"field": "tools", "message": f"Tool {i + 1}: give its name and whether it reads, writes or acts."})
            continue
        tools.append({"name": name, "description": " ".join(str(t.get("description") or "").split())[:300] or None, "access": access, "needs_approval": bool(t.get("needs_approval"))})
    level = data.get("autonomy_level")
    if level not in AGENT_AUTONOMY:
        errs.append({"field": "autonomy_level", "message": "Choose how far the agent acts on its own."})
    tested = data.get("kill_switch_tested_on")
    tested_on = None
    if tested:
        try:
            tested_on = date.fromisoformat(str(tested)[:10])
        except ValueError:
            errs.append({"field": "kill_switch_tested_on", "message": "Enter a date."})
        else:
            if tested_on > date.today():
                errs.append({"field": "kill_switch_tested_on", "message": "This is in the future."})
    out = {"tools": tools, "permissions": _lines(data.get("permissions"), "permissions", errs), "approval_points": _lines(data.get("approval_points"), "approval_points", errs),
           "autonomy_level": level, "kill_switch": (str(data.get("kill_switch") or "").strip()[:2000] or None), "kill_switch_tested_on": tested_on,
           "rate_limits": (" ".join(str(data.get("rate_limits") or "").split())[:300] or None)}
    if errs:
        raise Invalid(errors=errs)
    return out


def _display(field: str, v) -> str | None:
    if v in (None, [], ""):
        return None
    if field == "tools":
        return "; ".join(f"{t['name']} ({t['access']}{', needs approval' if t.get('needs_approval') else ''})" for t in v)[:2000]
    if isinstance(v, list):
        return "; ".join(v)[:2000]
    if field == "autonomy_level":
        return AUTONOMY_LABELS.get(v, v)
    return str(v)[:2000]


def save(db: Session, settings, actor, s: RegisterSystem, data: dict) -> AgentRegistration:
    from app.register.service import log_change

    if s.type != "agent":
        raise Conflict("Agent registration is for systems of type agent. Change the type on the Details tab first.")
    v = clean(data)
    r = registration(db, s)
    first = r is None
    if first:
        r = AgentRegistration(organization_id=s.organization_id, register_system_id=s.id, created_by=actor.id, version=0)
        db.add(r)
    before = {k: getattr(r, k, None) for k in CHANGE_FIELDS}
    for k, val in v.items():
        setattr(r, k, val)
    changed = [k for k in CHANGE_FIELDS if before.get(k) != v[k]]
    if not changed and not first:
        return r
    r.version = (r.version or 0) + 1
    r.updated_by = actor.id
    if s.autonomy != v["autonomy_level"]:  # the register row and the registration say the same
        old_autonomy, s.autonomy = s.autonomy, v["autonomy_level"]
        log_change(db, actor.user, s, "autonomy", old_autonomy, s.autonomy, "Changed in the agent registration")
    db.flush()
    for k in changed:
        log_change(db, actor.user, s, CHANGE_FIELDS[k], _display(k, before.get(k)), _display(k, v[k]), "Agent registration" if first else None,
                   entity="AgentRegistration", entity_id=r.id, raw=True)
    audit.record(db, actor_id=actor.id, action="agent.registered" if first else "agent.registration_changed", obj=r, request=actor.request,
                 before=None if first else {k: _display(k, before.get(k)) for k in changed}, after={k: _display(k, v[k]) for k in changed},
                 summary=f"{'Registered' if first else 'Changed the registration of'} agent {s.reference} {s.name} (version {r.version})")
    perm = [k for k in changed if k in PERMISSION_FIELDS]
    if perm and not first:
        alert_permission_change(db, settings, actor, s, perm)
    return r


def register_autonomy_changed(db: Session, settings, user: User, s: RegisterSystem, old: str | None, new: str | None) -> None:
    """The register row's autonomy was edited (register screen, bulk edit or the public API). The registration follows, with
    its own change-log line, and the change is alerted like any other change to what the agent may do."""
    from app.register.service import log_change

    if s.type != "agent" or new is None or old == new:
        return
    r = registration(db, s)
    if r is not None and r.autonomy_level != new:
        before = r.autonomy_level
        r.autonomy_level, r.version, r.updated_by = new, (r.version or 0) + 1, user.id
        db.flush()
        log_change(db, user, s, CHANGE_FIELDS["autonomy_level"], _display("autonomy_level", before), _display("autonomy_level", new), "Changed on the register",
                   entity="AgentRegistration", entity_id=r.id, raw=True)
    if r is not None or old is not None:
        alert_permission_change(db, settings, user, s, ["autonomy_level"])


def _caicos(db: Session, org_id: str) -> list[User]:
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == org_id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None), User.status == "active").distinct()))


def _audit_team(db: Session, org_id: str) -> list[User]:
    from app.notifications.service import futran_team
    from app.tenancy.models import Organization
    from app.tenancy.people import current_engagement

    e = current_engagement(db, db.get(Organization, org_id))
    return futran_team(db, e) if e is not None and e.status != "completed" else []


def alert_permission_change(db: Session, settings, actor, s: RegisterSystem, fields: list[str]) -> None:
    from app.notifications.service import notify

    who = getattr(actor, "user", actor)  # an Actor (the agent screen) or a User (register edits, the public API)
    what = ", ".join({"tools": "tools", "permissions": "permissions", "approval_points": "approval points", "autonomy_level": "autonomy", "rate_limits": "rate limits"}[f] for f in fields)
    owner = db.get(User, s.owner_user_id) if s.owner_user_id else None
    client_people = [u for u in [*_caicos(db, s.organization_id), owner] if u is not None and u.id != actor.id]
    title = f"Agent {s.reference} {s.name}: {what} changed"
    body = f"{who.name} changed what the agent may do. Check the change log and confirm the change was approved."
    notify(db, client_people, "agent_permissions_changed", title, body, f"/register/{s.id}/agent", settings=settings, email_template="notification")
    team = [u for u in _audit_team(db, s.organization_id) if u.id != actor.id]
    notify(db, team, "agent_permissions_changed", f"{title} (client change)", body, f"/clients/{s.organization_id}/agents", settings=settings)


def unregistered_tools(db: Session, s: RegisterSystem, r: AgentRegistration | None = None) -> list[str]:
    """Tools seen in the agent's decision log that its registration does not list."""
    r = r if r is not None else registration(db, s)
    known = {t["name"].casefold() for t in (r.tools if r else [])}
    seen = db.scalars(select(ActionTrace.tool).where(ActionTrace.register_system_id == s.id, ActionTrace.tool.is_not(None)).distinct())
    return sorted({t for t in seen if t and t.casefold() not in known})


# ---------------------------------------------------------------- the override-rate trend
def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def trend(db: Session, s: RegisterSystem, today: date | None = None) -> tuple[list[dict], list[str]]:
    today = today or utcnow().date()
    months = [_month_start(today, i) for i in range(TREND_MONTHS - 1, -1, -1)]
    start = datetime.combine(months[0], datetime.min.time())
    rows = db.execute(select(ActionTrace.at, ActionTrace.decision).where(ActionTrace.register_system_id == s.id, ActionTrace.at >= start))
    buckets = {m: {"total": 0, "escalated": 0, "blocked": 0} for m in months}
    for at, decision in rows:
        key = date(at.year, at.month, 1)
        if key in buckets:
            buckets[key]["total"] += 1
            if decision in ("escalated", "blocked"):
                buckets[key][decision] += 1
    out, flags = [], []
    for m in months:
        b = buckets[m]
        rate = round(100 * b["escalated"] / b["total"], 1) if b["total"] else None
        out.append({"month": m.strftime("%Y-%m"), "label": m.strftime("%b %Y"), **b, "override_rate": rate})
        if b["total"] >= FLAG_MIN_ACTIONS and b["escalated"] == 0:
            flags.append(f"{m:%B %Y}: {b['total']} actions and none handed to a person. Check that the human review is real (template 7.1.04).")
    return out, flags


# ---------------------------------------------------------------- decision samples
def draw(db: Session, actor, s: RegisterSystem, engagement_id: str | None, size: int, period_days: int, seed: int | None) -> AgentDecisionSample:
    if s.type != "agent":
        raise Conflict("Decision samples are drawn from agents' decision logs. This system is not an agent.")
    if not 1 <= size <= MAX_SAMPLE:
        raise Invalid(errors=[{"field": "size", "message": f"Choose a sample of 1 to {MAX_SAMPLE} decisions."}])
    if not 1 <= period_days <= 3660:
        raise Invalid(errors=[{"field": "period_days", "message": "Choose a period of 1 day to 10 years."}])
    if seed is None:
        seed = secrets.randbelow(2**31 - 1)
    elif not 0 <= seed < 2**31:
        raise Invalid(errors=[{"field": "seed", "message": "The seed must be a whole number from 0 to 2147483647."}])
    to = utcnow()
    frm = to - timedelta(days=period_days)
    ids = list(db.scalars(select(ActionTrace.id).where(ActionTrace.register_system_id == s.id, ActionTrace.at >= frm, ActionTrace.at <= to).order_by(ActionTrace.at, ActionTrace.id)))
    if not ids:
        raise Conflict("The agent has no decisions on record in this period. Ask the client to import or send its decision log.")
    picked = random.Random(seed).sample(ids, min(size, len(ids)))
    smp = AgentDecisionSample(organization_id=s.organization_id, register_system_id=s.id, engagement_id=engagement_id, seed=seed, period_from=frm, period_to=to, population=len(ids),
                              trace_ids=picked, drawn_by=actor.id, status="open", created_by=actor.id, updated_by=actor.id,
                              method=f"Simple random sample of {len(picked)} from {len(ids)} decisions between {frm:%Y-%m-%d %H:%M} and {to:%Y-%m-%d %H:%M} UTC, "
                                     f"ordered by time then id; Python random.Random({seed}).sample.")
    db.add(smp)
    db.flush()
    audit.record(db, actor_id=actor.id, action="agent_sample.drawn", obj=smp, request=actor.request, after={"seed": seed, "population": len(ids), "size": len(picked)},
                 summary=f"Drew {len(picked)} of {len(ids)} decisions of {s.reference} {s.name} for review (seed {seed})")
    return smp


def load_sample(db: Session, sample_id: str) -> AgentDecisionSample:
    smp = db.get(AgentDecisionSample, sample_id)
    if smp is None or smp.deleted_at is not None:
        raise NotFound()
    return smp


def review(db: Session, actor, smp: AgentDecisionSample, trace_id: str, verdict: str, note: str | None) -> AgentDecisionReview:
    if smp.status != "open":
        raise Conflict("This sample is complete. Draw a new sample to review more decisions.")
    if trace_id not in (smp.trace_ids or []):
        raise Invalid(errors=[{"field": "trace_id", "message": "This decision is not in the sample."}])
    if verdict not in VERDICTS:
        raise Invalid(errors=[{"field": "verdict", "message": "Choose appropriate, inappropriate or needs follow-up."}])
    note = (note or "").strip()[:2000] or None
    if verdict != "appropriate" and not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what was wrong or what to follow up."}])
    r = db.scalar(select(AgentDecisionReview).where(AgentDecisionReview.sample_id == smp.id, AgentDecisionReview.trace_id == trace_id))
    before = {"verdict": r.verdict, "note": r.note} if r else None
    if r is None:
        r = AgentDecisionReview(organization_id=smp.organization_id, sample_id=smp.id, trace_id=trace_id, verdict=verdict, reviewer_id=actor.id)
        db.add(r)
    r.verdict, r.note, r.reviewer_id, r.reviewed_at = verdict, note, actor.id, utcnow()
    db.flush()
    audit.record(db, actor_id=actor.id, action="agent_sample.reviewed", object_type="AgentDecisionSample", object_id=smp.id, organization_id=smp.organization_id,
                 engagement_id=smp.engagement_id, request=actor.request, before=before, after={"trace_id": trace_id, "verdict": verdict, "note": note},
                 summary=f"Recorded {VERDICT_LABELS[verdict].lower()} on a sampled agent decision")
    return r


def complete(db: Session, actor, smp: AgentDecisionSample, conclusion: str | None) -> AgentDecisionSample:
    if smp.status != "open":
        raise Conflict("This sample is already complete.")
    done = set(db.scalars(select(AgentDecisionReview.trace_id).where(AgentDecisionReview.sample_id == smp.id)))
    left = [t for t in smp.trace_ids if t not in done]
    if left:
        raise Conflict(f"{len(left)} sampled decisions have no verdict yet.")
    smp.status, smp.completed_by, smp.completed_at, smp.updated_by = "complete", actor.id, utcnow(), actor.id
    smp.conclusion = (conclusion or "").strip()[:4000] or None
    audit.record(db, actor_id=actor.id, action="agent_sample.completed", obj=smp, request=actor.request, after=summary(db, smp), summary="Completed the review of an agent decision sample")
    return smp


def summary(db: Session, smp: AgentDecisionSample) -> dict:
    counts = dict(db.execute(select(AgentDecisionReview.verdict, func.count()).where(AgentDecisionReview.sample_id == smp.id).group_by(AgentDecisionReview.verdict)).all())
    return {v: counts.get(v, 0) for v in VERDICTS}


def sample_out(db: Session, smp: AgentDecisionSample) -> dict:
    from app.engagements.models import Engagement
    from app.tracing.traces import trace_out

    traces = {t.id: t for t in db.scalars(select(ActionTrace).where(ActionTrace.id.in_(smp.trace_ids or [])))}
    reviews = {r.trace_id: r for r in db.scalars(select(AgentDecisionReview).where(AgentDecisionReview.sample_id == smp.id))}
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({smp.drawn_by, smp.completed_by, *(r.reviewer_id for r in reviews.values())} - {None})))}
    e = db.get(Engagement, smp.engagement_id) if smp.engagement_id else None
    decisions = []
    for tid in smp.trace_ids or []:
        t = traces.get(tid)
        r = reviews.get(tid)
        decisions.append({**(trace_out(t) if t else {"id": tid}), "verdict": r.verdict if r else None, "verdict_label": VERDICT_LABELS.get(r.verdict) if r else None,
                          "note": r.note if r else None, "reviewer": names.get(r.reviewer_id) if r else None})
    return {"id": smp.id, "system_id": smp.register_system_id, "engagement": e.audit_ref if e else None, "seed": smp.seed, "population": smp.population, "size": len(smp.trace_ids or []),
            "period_from": smp.period_from.isoformat(), "period_to": smp.period_to.isoformat(), "method": smp.method, "status": smp.status, "drawn_by": names.get(smp.drawn_by),
            "drawn_at": smp.created_at.isoformat(), "completed_by": names.get(smp.completed_by), "completed_at": smp.completed_at.isoformat() if smp.completed_at else None,
            "conclusion": smp.conclusion, "summary": summary(db, smp), "decisions": decisions}


# ---------------------------------------------------------------- decision logs pushed through the public API
def push(db: Session, settings, owner: User, s: RegisterSystem, events: list[dict], client_name: str) -> dict:
    from app.notifications.service import notify
    from app.tracing.access import state_for
    from app.tracing.traces import ingest

    if s.type != "agent":
        raise Conflict("Decision logs are taken for systems of type agent only.")
    if state_for(db, s)[0] != "active":
        raise Conflict("The tracing add-on is not active for this system. Ask your Chief AI Compliance Officer to unlock it.")
    if not isinstance(events, list) or not 1 <= len(events) <= 1000:
        raise Invalid(errors=[{"field": "events", "message": "Send 1 to 1,000 events in one call."}])
    r = registration(db, s)
    known_before = set(unregistered_tools(db, s, r))
    imp = ingest(db, owner.id, s, "api", events, f"API client {client_name}")
    now_unknown = unregistered_tools(db, s, r)
    pushed_tools = {str(e.get("tool") or "").strip() for e in events if isinstance(e, dict)}
    new = [t for t in now_unknown if t not in known_before]
    if new:
        notify(db, [u for u in [*_caicos(db, s.organization_id), db.get(User, s.owner_user_id) if s.owner_user_id else None] if u is not None],
               "agent_unregistered_tool", f"Agent {s.reference} {s.name} used a tool that is not registered", f"Not in the registration: {', '.join(new)}.",
               f"/register/{s.id}/agent", settings=settings, email_template="notification")
    return {"added": imp.added, "skipped": imp.skipped, "unregistered_tools": [t for t in now_unknown if t in pushed_tools]}
