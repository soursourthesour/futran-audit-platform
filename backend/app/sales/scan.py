"""Periodic opportunity scan (11-03 review, F8).

The Futran Admin sets "Look for new opportunities every N days" (off by default). The daily jobs run the scan once N days
have passed since the last completed scan (by date, so a run that starts a few minutes later still counts); "Run now"
runs it at once. Each scan looks at what changed since the last completed scan (the first one looks back one interval,
or 30 days when the setting is off) and opens opportunities through `open_from_trigger`, once per client and reference:

- laws added or materially changed in the law library (approved versions) that the scope engine puts the client in
  scope of;
- regulatory updates published since the last scan that were matched to the client (`RegulatoryAlert`);
- renewal audits: a client's latest completed engagement reaches its anniversary within 90 days and no annual review or
  newer engagement has been started.

The independence rule and the Chief Auditor approval flag are applied by `open_from_trigger` exactly as for every
other trigger. Each client's opportunities are opened inside its own savepoint, so one client that fails is logged
and skipped and the others still get theirs. Every run is audit-logged with its counts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Invalid
from app.core.ids import new_id
from app.sales import service as sales
from app.sales.models import Opportunity, OpportunityScanRun, OpportunityScanSetting
from app.tenancy.models import Organization, User

log = logging.getLogger(__name__)

CHOICES = (7, 15, 30)
MIN_DAYS, MAX_DAYS = 1, 365
LOOKBACK_WHEN_OFF = 30
RENEWAL_WINDOW_DAYS = 90
DAILY_RUN_UTC = time(10, 0)  # start_scheduler's daily tick (06:00 New York)
LAW_TRIGGERS = ("new_law", "law_change")
# Approved changes that do not change what a client must do: a version made only of these is not an opportunity.
COSMETIC_PATHS = {"law.verify_flag", "law.source_ids", "law.litigation_text", "law.main_duty", "law.effective_text", "law.short_name", "law.citation",
                  "law.topics", "law.label"}
COUNT_KEYS = ("laws", "regulatory_updates", "renewals", "already_open", "held_back", "failed_clients")


@dataclass
class Item:
    organization_id: str
    kind: str  # laws | regulatory_updates | renewals
    trigger: str
    ref: str
    service: str
    service_kind: str
    why_now: str
    same_refs: list[str] = field(default_factory=list)  # other references that mean the same opportunity is already open
    same_triggers: tuple[str, ...] = ()
    system_ids: list[str] = field(default_factory=list)
    after: Callable[[Opportunity], None] | None = None


# ------------------------------------------------------------------ setting

def _setting(db: Session) -> OpportunityScanSetting | None:
    return db.scalar(select(OpportunityScanSetting).where(OpportunityScanSetting.key == "platform"))


def interval(db: Session) -> int | None:
    s = _setting(db)
    return s.every_days if s is not None else None


def _futran_org_id(db: Session) -> str | None:
    return db.scalar(select(Organization.id).where(Organization.type == "futran", Organization.deleted_at.is_(None)).order_by(Organization.created_at).limit(1))


def set_interval(db: Session, actor: User, every_days: int | None, request=None) -> OpportunityScanSetting:
    if every_days is not None and not MIN_DAYS <= every_days <= MAX_DAYS:
        raise Invalid(errors=[{"field": "every_days", "message": f"Choose a number of days from {MIN_DAYS} to {MAX_DAYS}."}])
    s = _setting(db)
    if s is None:
        s = OpportunityScanSetting(key="platform")
        db.add(s)
    before = s.every_days
    s.every_days, s.updated_by = every_days, actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="opportunity_scan.settings", obj=s, organization_id=actor.organization_id, request=request,
                 before={"every_days": before}, after={"every_days": every_days},
                 summary=f"Opportunity scan set to every {every_days} days" if every_days else "Opportunity scan turned off")
    return s


def last_completed(db: Session) -> OpportunityScanRun | None:
    return db.scalar(select(OpportunityScanRun).where(OpportunityScanRun.status == "completed").order_by(OpportunityScanRun.started_at.desc()).limit(1))


def last_run(db: Session) -> OpportunityScanRun | None:
    return db.scalar(select(OpportunityScanRun).order_by(OpportunityScanRun.started_at.desc()).limit(1))


def _due_on(db: Session, n: int) -> date | None:
    last = last_completed(db)
    return last.started_at.date() + timedelta(days=n) if last is not None else None


def next_run_on(db: Session, now: datetime | None = None) -> date | None:
    """The date of the daily run that will next scan (None while the setting is off)."""
    n = interval(db)
    if n is None:
        return None
    now = _dt(now or utcnow())
    first_daily = now.date() if now.time() < DAILY_RUN_UTC else now.date() + timedelta(days=1)
    due = _due_on(db, n)
    return max(due, first_daily) if due else first_daily


def _dt(now) -> datetime:
    return now if isinstance(now, datetime) else datetime.combine(now, DAILY_RUN_UTC)


# ------------------------------------------------------------------ running

def run_scheduled(db: Session, settings, now) -> int:
    """The daily job: scan when the interval has passed. The scheduled key for the day is claimed once, so two processes
    that run the daily jobs together scan once. Returns 1 when it scanned."""
    now = _dt(now)
    n = interval(db)
    if n is None:
        return 0
    due = _due_on(db, n)
    if due is not None and now.date() < due:
        return 0
    key = f"scheduled:{now.date().isoformat()}"
    if db.scalar(select(OpportunityScanRun.id).where(OpportunityScanRun.run_key == key)):
        return 0
    try:
        with db.begin_nested():
            run = OpportunityScanRun(run_key=key, trigger="scheduled", started_at=now, since=_since(db, now), status="running", counts={}, found=[], errors=[])
            db.add(run)
            db.flush()
    except IntegrityError:  # another process claimed it first
        return 0
    _execute(db, run, None)
    return 1


def run_now(db: Session, actor: User, now: datetime | None = None, request=None) -> OpportunityScanRun:
    return run_scan(db, trigger="manual", actor=actor, now=now, request=request)


def run_scan(db: Session, *, trigger: str, actor: User | None, now: datetime | None = None, since: datetime | None = None, request=None) -> OpportunityScanRun:
    now = _dt(now or utcnow())
    run = OpportunityScanRun(run_key=f"{trigger}:{new_id()}", trigger=trigger, started_at=now, since=since or _since(db, now), status="running",
                             counts={}, found=[], errors=[], started_by=actor.id if actor else None)
    db.add(run)
    db.flush()
    _execute(db, run, actor, request=request)
    return run


def _since(db: Session, now: datetime) -> datetime:
    last = last_completed(db)
    if last is not None:
        return last.started_at
    return now - timedelta(days=interval(db) or LOOKBACK_WHEN_OFF)


def _execute(db: Session, run: OpportunityScanRun, actor: User | None, request=None) -> None:
    counts = dict.fromkeys(COUNT_KEYS, 0)
    found: list[str] = []
    errors: list[dict] = []
    now = run.started_at
    try:
        with db.begin_nested():
            items = _law_items(db, run.since, now) + _update_items(db, run.since, now) + _renewal_items(db, now.date())
    except Exception as exc:  # noqa: BLE001 (logged and shown on the run; the next scheduled day tries again)
        log.exception("Opportunity scan %s could not gather its sources", run.id)
        run.status, run.finished_at, run.errors = "failed", utcnow(), [{"client": None, "error": exc.__class__.__name__}]
        run.counts = counts
        _audit(db, run, actor, request)
        return
    by_org: dict[str, list[Item]] = {}
    for it in items:
        by_org.setdefault(it.organization_id, []).append(it)
    names = {o.id: o.name for o in db.scalars(select(Organization).where(Organization.id.in_(list(by_org))))}
    for org_id in sorted(by_org, key=lambda i: (names.get(i, "").casefold(), i)):
        mine = dict.fromkeys(COUNT_KEYS, 0)
        opened: list[str] = []
        try:
            with db.begin_nested():  # one client's failure leaves the other clients' opportunities in place
                for it in by_org[org_id]:
                    if _already_open(db, it):
                        mine["already_open"] += 1
                        continue
                    try:
                        o = sales.open_from_trigger(db, org_id, it.trigger, it.ref, service=it.service, why_now=it.why_now, service_kind=it.service_kind,
                                                    system_ids=it.system_ids, created_by=actor.id if actor else None)
                    except sales.IndependenceError:
                        mine["held_back"] += 1
                        continue
                    if it.after is not None:
                        it.after(o)
                    opened.append(o.id)
                    mine[it.kind] += 1
                db.flush()
        except Exception as exc:  # noqa: BLE001 (logged; nothing of this client's is kept, the next scan tries again)
            log.exception("Opportunity scan %s failed for client %s", run.id, org_id)
            errors.append({"client": names.get(org_id, org_id), "error": exc.__class__.__name__})
            counts["failed_clients"] += 1
            continue
        for k, v in mine.items():
            counts[k] += v
        found += opened
    run.counts, run.found, run.errors = counts, found, errors
    run.status, run.finished_at = "completed", utcnow()
    db.flush()
    _audit(db, run, actor, request)


def _audit(db: Session, run: OpportunityScanRun, actor: User | None, request) -> None:
    org_id = actor.organization_id if actor else _futran_org_id(db)
    if org_id is None:
        return
    c = run.counts or {}
    n = len(run.found or [])
    if run.status == "failed":
        summary = "Opportunity scan failed before it could look for opportunities"
    else:
        summary = (f"Opportunity scan found {n} new {'opportunity' if n == 1 else 'opportunities'}: {c.get('laws', 0)} from the law library, "
                   f"{c.get('regulatory_updates', 0)} from regulatory updates, {c.get('renewals', 0)} renewal audits")
        if c.get("failed_clients"):
            summary += f"; {c['failed_clients']} {'client' if c['failed_clients'] == 1 else 'clients'} failed and will be tried again"
    audit.record(db, actor_id=actor.id if actor else None, actor_name=None if actor else "Scheduler", action="opportunity_scan.run", obj=run, organization_id=org_id,
                 request=request, after={"trigger": run.trigger, "since": run.since.isoformat(), "status": run.status, "counts": c, "errors": run.errors or []},
                 summary=summary[:1000])


def _already_open(db: Session, it: Item) -> bool:
    refs = [it.ref, *it.same_refs]
    triggers = it.same_triggers or (it.trigger,)
    return db.scalar(select(Opportunity.id).where(Opportunity.organization_id == it.organization_id, Opportunity.trigger.in_(triggers),
                                                  Opportunity.trigger_ref.in_(refs)).limit(1)) is not None


def _clients(db: Session) -> set[str]:
    return set(db.scalars(select(Organization.id).where(Organization.type == "client", Organization.deleted_at.is_(None))))


def _day(d: date | datetime) -> str:
    return f"{d.day} {d:%B %Y}"


# ------------------------------------------------------------------ sources

def _law_items(db: Session, since: datetime, now: datetime) -> list[Item]:
    """(a) The newest version of each law approved in the window, when it is a new law or changes more than wording."""
    from app.laws.models import Regulation
    from app.laws.publish import chain_ids, current_version_of
    from app.regmaster.engine import law_label
    from app.regmaster.models import ClientLawApplicability, LawVersion, ProposedChange

    latest: dict[str, tuple[Regulation, object, list[str]]] = {}
    for v in db.scalars(select(LawVersion).where(LawVersion.approved_at.is_not(None), LawVersion.approved_at > since, LawVersion.approved_at <= now)
                        .order_by(LawVersion.approved_at)):
        reg = current_version_of(db, v.regulation_id)
        if reg is None or reg.retired_in_version_id is not None:
            continue
        ids = chain_ids(db, reg.id) or [reg.id]
        latest[ids[0]] = (reg, v, ids)  # a later approval in the window replaces an earlier one
    clients = _clients(db)
    out: list[Item] = []
    for reg, v, ids in latest.values():
        pcs = list(db.scalars(select(ProposedChange).where(ProposedChange.applied_version_id == v.id)))
        new = v.version_no == 1 or any(pc.field_path == "new_law" for pc in pcs)
        if not new and pcs and all(pc.field_path in COSMETIC_PATHS for pc in pcs):
            continue
        label = law_label(reg)
        what = "; ".join(dict.fromkeys(pc.summary for pc in pcs)) or v.change_summary or "a new version was approved"
        ref = f"lawver:{v.id}"
        rows = db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.regulation_id.in_(ids), ClientLawApplicability.in_scope.is_(True),
                                                               ClientLawApplicability.deleted_at.is_(None)))
        for row in {r.organization_id: r for r in rows}.values():
            if row.organization_id not in clients:
                continue
            why = f"New law in the library: {label}" if new else f"{label} changed: {what}"
            if row.reason_text:
                why += f" (applies: {row.reason_text})"
            out.append(Item(row.organization_id, "laws", "new_law" if new else "law_change", ref, service=f"{label} readiness review", service_kind="readiness",
                            why_now=why[:300], same_refs=[pc.id for pc in pcs], same_triggers=LAW_TRIGGERS))
    return out


def _update_items(db: Session, since: datetime, now: datetime) -> list[Item]:
    """(b) Published regulatory updates matched to a client. The reference is the update, as for "Create advisory
    opportunity" on the update itself, so the two never open the same opportunity twice."""
    from app.regupdates.models import RegulatoryAlert, RegulatoryUpdate
    from app.regupdates.service import CHANGE_LABELS

    clients = _clients(db)
    rows = db.execute(select(RegulatoryAlert, RegulatoryUpdate).join(RegulatoryUpdate, RegulatoryUpdate.id == RegulatoryAlert.update_id)
                      .where(RegulatoryUpdate.status == "published", RegulatoryUpdate.watch.is_(False), RegulatoryUpdate.published_at > since,
                             RegulatoryUpdate.published_at <= now, RegulatoryAlert.deleted_at.is_(None))
                      .order_by(RegulatoryUpdate.published_at)).all()
    out: list[Item] = []
    for a, u in rows:
        if a.organization_id not in clients:
            continue
        why = f"{u.reference} {CHANGE_LABELS.get(u.change_type, u.change_type)} published {_day(u.published_at)}"
        if u.effective_on:
            why += f", effective {_day(u.effective_on)}"
        if a.match_reason:
            why += f": {a.match_reason}"

        def link(o: Opportunity, a=a) -> None:
            if a.opportunity_id is None:
                a.opportunity_id = o.id

        out.append(Item(a.organization_id, "regulatory_updates", "regulatory_update", u.id, service=f"{u.law_name or 'Regulatory'} advisory: {u.title}"[:200],
                        service_kind="advisory", why_now=why[:300], system_ids=list(a.affected_system_ids or []), after=link))
    return out


def _year_later(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _renewal_items(db: Session, today: date) -> list[Item]:
    """(c) The latest completed engagement of each client reaches an anniversary within 90 days (or has passed it) and
    no annual review or newer engagement has been started. One opportunity per engagement and anniversary."""
    from app.engagements.models import Engagement

    clients = _clients(db)
    latest: dict[str, Engagement] = {}
    for e in db.scalars(select(Engagement).where(Engagement.status.in_(("completed", "archived")), Engagement.completed_at.is_not(None), Engagement.deleted_at.is_(None))
                        .order_by(Engagement.completed_at)):
        latest[e.client_id] = e
    limit = today + timedelta(days=RENEWAL_WINDOW_DAYS)
    out: list[Item] = []
    for org_id, e in latest.items():
        if org_id not in clients:
            continue
        newer = db.scalar(select(Engagement.id).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None), Engagement.id != e.id,
                                                      or_(Engagement.prior_engagement_id == e.id, Engagement.created_at > e.created_at)).limit(1))
        if newer:
            continue
        done = e.completed_at.date()
        years = limit.year - done.year
        while years >= 1 and _year_later(done, years) > limit:
            years -= 1
        if years < 1:
            continue
        due = _year_later(done, years)
        when = f"was due {_day(due)}" if due < today else f"due {_day(due)}"
        why = f"Annual review {when}: {e.name} completed {_day(done)} and no annual review has been started"
        out.append(Item(org_id, "renewals", "renewal_audit", f"renewal:{e.id}:{due.isoformat()}", service="Annual AI governance review (renewal audit)",
                        service_kind="audit", why_now=why[:300]))
    return out
