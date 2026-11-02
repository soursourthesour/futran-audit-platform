"""Monitoring checks owned by WS-J (spec §21 F3): commitment overdue, vendor SOC 2 report expiring, policy older than 12
months. Each reads audit data only."""
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import today, utcnow
from app.monitoring.registry import CheckOutcome, register_check

COMMITMENT_WARN_DAYS = 14
SOC2_WARN_DAYS = 30
POLICY_MAX_DAYS = 365
POLICY_WARN_DAYS = 30
SOC2_CODE = "DR-603"
NOT_OPEN = ("draft", "pending_approval", "completed", "archived")


def _d(v) -> str:
    return f"{v.day} {v:%b %Y}"


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


# ---- commitments (governance §10.5: what the client undertook to create or constitute)
def commitment_overdue(db, org) -> list[CheckOutcome]:
    from app.governance.models import Commitment

    t = today()
    out = []
    for c in db.scalars(select(Commitment).where(Commitment.organization_id == org.id, Commitment.deleted_at.is_(None)).order_by(Commitment.target_date)):
        label = c.description
        if c.status in ("closed", "awaiting_verification"):
            out.append(CheckOutcome(c.id, label, "healthy", "Done." if c.status == "closed" else "Marked done; waiting for Futran to verify.", "/remediation"))
            continue
        left = (c.target_date - t).days
        if left < 0:
            out.append(CheckOutcome(c.id, label, "failed", f"Overdue: due {_d(c.target_date)} ({_days(-left)} ago). Owner: {c.owner}.", "/remediation", action="open"))
        elif left <= COMMITMENT_WARN_DAYS:
            out.append(CheckOutcome(c.id, label, "attention", f"Due in {_days(left)} ({_d(c.target_date)}). Owner: {c.owner}.", "/remediation", action="open"))
        else:
            out.append(CheckOutcome(c.id, label, "healthy", f"Due {_d(c.target_date)}. Owner: {c.owner}.", "/remediation"))
    return out


# ---- vendor SOC 2 reports (the document request register, DR-603, with the expiry date recorded on it)
def _soc2_rows(db, org):
    """Received SOC 2 reports, the newest for each vendor system only: a report superseded by one received on a later
    engagement is no longer watched."""
    from app.docrequests.models import DocumentRequest
    from app.reference.models import DocumentCatalogItem

    from app.engagements.models import Engagement

    item = db.scalar(select(DocumentCatalogItem).where(DocumentCatalogItem.code == SOC2_CODE))
    if item is None:
        return []
    rows = list(db.scalars(select(DocumentRequest).where(DocumentRequest.organization_id == org.id, DocumentRequest.catalog_item_id == item.id,
                                                         DocumentRequest.deleted_at.is_(None), DocumentRequest.status == "received")))
    started = {e.id: e.created_at for e in db.scalars(select(Engagement).where(Engagement.id.in_({r.engagement_id for r in rows})))}
    mapped: dict[tuple[str, str | None], str | None] = {}

    def same(eid: str, system_id: str | None) -> str | None:
        if (eid, system_id) not in mapped:
            mapped[(eid, system_id)] = _same_system(db, eid, system_id)
        return mapped[(eid, system_id)]

    def superseded(r) -> bool:
        # a report received on a later engagement, in the place a new request for this one goes (see request_new_report)
        return any(z.engagement_id != r.engagement_id and started[z.engagement_id] > started[r.engagement_id] and z.ai_system_id == same(z.engagement_id, r.ai_system_id)
                   for z in rows)

    return [r for r in rows if not superseded(r)]


def _soc2_label(db, r) -> str:
    from app.systems.models import AISystem, Vendor

    s = db.get(AISystem, r.ai_system_id) if r.ai_system_id else None
    v = db.get(Vendor, s.vendor_id) if s is not None and s.vendor_id else None
    if v is not None:
        return f"{v.legal_name} SOC 2 report"
    if s is not None:
        return f"SOC 2 report for {s.reference_id} {s.name}"
    return "Vendor SOC 2 report"


def vendor_soc2_expiring(db, org) -> list[CheckOutcome]:
    t = today()
    out = []
    for r in _soc2_rows(db, org):
        label = _soc2_label(db, r)
        if r.expires_on is None:
            out.append(CheckOutcome(r.id, label, "not_started", "Record when this report expires so it can be watched.", "/documents"))
            continue
        left = (r.expires_on - t).days
        if left < 0:
            out.append(CheckOutcome(r.id, label, "failed", f"Expired on {_d(r.expires_on)}.", "/documents", action="request_report"))
        elif left <= SOC2_WARN_DAYS:
            out.append(CheckOutcome(r.id, label, "attention", f"Expires in {_days(left)} ({_d(r.expires_on)}).", "/documents", action="request_report"))
        else:
            out.append(CheckOutcome(r.id, label, "healthy", f"Valid until {_d(r.expires_on)}.", "/documents"))
    return out


def _same_system(db, engagement_id: str, old_system_id: str | None) -> str | None:
    """The newer engagement's system for the same register system (or, failing that, the same name)."""
    from app.systems.models import AISystem

    old = db.get(AISystem, old_system_id) if old_system_id else None
    if old is None:
        return None
    rows = list(db.scalars(select(AISystem).where(AISystem.engagement_id == engagement_id, AISystem.deleted_at.is_(None))))
    hit = next((s for s in rows if old.register_system_id and s.register_system_id == old.register_system_id), None) or next((s for s in rows if s.name == old.name), None)
    return hit.id if hit else None


def _open_engagement(db, org):
    """The client's newest engagement that is under way. A completed or archived engagement's records are signed."""
    from app.engagements.models import Engagement

    return db.scalar(select(Engagement).where(Engagement.client_id == org.id, Engagement.deleted_at.is_(None), Engagement.status.not_in(NOT_OPEN))
                     .order_by(Engagement.created_at.desc()).limit(1))


def request_new_report(db, settings, user, org, result) -> str:
    """Ask for the new report on the client's open engagement: a pending document request due in 30 days. The register
    holds one request per engagement, item and system, so when the open engagement already has this row it is asked
    again (pending, new due date, expiry cleared) and keeps the earlier report's files. A completed or archived
    engagement's register is never changed: with no engagement under way nothing is written, and the person is told the
    report is requested with the next engagement's documents."""
    from app.audit_log import service as audit
    from app.core.errors import Conflict
    from app.docrequests.models import DocumentRequest

    old = db.get(DocumentRequest, result.object_id)
    if old is None or old.organization_id != org.id:
        raise ValueError("The report this result refers to no longer exists.")
    e = _open_engagement(db, org)
    if e is None:
        raise Conflict("No engagement is under way, and a completed audit's document register stays as it was signed. Ask the vendor for its current "
                       "SOC 2 report now; Futran requests it with the documents for your next engagement, and you upload it then.")
    eid = e.id
    system_id = old.ai_system_id if eid == old.engagement_id else _same_system(db, eid, old.ai_system_id)
    q = select(DocumentRequest).where(DocumentRequest.engagement_id == eid, DocumentRequest.catalog_item_id == old.catalog_item_id, DocumentRequest.deleted_at.is_(None))
    q = q.where(DocumentRequest.ai_system_id.is_(None) if system_id is None else DocumentRequest.ai_system_id == system_id)
    row = db.scalar(q)
    if row is not None and row.id != old.id and row.status == "received":
        raise Conflict(f"A newer report is already on file on your Documents page (received {_d(row.received_at or row.requested_at)}). It was not reopened.")
    due = today() + timedelta(days=30)
    if row is None:
        row = DocumentRequest(organization_id=org.id, engagement_id=eid, catalog_item_id=old.catalog_item_id, ai_system_id=system_id, requested_at=utcnow(),
                              due_at=due, status="pending", evidence_ids=[], created_by=user.id)
        db.add(row)
    else:
        row.status, row.due_at, row.requested_at, row.expires_on, row.received_at, row.due_warned_at = "pending", due, utcnow(), None, None, None
    db.flush()
    audit.record(db, actor_id=user.id, action="document_request.requested_again", obj=row, summary=f"Requested a new {_soc2_label(db, old)} (monitoring), due {_d(due)}")
    return f"A new report is requested on your Documents page, due {_d(due)}. Upload it there when the vendor sends it."


# ---- policies (the governance documents the client has in place, dated by their newest uploaded file)
def policy_older_than_12_months(db, org) -> list[CheckOutcome]:
    from app.files.models import FileObject
    from app.governance.models import GovernanceItem

    latest: dict[str, GovernanceItem] = {}
    for gi in db.scalars(select(GovernanceItem).where(GovernanceItem.organization_id == org.id, GovernanceItem.deleted_at.is_(None),
                                                      GovernanceItem.kind.in_(["document", "security_document"]), GovernanceItem.status == "in_place")
                         .order_by(GovernanceItem.created_at)):
        if "policy" in (gi.title or "").lower() and gi.file_ids:
            latest[gi.catalog_code] = gi
    t = today()
    out = []
    for gi in latest.values():
        dates = [f.created_at.date() for f in (db.get(FileObject, i) for i in gi.file_ids or []) if f is not None and f.deleted_at is None]
        if not dates:
            continue
        age = (t - max(dates)).days
        when = _d(max(dates))
        if age > POLICY_MAX_DAYS:
            out.append(CheckOutcome(gi.id, gi.title, "failed", f"Latest version uploaded {when}, more than 12 months ago. Review and upload the current version.",
                                    "/governance", action="open"))
        elif age > POLICY_MAX_DAYS - POLICY_WARN_DAYS:
            out.append(CheckOutcome(gi.id, gi.title, "attention", f"Latest version uploaded {when}; 12 months in {_days(POLICY_MAX_DAYS - age)}.", "/governance", action="open"))
        else:
            out.append(CheckOutcome(gi.id, gi.title, "healthy", f"Latest version uploaded {when}.", "/governance"))
    return out


register_check("commitment_overdue", "Commitment overdue", "high", "monthly", "commitment", commitment_overdue)
register_check("vendor_soc2_expiring", "Vendor SOC 2 report expiring", "medium", "monthly", "vendor", vendor_soc2_expiring, on_action=request_new_report)
register_check("policy_older_than_12_months", "Policy older than 12 months", "medium", "monthly", "policy", policy_older_than_12_months)
