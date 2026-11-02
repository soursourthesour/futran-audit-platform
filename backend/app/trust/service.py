"""Trust Center (spec §21 F9, screen 32).

The client's CAICO builds the page and approves each item. A Futran Chief Auditor then confirms that the item matches
the client's signed report (status final, signed) before it is published; a claim with no signed report behind it cannot
be confirmed. This is the platform's guard against "AI washing" (FTC Act §5): the page never claims more than the audit found.

Items: commitments, published policies (from the policy builder), the LL144 bias audit summary (from `PublicSummary`),
the "Audited by Futran" badge (engagement, period and report reference; the rating band only if the client opts in),
the governance description, and rights and contact. Badge and bias summary content is built from the platform's records,
never typed. The public sees only the snapshot that was confirmed (`published_content`); editing an item puts the working
copy back to draft while the confirmed version stays up until it is withdrawn or a new version is confirmed.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.engagements.models import Engagement
from app.mail.sending import token_hash
from app.reports.models import PublicSummary, Report
from app.tenancy.models import Organization, RoleAssignment, User
from app.trust.models import ITEM_KINDS, TrustCenterItem, TrustCenterNdaAcceptance, TrustCenterPage, TrustCenterView

SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,58}[a-z0-9])$")
RESERVED = {"admin", "api", "login", "staff", "trust", "public", "new", "edit", "confirmations"}
KIND_LABELS = {"commitment": "Commitment", "policy": "Policy", "bias_summary": "Bias audit summary (NYC LL144)", "badge": "Audited by Futran",
               "governance": "Governance", "rights_contact": "Your rights and contact"}
TEXT_KINDS = ("commitment", "governance", "rights_contact")
NDA_HOURS = 24
FUTRAN = "Futran Solutions"


# ---- page
def page_for(db: Session, org_id: str) -> TrustCenterPage | None:
    return db.scalar(select(TrustCenterPage).where(TrustCenterPage.organization_id == org_id, TrustCenterPage.deleted_at.is_(None)))


def _text(v, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


def _long(v, limit: int = 4000) -> str:
    return "\n".join(" ".join(line.split()) for line in str(v or "").strip().splitlines())[:limit]


def save_page(db: Session, actor: User, org: Organization, data: dict) -> TrustCenterPage:
    p = page_for(db, org.id)
    errs = []
    slug = str(data.get("slug", p.slug if p else "") or "").strip().lower()
    if not SLUG.match(slug) or slug in RESERVED:
        errs.append({"field": "slug", "message": "Use 3 to 60 lower-case letters, numbers and hyphens, for example abc-corp."})
    title = _text(data.get("title", p.title if p else f"How {org.name} governs its use of AI"), 200)
    if not title:
        errs.append({"field": "title", "message": "Give the page a heading."})
    email = _text(data.get("contact_email", p.contact_email if p else ""), 254) or None
    if email and ("@" not in email or " " in email):
        errs.append({"field": "contact_email", "message": "Enter a valid email address, or leave it blank."})
    access = data.get("access", p.access if p else "public")
    if access not in ("public", "nda"):
        errs.append({"field": "access", "message": "Choose public or NDA click-through."})
    nda = _long(data.get("nda_text", p.nda_text if p else ""), 6000) or None
    if access == "nda" and not nda:
        errs.append({"field": "nda_text", "message": "Enter the text visitors accept before they open detailed documents."})
    if errs:
        raise Invalid(errors=errs)
    clash = db.scalar(select(TrustCenterPage.id).where(TrustCenterPage.slug == slug, TrustCenterPage.organization_id != org.id))
    if clash:
        raise Conflict("That address is already taken. Choose another.")
    before = {"slug": p.slug, "live": p.live, "access": p.access, "indexable": p.indexable} if p else None
    if p is None:
        p = TrustCenterPage(organization_id=org.id, slug=slug, title=title, created_by=actor.id)
        db.add(p)
    p.slug, p.title, p.contact_email, p.access, p.nda_text = slug, title, email, access, nda
    p.intro = _long(data.get("intro", p.intro), 2000) or None
    p.live = bool(data.get("live", p.live or False))
    p.indexable = bool(data.get("indexable", p.indexable or False))
    p.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="trust.page", obj=p, before=before, after={"slug": p.slug, "live": p.live, "access": p.access, "indexable": p.indexable},
                 summary=f"Updated the Trust Center page /trust/{p.slug}" + (" (live)" if p.live else " (not live)"))
    return p


# ---- sources the platform builds content from
def final_report(db: Session, engagement_id: str) -> Report | None:
    return db.scalar(select(Report).where(Report.engagement_id == engagement_id, Report.status == "final", Report.signed_at.is_not(None), Report.deleted_at.is_(None))
                     .order_by(Report.signed_at.desc()).limit(1))


def latest_final_report(db: Session, org_id: str) -> Report | None:
    return db.scalar(select(Report).where(Report.organization_id == org_id, Report.status == "final", Report.signed_at.is_not(None), Report.deleted_at.is_(None))
                     .order_by(Report.signed_at.desc()).limit(1))


def report_ref(db: Session, r: Report) -> str:
    e = db.get(Engagement, r.engagement_id)
    return f"{e.audit_ref or e.name} {r.version}"


def sources(db: Session, org_id: str) -> dict:
    from app.policies.models import PolicyDocument

    engs = []
    for e in db.scalars(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc())):
        r = final_report(db, e.id)
        if r is not None:
            engs.append({"id": e.id, "name": e.name, "audit_ref": e.audit_ref, "report_ref": report_ref(db, r), "signed_on": r.signed_at.date().isoformat()})
    sums = []
    for s in db.scalars(select(PublicSummary).where(PublicSummary.organization_id == org_id, PublicSummary.deleted_at.is_(None))):
        if final_report(db, s.engagement_id) is not None:
            sums.append({"id": s.id, "tool_name": s.tool_name, "audit_date": s.audit_date.isoformat() if s.audit_date else None})
    pols = [{"id": p.id, "title": p.title, "version_no": p.version_no} for p in db.scalars(select(PolicyDocument).where(
        PolicyDocument.organization_id == org_id, PolicyDocument.deleted_at.is_(None), PolicyDocument.status == "published").order_by(PolicyDocument.title))]
    return {"engagements": engs, "bias_summaries": sums, "policies": pols}


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def policy_successor(db: Session, p) -> "object | None":
    """The published version that replaced a retired policy, following the chain of versions; None if there is none."""
    from app.policies.models import PolicyDocument

    cur, seen = p, set()
    while cur is not None and cur.status != "published" and cur.id not in seen:
        seen.add(cur.id)
        cur = db.scalar(select(PolicyDocument).where(PolicyDocument.supersedes_id == cur.id, PolicyDocument.organization_id == p.organization_id,
                                                     PolicyDocument.deleted_at.is_(None), PolicyDocument.status.in_(("published", "retired")))
                        .order_by(PolicyDocument.version_no.desc()).limit(1))
    return cur if cur is not None and cur.id != p.id and cur.status == "published" else None


def content(db: Session, it: TrustCenterItem) -> dict:
    """What the item says, built from the platform's records for badge, bias summary and policy items."""
    from app.policies.models import PolicyDocument

    if it.kind in TEXT_KINDS:
        return {"title": it.title, "body": it.body or "", "link_label": it.link_label, "link_url": it.link_url}
    if it.kind == "policy":
        p = db.get(PolicyDocument, it.source_id) if it.source_id else None
        if p is None or p.organization_id != it.organization_id:
            raise Conflict("The policy is no longer published.")
        if p.status != "published":
            n = policy_successor(db, p)
            if n is not None:
                raise Conflict(f"Needs updating to version {n.version_no}: version {p.version_no} of this policy was replaced, so the item is off the public page. "
                               f"Move it to version {n.version_no}, then approve it for Futran to confirm again.")
            raise Conflict("The policy is no longer published.")
        return {"title": p.title, "body": it.body or "", "policy_id": p.id, "version_no": p.version_no, "approved_on": _iso(p.approved_at.date() if p.approved_at else None),
                "file_id": p.published_file_id, "document": bool(p.published_file_id)}
    if it.kind == "bias_summary":
        s = db.get(PublicSummary, it.source_id) if it.source_id else None
        if s is None or s.organization_id != it.organization_id or s.deleted_at is not None:
            raise Conflict("The bias audit summary is no longer available.")
        r = final_report(db, s.engagement_id)
        if r is None:
            raise Conflict("The bias audit summary has no signed report behind it.")
        return {"title": it.title or "Bias audit summary (NYC Local Law 144)", "body": it.body or "", "tool_name": s.tool_name, "audit_date": _iso(s.audit_date),
                "distribution_date": _iso(s.distribution_date), "data_source": s.data_source, "unknown_category_count": s.unknown_category_count,
                "impact_ratios": list(s.impact_ratios or []), "auditor": FUTRAN, "report_ref": report_ref(db, r)}
    if it.kind == "badge":
        from app.reports.service import RATING_LABEL

        e = db.get(Engagement, it.source_id) if it.source_id else None
        if e is None or e.client_id != it.organization_id:
            raise Conflict("The engagement is no longer available.")
        r = final_report(db, e.id)
        if r is None:
            raise Conflict("The engagement has no signed report.")
        out = {"title": f"Audited by {FUTRAN}", "body": it.body or "", "engagement": "AI governance assessment", "period_start": _iso(e.period_start),
               "period_end": _iso(e.period_end), "report_ref": report_ref(db, r), "signed_on": r.signed_at.date().isoformat()}
        if (it.options or {}).get("show_rating") and e.overall_rating:
            out["rating"] = RATING_LABEL.get(e.overall_rating, e.overall_rating)
        return out
    raise Invalid(errors=[{"field": "kind", "message": "Choose what the item shows."}])


def _source_report(db: Session, it: TrustCenterItem) -> Report | None:
    if it.kind == "badge":
        return final_report(db, it.source_id) if it.source_id else None
    if it.kind == "bias_summary":
        s = db.get(PublicSummary, it.source_id) if it.source_id else None
        return final_report(db, s.engagement_id) if s else None
    return latest_final_report(db, it.organization_id)


# ---- items
def _apply(db: Session, it: TrustCenterItem, data: dict) -> None:
    errs = []
    if it.kind in TEXT_KINDS:
        title = _text(data.get("title", it.title), 200)
        body = _long(data.get("body", it.body))
        if not title:
            errs.append({"field": "title", "message": "Give the item a heading."})
        if not body:
            errs.append({"field": "body", "message": "Write what the item says."})
        url = _text(data.get("link_url", it.link_url), 500) or None
        if url and not (url.startswith("https://") or url.startswith("mailto:")):
            errs.append({"field": "link_url", "message": "Links start with https:// or mailto:."})
        if errs:
            raise Invalid(errors=errs)
        it.title, it.body, it.link_url = title, body, url
        it.link_label = _text(data.get("link_label", it.link_label), 80) or (None if not url else "Contact us")
    else:
        if it.kind == "policy" and data.get("source_id") and data["source_id"] != it.source_id:
            from app.policies.models import PolicyDocument

            old = db.get(PolicyDocument, it.source_id) if it.source_id else None
            n = policy_successor(db, old) if old is not None else None
            if n is None or n.id != data["source_id"]:
                raise Invalid(errors=[{"field": "source_id", "message": "A policy item can only move to the current published version of the same policy."}])
            it.source_id = n.id
        it.body = _long(data.get("body", it.body), 1000) or None
        if "show_rating" in data and it.kind == "badge":
            it.options = {**(it.options or {}), "show_rating": bool(data["show_rating"])}
        c = content(db, it)
        it.title = c["title"]


def create_item(db: Session, actor: User, page: TrustCenterPage, data: dict) -> TrustCenterItem:
    kind = data.get("kind")
    if kind not in ITEM_KINDS:
        raise Invalid(errors=[{"field": "kind", "message": "Choose what the item shows."}])
    src = data.get("source_id") if kind not in TEXT_KINDS else None
    if kind not in TEXT_KINDS and not src:
        raise Invalid(errors=[{"field": "source_id", "message": "Choose the record the item is built from."}])
    if src and kind == "policy":
        from app.policies.models import PolicyDocument

        p = db.get(PolicyDocument, src)
        if p is None or p.organization_id != page.organization_id:
            raise NotFound()
    order = (db.scalar(select(TrustCenterItem.order).where(TrustCenterItem.page_id == page.id).order_by(TrustCenterItem.order.desc()).limit(1)) or 0) + 1
    it = TrustCenterItem(organization_id=page.organization_id, page_id=page.id, kind=kind, title=KIND_LABELS[kind], source_id=src, options={}, order=order,
                         status="draft", created_by=actor.id)
    _apply(db, it, data)
    db.add(it)
    db.flush()
    audit.record(db, actor_id=actor.id, action="trust.item_add", obj=it, after={"kind": kind, "source_id": src}, summary=f"Added '{it.title}' to the Trust Center")
    return it


def get_item(db: Session, org_id: str | None, item_id: str) -> TrustCenterItem:
    it = db.get(TrustCenterItem, item_id)
    if it is None or it.deleted_at is not None or (org_id is not None and it.organization_id != org_id):
        raise NotFound()
    return it


def update_item(db: Session, actor: User, it: TrustCenterItem, data: dict) -> TrustCenterItem:
    _apply(db, it, data)
    it.status, it.approved_content, it.client_approved_by, it.client_approved_at = "draft", None, None, None
    it.updated_by = actor.id
    audit.record(db, actor_id=actor.id, action="trust.item_edit", obj=it, summary=f"Edited '{it.title}' (back to draft; the confirmed version stays published)")
    return it


def chief_auditors(db: Session) -> list[User]:
    return list(db.scalars(select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).join(Organization, Organization.id == User.organization_id).where(
        Organization.type == "futran", User.deleted_at.is_(None), User.status == "active", RoleAssignment.role == "chief_auditor", RoleAssignment.deleted_at.is_(None))))


def approve_item(db: Session, settings, actor: User, it: TrustCenterItem) -> TrustCenterItem:
    from app.notifications.service import notify

    if it.status not in ("draft", "returned"):
        raise Conflict("This item is not a draft.")
    it.approved_content = content(db, it)
    it.status, it.client_approved_by, it.client_approved_at, it.return_note = "awaiting_confirmation", actor.id, utcnow(), None
    org = db.get(Organization, it.organization_id)
    notify(db, chief_auditors(db), "trust_item_to_confirm", f"{org.name}: Trust Center item to confirm", f"'{it.title}', approved by {actor.name}. Check it against the signed report.",
           "/trust-confirmations", settings=settings)
    audit.record(db, actor_id=actor.id, action="trust.item_approve", obj=it, after={"content": it.approved_content}, summary=f"Approved '{it.title}' for the Trust Center")
    return it


def confirm_item(db: Session, actor: User, it: TrustCenterItem, note: str | None) -> TrustCenterItem:
    if it.status != "awaiting_confirmation":
        raise Conflict("Only an item the client has approved can be confirmed.")
    r = _source_report(db, it)
    if r is None:
        raise Conflict("There is no signed report for this client, so the claim cannot be confirmed.")
    now_content = content(db, it)
    if now_content != it.approved_content:
        raise Conflict("The record behind this item changed after the client approved it. Return it so the client can approve it again.")
    it.status, it.confirmed_by, it.confirmed_at, it.confirmed_report_id = "published", actor.id, utcnow(), r.id
    it.confirm_note = _long(note, 2000) or None
    it.published_content, it.published_at, it.withdrawn_at = now_content, utcnow(), None
    audit.record(db, actor_id=actor.id, action="trust.confirm", obj=it, after={"report_id": r.id, "note": it.confirm_note},
                 summary=f"Confirmed '{it.title}' against {report_ref(db, r)} and published it")
    return it


def return_item(db: Session, actor: User, it: TrustCenterItem, note: str | None) -> TrustCenterItem:
    from app.notifications.service import notify

    if it.status != "awaiting_confirmation":
        raise Conflict("Only an item waiting for confirmation can be returned.")
    note = _long(note, 2000)
    if not note:
        raise Invalid(errors=[{"field": "note", "message": "Say what does not match the signed report."}])
    it.status, it.return_note = "returned", note
    who = db.get(User, it.client_approved_by) if it.client_approved_by else None
    if who is not None:
        notify(db, [who], "trust_item_returned", f"Futran returned '{it.title}'", note, "/trust")
    audit.record(db, actor_id=actor.id, action="trust.return", obj=it, after={"note": note}, summary=f"Returned '{it.title}': {note[:120]}")
    return it


def withdraw_item(db: Session, actor: User, it: TrustCenterItem) -> TrustCenterItem:
    if it.published_content is None or it.withdrawn_at is not None:
        raise Conflict("This item is not on the public page.")
    it.withdrawn_at = utcnow()
    if it.status == "published":
        it.status = "withdrawn"
    audit.record(db, actor_id=actor.id, action="trust.withdraw", obj=it, summary=f"Took '{it.title}' off the public Trust Center")
    return it


def delete_item(db: Session, actor: User, it: TrustCenterItem) -> None:
    if shown(db, it):
        raise Conflict("Withdraw the item from the public page first.")
    it.deleted_at = utcnow()
    audit.record(db, actor_id=actor.id, action="trust.item_delete", obj=it, summary=f"Removed '{it.title}' from the Trust Center editor")


def is_live(it: TrustCenterItem) -> bool:
    return it.published_content is not None and it.withdrawn_at is None


def shown(db: Session, it: TrustCenterItem) -> bool:
    """On the public page: confirmed, not withdrawn and, for a policy, the confirmed version is still the published one
    (a retired version is never presented as current)."""
    if not is_live(it):
        return False
    if it.kind == "policy":
        from app.policies.models import PolicyDocument

        pid = (it.published_content or {}).get("policy_id")
        p = db.get(PolicyDocument, pid) if pid else None
        return p is not None and p.organization_id == it.organization_id and p.deleted_at is None and p.status == "published"
    return True


def items(db: Session, page: TrustCenterPage) -> list[TrustCenterItem]:
    return list(db.scalars(select(TrustCenterItem).where(TrustCenterItem.page_id == page.id, TrustCenterItem.organization_id == page.organization_id,
                                                         TrustCenterItem.deleted_at.is_(None)).order_by(TrustCenterItem.order)))


def item_out(db: Session, it: TrustCenterItem) -> dict:
    name = lambda uid: (db.get(User, uid).name if uid and db.get(User, uid) else None)  # noqa: E731
    try:
        working = content(db, it)
        problem = None
    except Conflict as exc:
        working, problem = None, exc.detail
    update_to = None
    if it.kind == "policy" and it.source_id:
        from app.policies.models import PolicyDocument

        src = db.get(PolicyDocument, it.source_id)
        n = policy_successor(db, src) if src is not None and src.organization_id == it.organization_id else None
        update_to = {"policy_id": n.id, "version_no": n.version_no} if n is not None else None
    return {"id": it.id, "kind": it.kind, "kind_label": KIND_LABELS[it.kind], "title": it.title, "body": it.body, "link_label": it.link_label, "link_url": it.link_url,
            "source_id": it.source_id, "options": it.options or {}, "status": it.status, "live": shown(db, it), "update_to": update_to, "content": working, "problem": problem,
            "published_content": it.published_content, "client_approved_by": name(it.client_approved_by), "client_approved_at": _iso(it.client_approved_at),
            "confirmed_by": name(it.confirmed_by), "confirmed_at": _iso(it.confirmed_at), "confirmed_report_id": it.confirmed_report_id,
            "confirm_note": it.confirm_note, "return_note": it.return_note, "published_at": _iso(it.published_at)}


def views(db: Session, page: TrustCenterPage, days: int = 30) -> list[dict]:
    since = today() - timedelta(days=days - 1)
    rows = {v.day: v.views for v in db.scalars(select(TrustCenterView).where(TrustCenterView.page_id == page.id, TrustCenterView.day >= since))}
    return [{"day": (since + timedelta(days=i)).isoformat(), "views": rows.get(since + timedelta(days=i), 0)} for i in range(days)]


def page_out(p: TrustCenterPage) -> dict:
    return {"id": p.id, "slug": p.slug, "title": p.title, "intro": p.intro, "contact_email": p.contact_email, "live": p.live, "access": p.access,
            "nda_text": p.nda_text, "indexable": p.indexable, "url_path": f"/trust/{p.slug}"}


# ---- confirmations queue (Futran Chief Auditor)
def confirmation_queue(db: Session, org_ids: set[str] | None) -> list[dict]:
    out = []
    for it in db.scalars(select(TrustCenterItem).where(TrustCenterItem.status == "awaiting_confirmation", TrustCenterItem.deleted_at.is_(None)).order_by(TrustCenterItem.client_approved_at)):
        if org_ids is not None and it.organization_id not in org_ids:
            continue
        org = db.get(Organization, it.organization_id)
        r = _source_report(db, it)
        rep = None
        if r is not None:
            from app.reports.service import RATING_LABEL

            e = db.get(Engagement, r.engagement_id)
            rep = {"id": r.id, "ref": report_ref(db, r), "signed_on": r.signed_at.date().isoformat(), "engagement_id": e.id, "client_id": e.client_id,
                   "period_start": _iso(e.period_start), "period_end": _iso(e.period_end), "overall_rating": RATING_LABEL.get(e.overall_rating or "", "Not rated")}
        out.append(item_out(db, it) | {"client_id": it.organization_id, "client_name": org.name if org else "", "report": rep, "approved_content": it.approved_content})
    return out


# ---- public page
def public_page(db: Session, slug: str) -> TrustCenterPage:
    p = db.scalar(select(TrustCenterPage).where(TrustCenterPage.slug == (slug or "").lower(), TrustCenterPage.deleted_at.is_(None)))
    if p is None or not p.live:
        raise NotFound("There is no Trust Center at this address.")
    return p


def count_view(db: Session, p: TrustCenterPage) -> None:
    from sqlalchemy import update

    d = today()
    res = db.execute(update(TrustCenterView).where(TrustCenterView.page_id == p.id, TrustCenterView.day == d).values(views=TrustCenterView.views + 1))
    if res.rowcount == 0:
        db.add(TrustCenterView(organization_id=p.organization_id, page_id=p.id, day=d, views=1))
    db.flush()


PUBLIC_CONTENT_KEYS = {"title", "body", "link_label", "link_url", "version_no", "approved_on", "document", "tool_name", "audit_date", "distribution_date",
                       "data_source", "unknown_category_count", "impact_ratios", "auditor", "report_ref", "engagement", "period_start", "period_end", "signed_on", "rating"}


def public_out(db: Session, p: TrustCenterPage) -> dict:
    """Only published items, and only their confirmed snapshot. No internal ids beyond the item id, no names of staff."""
    org = db.get(Organization, p.organization_id)
    out_items = []
    for it in items(db, p):
        if not shown(db, it):
            continue
        c = {k: v for k, v in (it.published_content or {}).items() if k in PUBLIC_CONTENT_KEYS}
        out_items.append({"id": it.id, "kind": it.kind, "title": c.get("title", it.title), "body": c.get("body", ""), "content": c,
                          "gated": p.access == "nda" and bool(c.get("document"))})
    return {"slug": p.slug, "organization": org.name if org else "", "title": p.title, "intro": p.intro, "contact_email": p.contact_email, "access": p.access,
            "nda_text": p.nda_text if p.access == "nda" else None, "noindex": not p.indexable, "items": out_items, "updated_at": _iso(p.updated_at)}


def accept_nda(db: Session, p: TrustCenterPage, data: dict) -> tuple[str, datetime]:
    if p.access != "nda":
        raise Conflict("This page has no NDA.")
    errs = []
    name, email = _text(data.get("name"), 160), _text(data.get("email"), 254).lower()
    if not name:
        errs.append({"field": "name", "message": "Enter your name."})
    if "@" not in email or " " in email:
        errs.append({"field": "email", "message": "Enter your work email."})
    if data.get("accept") is not True:
        errs.append({"field": "accept", "message": "Accept the terms to continue."})
    if errs:
        raise Invalid(errors=errs)
    raw = secrets.token_urlsafe(32)
    exp = utcnow() + timedelta(hours=NDA_HOURS)
    a = TrustCenterNdaAcceptance(organization_id=p.organization_id, page_id=p.id, name=name, email=email, company=_text(data.get("company"), 200) or None,
                                 nda_text=p.nda_text, accepted_at=utcnow(), token_hash=token_hash(raw), expires_at=exp)
    db.add(a)
    db.flush()
    audit.record(db, actor_id=None, actor_name=f"{name} ({email})", action="trust.nda_accept", obj=a, organization_id=p.organization_id,
                 summary=f"{name} of {a.company or 'an unnamed company'} accepted the Trust Center NDA")
    return raw, exp


def document(db: Session, settings, p: TrustCenterPage, item_id: str, access: str | None) -> tuple[bytes, str]:
    from app.files.models import FileObject
    from app.files.service import read

    it = db.get(TrustCenterItem, item_id)
    if it is None or it.page_id != p.id or it.organization_id != p.organization_id or it.deleted_at is not None or it.kind != "policy" or not shown(db, it):
        raise NotFound()
    file_id = (it.published_content or {}).get("file_id")
    f = db.get(FileObject, file_id) if file_id else None
    if f is None or f.organization_id != p.organization_id or f.deleted_at is not None:
        raise NotFound()
    if p.access == "nda":
        a = db.scalar(select(TrustCenterNdaAcceptance).where(TrustCenterNdaAcceptance.token_hash == token_hash(access or ""))) if access else None
        if a is None or a.page_id != p.id or a.expires_at <= utcnow():
            raise Forbidden("Accept the NDA to open this document.")
    return read(settings, f), f.filename
