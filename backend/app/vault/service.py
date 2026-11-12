"""G-10 evidence vault and retention (spec B10, v0.6.1 §15).

Retention: each client has a tier of 3, 7 or 10 years (default 7, `settings.retention_years_default`). Engagement
evidence (files linked as `evidence` or `governance_document`) is due for deletion that many years after the engagement
was completed, but never sooner than the engagement letter promised (`Engagement.retention_years`, or the default the
letter states): a tier can lengthen retention, never shorten it. Reports,
packages, letters and other generated documents are not deleted by the vault. Raw applicant data of bias tests keeps its
own F11 rule (app.biascalc.retention) and shows in the countdown.

Countdown and notice: an item enters the countdown 90 days before it is due. The daily job sends one notice per client
to the Chief Auditors and the client's CAICO when items first enter it, and never deletes an item earlier than 90 days
after its notice, so an item already past its date when first seen still gets the full 90 days.

Legal holds: `hold_for` is the one check every deletion path calls (this module's daily job and the bias raw-data
purge). `org_on_hold` is for whole-organization deletions: R2's lost-prospect clean-up must call it and skip any
organization it returns True for; this module does not run that job. A held item is never deleted; it is
deleted on the first daily run after the last hold covering it is released (and its 90 days have passed).

Storage metering: `storage_used_gb` feeds G-01 usage (`vault_gb`); `active_holds` feeds `legal_holds` (M-06e).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.tenancy.models import Organization, RoleAssignment, User
from app.vault.models import TIERS, LegalHold, RetentionNotice, RetentionPolicy

log = logging.getLogger(__name__)
NOTICE_DAYS = 90
VAULT_TYPES = ("evidence", "governance_document")  # what the vault deletes at the end of retention
KIND_LABELS = {"evidence": "Evidence", "governance_document": "Governance document", "bias_raw_data": "Raw data"}


def _plus_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _d(v) -> date | None:
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


# ---------------------------------------------------------------- retention tier
def current_policy(db: Session, org_id: str, on: date | None = None) -> RetentionPolicy | None:
    on = on or today()
    return db.scalar(select(RetentionPolicy).where(RetentionPolicy.organization_id == org_id, RetentionPolicy.deleted_at.is_(None), RetentionPolicy.effective_from <= on)
                     .order_by(RetentionPolicy.effective_from.desc(), RetentionPolicy.created_at.desc()).limit(1))


def retention_years(db: Session, settings, org_id: str, on: date | None = None) -> int:
    p = current_policy(db, org_id, on)
    return p.years if p else settings.retention_years_default


def letter_years(settings, e: Engagement) -> int:
    """The retention period the engagement letter states (the initiation package uses the same rule)."""
    return e.retention_years or settings.retention_years_default


def _years_for(db: Session, settings, e: Engagement, policy: RetentionPolicy | None) -> int:
    """The client's tier can lengthen an engagement's retention but never shorten it below what its letter promised."""
    return max(policy.years if policy else 0, letter_years(settings, e))


def kept_longer_by_letter(db: Session, settings, org_id: str, years: int) -> int:
    """Engagements whose letters keep evidence longer than `years`, so a shorter tier does not apply to them."""
    return sum(1 for e in db.scalars(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None)))
               if letter_years(settings, e) > years)


def set_tier(db: Session, actor: User, org: Organization, years: int, reason: str | None, settings=None) -> RetentionPolicy:
    if years not in TIERS:
        raise Invalid(errors=[{"field": "years", "message": "Choose 3, 7 or 10 years."}])
    before = current_policy(db, org.id)
    p = RetentionPolicy(organization_id=org.id, years=years, effective_from=today(), set_by=actor.id, reason=(" ".join(str(reason or "").split()) or None),
                        created_by=actor.id)
    db.add(p)
    db.flush()
    longer = kept_longer_by_letter(db, settings, org.id, years) if settings is not None else None
    audit.record(db, actor_id=actor.id, action="vault.retention_tier", obj=p, before={"years": before.years if before else None},
                 after={"years": years, "reason": p.reason, "kept_longer_by_letter": longer},
                 summary=f"Retention tier for {org.name} set to {years} years" + (f"; {longer} engagements keep their letters' longer period" if longer else ""))
    return p


# ---------------------------------------------------------------- legal holds
def holds(db: Session, org_id: str, *, active_only: bool = False) -> list[LegalHold]:
    q = select(LegalHold).where(LegalHold.organization_id == org_id, LegalHold.deleted_at.is_(None))
    if active_only:
        q = q.where(LegalHold.released_at.is_(None))
    return list(db.scalars(q.order_by(LegalHold.set_at.desc())))


def active_holds(db: Session, org_id: str, on: date | None = None) -> int:
    return db.scalar(select(func.count(LegalHold.id)).where(LegalHold.organization_id == org_id, LegalHold.deleted_at.is_(None), LegalHold.released_at.is_(None))) or 0


def _clean_scope(db: Session, org: Organization, scope: dict | None) -> dict:
    from app.systems.models import AISystem

    scope = scope or {}
    out: dict = {}
    eids = list(dict.fromkeys(scope.get("engagement_ids") or []))
    if eids:
        own = set(db.scalars(select(Engagement.id).where(Engagement.id.in_(eids), Engagement.client_id == org.id)))
        if own != set(eids):
            raise Invalid(errors=[{"field": "scope", "message": "Choose engagements of this client."}])
        out["engagement_ids"] = eids
    sids = list(dict.fromkeys(scope.get("system_ids") or []))
    if sids:
        from app.register.models import RegisterSystem

        own = set(db.scalars(select(AISystem.id).where(AISystem.id.in_(sids), AISystem.organization_id == org.id)))
        own |= set(db.scalars(select(RegisterSystem.id).where(RegisterSystem.id.in_(sids), RegisterSystem.organization_id == org.id)))
        if own != set(sids):
            raise Invalid(errors=[{"field": "scope", "message": "Choose AI systems of this client."}])
        out["system_ids"] = sids
    for k in ("from", "to"):
        v = scope.get(k)
        if v:
            try:
                out[k] = date.fromisoformat(str(v)[:10]).isoformat()
            except ValueError as exc:
                raise Invalid(errors=[{"field": "scope", "message": "Enter dates as YYYY-MM-DD."}]) from exc
    if out.get("from") and out.get("to") and out["from"] > out["to"]:
        raise Invalid(errors=[{"field": "scope", "message": "The start date is after the end date."}])
    return out


def place_hold(db: Session, actor: User, org: Organization, *, name: str, matter_ref: str | None, reason: str, scope: dict | None) -> LegalHold:
    name = " ".join(str(name or "").split())
    reason = " ".join(str(reason or "").split())
    errs = []
    if not name:
        errs.append({"field": "name", "message": "Name the hold."})
    if not reason:
        errs.append({"field": "reason", "message": "Say why the hold is needed, for example the client counsel's request."})
    if errs:
        raise Invalid(errors=errs)
    clean = _clean_scope(db, org, scope)
    n = db.scalar(select(func.count(LegalHold.id)).where(LegalHold.organization_id == org.id)) or 0
    h = LegalHold(organization_id=org.id, ref=f"LH-{n + 1:03d}", name=name[:200], matter_ref=(str(matter_ref or "").strip()[:200] or None), reason=reason[:4000],
                  scope=clean, set_by=actor.id, set_at=utcnow(), created_by=actor.id)
    db.add(h)
    db.flush()
    audit.record(db, actor_id=actor.id, action="vault.hold_placed", obj=h, after={"ref": h.ref, "matter_ref": h.matter_ref, "scope": clean, "reason": h.reason},
                 summary=f"Legal hold {h.ref} placed on {org.name}: {scope_label(db, h)}")
    return h


def release_hold(db: Session, actor: User, h: LegalHold, reason: str) -> LegalHold:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise Invalid(errors=[{"field": "reason", "message": "Say why the hold is released."}])
    if h.released_at is not None:
        raise Conflict("This hold has already been released.")
    h.released_at, h.released_by, h.release_reason, h.updated_by = utcnow(), actor.id, reason[:4000], actor.id
    audit.record(db, actor_id=actor.id, action="vault.hold_released", obj=h, after={"reason": h.release_reason}, summary=f"Legal hold {h.ref} released: {reason[:200]}")
    return h


def _matches(h: LegalHold, engagement_id: str | None, system_ids, on_date: date | None) -> bool:
    sc = h.scope or {}
    if sc.get("engagement_ids") and engagement_id not in sc["engagement_ids"]:
        return False
    if sc.get("system_ids") and not (set(system_ids or ()) & set(sc["system_ids"])):
        return False
    if (sc.get("from") or sc.get("to")) and on_date is not None:
        if sc.get("from") and on_date < date.fromisoformat(sc["from"]):
            return False
        if sc.get("to") and on_date > date.fromisoformat(sc["to"]):
            return False
    return True  # an item with no date is held by a dated hold: when in doubt, keep


def hold_for(db: Session, org_id: str, *, engagement_id: str | None = None, system_ids=(), on_date: date | None = None) -> LegalHold | None:
    """The active legal hold covering an item, or None. Every deletion path calls this before deleting anything."""
    for h in holds(db, org_id, active_only=True):
        if _matches(h, engagement_id, system_ids, on_date):
            return h
    return None


def org_on_hold(db: Session, org_id: str) -> bool:
    """Whether any legal hold is active for the organization: a whole-organization deletion must not run."""
    return active_holds(db, org_id) > 0


def file_hold(db: Session, f: FileObject) -> LegalHold | None:
    return hold_for(db, f.organization_id, engagement_id=f.engagement_id, system_ids=_file_systems(db, f), on_date=_d(f.created_at))


def _file_systems(db: Session, f: FileObject) -> list[str]:
    from app.systems.models import AISystem

    if not f.linked_id:
        return []
    out = [f.linked_id]
    s = db.get(AISystem, f.linked_id)
    if s is not None and s.register_system_id:
        out.append(s.register_system_id)
    return out


def run_systems(db: Session, run) -> list[str]:
    from app.systems.models import AISystem

    s = db.get(AISystem, run.ai_system_id)
    return [run.ai_system_id] + ([s.register_system_id] if s is not None and s.register_system_id else [])


def scope_label(db: Session, h: LegalHold) -> str:
    from app.register.models import RegisterSystem
    from app.systems.models import AISystem

    sc = h.scope or {}
    parts = []
    if sc.get("engagement_ids"):
        names = [e.name for e in db.scalars(select(Engagement).where(Engagement.id.in_(sc["engagement_ids"])))]
        parts.append("Engagements: " + ", ".join(names))
    else:
        parts.append("All engagements")
    if sc.get("system_ids"):
        names = [s.name for s in db.scalars(select(AISystem).where(AISystem.id.in_(sc["system_ids"])))]
        names += [s.name for s in db.scalars(select(RegisterSystem).where(RegisterSystem.id.in_(sc["system_ids"])))]
        parts.append("systems: " + ", ".join(names))
    if sc.get("from") and sc.get("to"):
        parts.append(f"items from {sc['from']} to {sc['to']}")
    elif sc.get("from"):
        parts.append(f"items since {sc['from']}")
    elif sc.get("to"):
        parts.append(f"items up to {sc['to']}")
    return "; ".join(parts)


# ---------------------------------------------------------------- items and the countdown
def _items(db: Session, settings, org_id: str) -> list[dict]:
    """Everything with a retention date for one client: engagement evidence and raw bias-test data."""
    from app.biascalc.models import BiasTestRun
    from app.biascalc.service import raw_delete_on

    policy = current_policy(db, org_id)
    engs = {e.id: e for e in db.scalars(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None), Engagement.completed_at.is_not(None)))}
    out = []
    if engs:
        for f in db.scalars(select(FileObject).where(FileObject.organization_id == org_id, FileObject.deleted_at.is_(None), FileObject.engagement_id.in_(list(engs)),
                                                     FileObject.linked_type.in_(VAULT_TYPES))):
            e = engs[f.engagement_id]
            out.append({"item_type": "file", "item_id": f.id, "file": f, "filename": f.filename, "kind": KIND_LABELS[f.linked_type], "engagement_id": e.id,
                        "engagement": e.name, "due_on": _plus_years(e.completed_at.date(), _years_for(db, settings, e, policy)), "size": f.size,
                        "systems": _file_systems(db, f), "item_date": _d(f.created_at)})
    for run in db.scalars(select(BiasTestRun).where(BiasTestRun.organization_id == org_id, BiasTestRun.deleted_at.is_(None), BiasTestRun.raw_deleted_at.is_(None),
                                                    BiasTestRun.dataset_file_id.is_not(None))):
        if run.keep_raw_data:
            continue
        due = raw_delete_on(db, settings, run)
        if due is None:
            continue
        e = db.get(Engagement, run.engagement_id)
        out.append({"item_type": "bias_raw_data", "item_id": run.id, "file": None, "filename": run.dataset_filename or "Applicant data", "kind": KIND_LABELS["bias_raw_data"],
                    "engagement_id": run.engagement_id, "engagement": e.name if e else "", "due_on": due, "size": None, "systems": run_systems(db, run),
                    "item_date": _d(run.created_at)})
    return out


def _notice(db: Session, it: dict) -> RetentionNotice | None:
    return db.scalar(select(RetentionNotice).where(RetentionNotice.item_type == it["item_type"], RetentionNotice.item_id == it["item_id"]))


def _delete_on(it: dict, notice: RetentionNotice | None, on: date) -> date:
    if notice is not None:
        return notice.delete_on
    if it["item_type"] == "bias_raw_data":
        return it["due_on"]  # the F11 job deletes raw data on its date
    return max(it["due_on"], on + timedelta(days=NOTICE_DAYS))


def countdown(db: Session, settings, org: Organization, on: date | None = None, days: int = NOTICE_DAYS) -> list[dict]:
    """Items due for deletion within `days`, held items included (with the hold), nearest first."""
    on = on or today()
    rows = []
    for it in _items(db, settings, org.id):
        if it["due_on"] > on + timedelta(days=days):
            continue
        n = _notice(db, it)
        h = hold_for(db, org.id, engagement_id=it["engagement_id"], system_ids=it["systems"], on_date=it["item_date"])
        rows.append({"item_type": it["item_type"], "id": it["item_id"], "filename": it["filename"], "kind": it["kind"], "engagement_id": it["engagement_id"],
                     "engagement": it["engagement"], "due_on": it["due_on"].isoformat(), "delete_on": _delete_on(it, n, on).isoformat(),
                     "notified_on": n.notified_on.isoformat() if n else None, "hold": h.ref if h else None, "size": it["size"]})
    return sorted(rows, key=lambda r: (r["delete_on"], r["filename"]))


# ---------------------------------------------------------------- daily job
def _caicos(db: Session, org_id: str) -> list[User]:
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(
        User.organization_id == org_id, RoleAssignment.role == "caico", RoleAssignment.deleted_at.is_(None), User.deleted_at.is_(None))))


def _delete_file(db: Session, settings, f: FileObject, it: dict, now: datetime) -> None:
    from app.ai.models import DocumentText
    from app.files.storage import get_storage

    with db.begin_nested():  # the bytes go last, so a failure leaves the database as it was
        for dt in db.scalars(select(DocumentText).where(DocumentText.file_id == f.id)):
            db.delete(dt)
        f.deleted_at = now
        audit.record(db, actor_id=None, actor_name="Scheduler", action="vault.retention_deleted", obj=f,
                     after={"filename": f.filename, "due_on": it["due_on"].isoformat(), "engagement": it["engagement"]},
                     summary=f"Deleted {f.filename} ({it['engagement']}) at the end of the retention period")
        db.flush()
        get_storage(settings).delete(f.storage_key)


def run_daily(db: Session, settings, now) -> int:
    """Send notices for items entering the 90-day countdown and delete evidence whose notice period is over, unless a
    legal hold covers it. Returns the number of files deleted."""
    from app.commercial.common import users_with_roles
    from app.notifications.service import notify

    now = now if isinstance(now, datetime) else datetime.combine(now, datetime.min.time())
    on = now.date()
    deleted = 0
    org_ids = set(db.scalars(select(Engagement.client_id).where(Engagement.completed_at.is_not(None), Engagement.deleted_at.is_(None))))
    from app.biascalc.models import BiasTestRun

    org_ids |= set(db.scalars(select(BiasTestRun.organization_id).where(BiasTestRun.raw_deleted_at.is_(None), BiasTestRun.dataset_file_id.is_not(None))))
    for org_id in sorted(org_ids):
        org = db.get(Organization, org_id)
        if org is None or org.deleted_at is not None:
            continue
        new_notices: list[RetentionNotice] = []
        for it in _items(db, settings, org_id):
            if it["due_on"] > on + timedelta(days=NOTICE_DAYS):
                continue
            n = _notice(db, it)
            if n is None:
                n = RetentionNotice(organization_id=org_id, item_type=it["item_type"], item_id=it["item_id"], engagement_id=it["engagement_id"], due_on=it["due_on"],
                                    delete_on=_delete_on(it, None, on), notified_on=on)
                db.add(n)
                new_notices.append(n)
                continue  # never deleted on the day of its notice
            if it["item_type"] != "file" or n.delete_on > on:
                continue
            if hold_for(db, org_id, engagement_id=it["engagement_id"], system_ids=it["systems"], on_date=it["item_date"]) is not None:
                continue
            try:
                _delete_file(db, settings, it["file"], it, now)
                deleted += 1
            except Exception:
                log.exception("Could not delete %s at the end of retention; it is retried on the next run", it["item_id"])
        if new_notices:
            db.flush()
            first = min(n.delete_on for n in new_notices)
            k = len(new_notices)
            title = f"{org.name}: {k} item{'s' if k != 1 else ''} will be deleted at the end of the retention period"
            body = (f"The first deletion is on {first.isoformat()}, at least 90 days from today. Items under a legal hold are kept. "
                    "Ask the Chief Auditor for a legal hold if anything must be kept.")
            notify(db, users_with_roles(db, ["chief_auditor"]), "retention_notice", title, body, f"/staff/clients/{org.id}/vault", settings=settings)
            notify(db, _caicos(db, org.id), "retention_notice", title, body, None, settings=settings)
            audit.record(db, actor_id=None, actor_name="Scheduler", action="vault.retention_notice", obj=org, after={"items": k, "first_delete_on": first.isoformat()},
                         summary=f"Deletion notice: {k} items, first deletion on {first.isoformat()}")
    db.flush()
    return deleted


# ---------------------------------------------------------------- storage metering (G-01)
def storage_used_bytes(db: Session, org_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(FileObject.size), 0)).where(FileObject.organization_id == org_id, FileObject.deleted_at.is_(None))) or 0)


def storage_used_gb(db: Session, org_id: str) -> float:
    return round(storage_used_bytes(db, org_id) / 1024 ** 3, 2)
