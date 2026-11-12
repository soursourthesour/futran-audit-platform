"""Send, reminders, view tracking and acceptance (SM-10, SM-12; spec §4.6, §4.10).

Token-link pattern (as SM-07 and the email links): a random 256-bit token per contact, stored only as its SHA-256 hash,
for this one purpose, expiring at the end of the proposal's last valid day, rate limited, no sign-in. A reminder carries a
fresh link and the old one stops working; sending a newer version retires the older version's links. The link shows
that one proposal version and nothing else.

Emails go from the rep's own mailbox when connected, else Futran's mailbox, SMTP or the outbox. With real email on, the
readable copy kept in the outbox has the link removed. "Opened" means the link was opened; there are no pixels."""
import html as html_lib
import re
import secrets
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.config import Settings
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.mail.sending import token_hash
from app.proposals import approvals, document
from app.proposals import service as ps
from app.proposals.models import Acceptance, Proposal, ProposalEvent, ProposalLink
from app.tenancy.models import Organization, User

MAX_RECIPIENTS = 10
SUBMITS_PER_MINUTE = 10
VIEWS_PER_MINUTE = 60
NOT_OPENED_DAYS = 3
EXPIRING_DAYS = 5
LIVE = ("sent", "viewed", "changes_requested")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_SUBJECT = "Proposal from Futran Solutions for [Company]"
DEFAULT_MESSAGE = ("Hi [First name],\n\nAttached is our proposal for the AI governance work we discussed. You can review and accept it online "
                   "with the link below.\n\n[Rep name] · Futran Solutions")


class Gone(AppError):
    status_code = 410


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def futran_org(db: Session) -> Organization:
    return db.scalar(select(Organization).where(Organization.type == "futran").order_by(Organization.created_at).limit(1))


def _event(db: Session, p: Proposal, kind: str, *, by: User | None = None, by_name: str | None = None, link: ProposalLink | None = None,
           detail: str | None = None) -> ProposalEvent:
    ev = ProposalEvent(proposal_id=p.id, kind=kind, by_id=by.id if by else None, by_name=by_name or (by.name if by else None), link_id=link.id if link else None,
                       detail=detail)
    db.add(ev)
    db.flush()
    return ev


def _first(name: str) -> str:
    return (name or "").split()[0] if (name or "").strip() else "there"


def _merge(text: str, values: dict) -> str:
    return re.sub(r"\[([A-Za-z ]+)\]", lambda m: values.get(m.group(1), m.group(0)), text or "")


def _render(body: str, link: str, expires: str, values: dict) -> tuple[str, str]:
    from app.mail.service import render_layout

    paras = [p.strip() for p in (body or "").replace("\r\n", "\n").split("\n\n") if p.strip()]
    if "[Link]" not in paras:
        paras.insert(min(2, len(paras)), "[Link]")
    h, t = [], []
    for p in paras:
        if p == "[Link]":
            h.append(f'<p style="margin:24px 0"><a href="{html_lib.escape(link)}" style="background:#1B3A6B;color:#ffffff;padding:12px 20px;'
                     f'text-decoration:none;display:inline-block">Review and accept the proposal</a></p>'
                     f'<p style="font-size:13px;color:#5b6474">This link is personal to you and works until {html_lib.escape(expires)}.</p>')
            t.append(f"Review and accept the proposal: {link}\nThis link is personal to you and works until {expires}.")
            continue
        merged = _merge(p, values)
        h.append("<p>" + "<br>".join(html_lib.escape(line) for line in merged.split("\n")) + "</p>")
        t.append(merged)
    return render_layout("\n".join(h)), "\n\n".join(t) + "\n"


def _deliver(db: Session, settings: Settings, p: Proposal, link: ProposalLink, rep: User, subject: str, body: str, url: str, *, reminder: bool) -> None:
    """One email from the rep's mailbox, recorded in the email log (same path as the SM-07 questionnaire links)."""
    from app.mail import adminlog, delivery
    from app.mail.models import MailRecipient, MailSend, MailThread
    from app.mail.sending import next_subject_ref

    org = futran_org(db)
    values = document.merge_values(db, p) | {"First name": _first(link.name), "Rep name": rep.name}
    expires = document.fmt_day(p.valid_until)
    sender = delivery.resolve_sender(db, settings, org.id, prefer="me", user_id=rep.id)
    now = utcnow()
    subject = delivery.one_line(_merge(subject, values))[:280]
    ms = MailSend(organization_id=org.id, kind="reminder" if reminder else "system", mode="direct", template_key="proposal_send",
                  template_name="Proposal" + (" reminder" if reminder else ""), subject=subject, channel=sender.channel, sender_label=sender.label,
                  sender_connection_id=sender.connection.id if sender.connection else None,
                  sender_user_id=rep.id if sender.user_connection is not None else None, recipient_count=1, sent_by=rep.id, sent_by_name=rep.name,
                  related_type="ProposalLink", related_id=link.id, status="queued", retain_until=adminlog.retain_until(now), created_by=rep.id,
                  link_days=p.valid_days or 30)
    db.add(ms)
    db.flush()
    if sender.is_provider:  # replies come back to the rep's thread
        ref = next_subject_ref(db)
        db.add(MailThread(organization_id=org.id, send_id=ms.id, connection_id=ms.sender_connection_id, subject_ref=ref,
                          user_connection_id=sender.user_connection.id if sender.user_connection is not None else None))
        subject = f"{subject} [{ref}]"
    html, text = _render(body, url, expires, values)
    env = delivery.Envelope(to=[link.email], subject=subject, html=html, text=text)
    stored = None
    if settings.email_mode != "outbox":
        sh, st = _render(body, "(personal link sent to the recipient, not stored)", expires, values)
        stored = delivery.Envelope(to=[link.email], subject=subject, html=sh, text=st)
    msg = delivery.record(db, organization_id=org.id, env=env, stored=stored, template_key="proposal_send", related=link, actor_id=rep.id,
                          mail_send_id=ms.id, channel=sender.channel)
    res = delivery.deliver(db, settings, sender, env, msg)
    db.add(MailRecipient(organization_id=org.id, send_id=ms.id, email=link.email.lower(), name=link.name, status="sent" if res.ok else "bounced",
                         error=None if res.ok else res.error, provider_message_id=res.provider_message_id, provider_thread_id=res.provider_thread_id,
                         last_event_at=now, attempts=1))
    ms.status, ms.sent_at = "sent", now
    link.mail_send_id = ms.id
    db.flush()
    adminlog.write(db, organization_id=org.id, category="send", action="system_send", actor_name=rep.name, send_id=ms.id,
                   summary=f"{ms.template_name} to {link.email}" + ("" if res.ok else " (not delivered)"))
    if not res.ok:
        _event(db, p, "not_delivered", by=rep, link=link, detail=res.error)


def _expiry(p: Proposal) -> datetime:
    return datetime.combine(p.valid_until + timedelta(days=1), time.min)


def _issue(db: Session, settings: Settings, p: Proposal, name: str, email: str, rep: User) -> tuple[ProposalLink, str]:
    raw = new_token()
    link = ProposalLink(proposal_id=p.id, name=name, email=email.lower(), token_hash=token_hash(raw), expires_at=_expiry(p), sent_by=rep.id)
    db.add(link)
    db.flush()
    return link, f"{settings.base_url}/p/{raw}"


def _recipients(raw) -> list[tuple[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise Invalid(errors=[{"field": "recipients", "message": "Add at least one person to send the proposal to."}])
    if len(raw) > MAX_RECIPIENTS:
        raise Invalid(errors=[{"field": "recipients", "message": f"Send to up to {MAX_RECIPIENTS} people."}])
    out, seen = [], set()
    for r in raw:
        name = " ".join(str((r or {}).get("name") or "").split())[:200]
        email = str((r or {}).get("email") or "").strip().lower()
        if not EMAIL.match(email) or len(email) > 254:
            raise Invalid(errors=[{"field": "recipients", "message": f"\"{email or 'blank'}\" is not an email address."}])
        if email in seen:
            continue
        seen.add(email)
        out.append((name or email.split("@")[0], email))
    return out


def preflight(db: Session, p: Proposal) -> list[dict]:
    """What stops this version being sent now (empty when it can go)."""
    out = []
    versions = ps.thread(db, p.thread_id)
    if versions[-1].id != p.id:
        out.append({"rule": "VERSION", "message": f"Version {versions[-1].version} is the latest. Send that one."})
    if not p.editable:
        out.append({"rule": "SENT", "message": f"Version {p.version} was already sent. Start a new version to send again."})
    if not [ln for ln in document.offered(ps.lines(db, p))]:
        out.append({"rule": "EMPTY", "message": "Add at least one priced line."})
    for r in approvals.unmet(db, p):
        state = {"missing": "not requested", "pending": "waiting", "returned": "returned", "outdated": "given for an earlier draft"}.get(r.get("state"), "")
        out.append({"rule": r["rule"], "message": f"{r['rule']} · {r['message']}" + (f" Approval {state}." if r["kind"] == "approval" else "")})
    return out


def send(db: Session, settings: Settings, rep: User, p: Proposal, *, recipients, subject: str | None = None, message: str | None = None) -> list[ProposalLink]:
    """Freeze the version, store its PDF and Word files, email each contact a personal acceptance link. Every rule is
    checked here, whatever the screen showed."""
    from app.files.service import upload
    from app.sales.models import Opportunity

    people = _recipients(recipients)
    problems = preflight(db, p)
    if problems:
        raise Conflict("This version can't be sent yet: " + " ".join(x["message"] for x in problems))
    subject = (subject or DEFAULT_SUBJECT).strip()[:250] or DEFAULT_SUBJECT
    message = (message or DEFAULT_MESSAGE).replace("\r\n", "\n").strip()[:8000] or DEFAULT_MESSAGE
    now = utcnow()
    p.valid_until = today() + timedelta(days=p.valid_days or 30)
    p.status, p.sent_at, p.sent_by = "sent", now, rep.id
    db.flush()
    org = futran_org(db)
    files = {}
    for kind, data, ctype in (("pdf", document.to_pdf(db, p), "application/pdf"),
                              ("docx", document.to_docx(db, p), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")):
        files[kind] = upload(db, settings, rep, data=data, filename=document.filename(db, p, kind), content_type=ctype, organization_id=org.id,
                             linked_type="Proposal", linked_id=p.id).id
    p.file_ids = files
    for older in ps.thread(db, p.thread_id):
        if older.id != p.id and older.status in LIVE + ("draft", "awaiting_approval", "approved"):
            older.status = "superseded"
            for ln in db.scalars(select(ProposalLink).where(ProposalLink.proposal_id == older.id, ProposalLink.revoked_at.is_(None))):
                ln.revoked_at = now
    links = []
    for name, email in people:
        link, url = _issue(db, settings, p, name, email, rep)
        _deliver(db, settings, p, link, rep, subject, message, url, reminder=False)
        _event(db, p, "sent", by=rep, link=link, detail=f"To {name} <{email}>")
        links.append(link)
    opp = db.get(Opportunity, p.opportunity_id)
    company = document.merge_values(db, p)["Company"]
    if opp is not None:
        ps._log_opp(db, opp, f"Proposal v{p.version} sent to {', '.join(e for _, e in people)}; valid until {document.fmt_day(p.valid_until)}.", rep)
    audit.record(db, actor_id=rep.id, action="proposal.send", organization_id=rep.organization_id, object_type="Proposal", object_id=p.id,
                 summary=f"{company} proposal v{p.version} sent to {len(people)} contact{'s' if len(people) != 1 else ''}")
    db.flush()
    return links


def remind(db: Session, settings: Settings, rep: User, p: Proposal, link_id: str, message: str | None = None) -> ProposalLink:
    old = db.get(ProposalLink, link_id)
    if old is None or old.proposal_id != p.id:
        raise NotFound()
    if p.status not in LIVE:
        raise Conflict("Only a sent proposal that is still open can have a reminder.")
    if old.revoked_at is not None:
        raise Conflict("This link was already replaced. Remind from the latest link.")
    now = utcnow()
    if p.valid_until is None or _expiry(p) <= now:
        raise Conflict("This proposal has expired. Start a new version.")
    link, url = _issue(db, settings, p, old.name, old.email, rep)
    old.revoked_at, old.replaced_by_id = now, link.id
    body = message or ("Hi [First name],\n\nA reminder about our proposal for [Company]. It is valid until [Valid until]; you can review and accept "
                       "it with the link below.\n\n[Rep name] · Futran Solutions")
    _deliver(db, settings, p, link, rep, "Reminder: proposal from Futran Solutions for [Company]", body, url, reminder=True)
    _event(db, p, "reminder", by=rep, link=link, detail=f"To {link.name} <{link.email}>")
    return link


# ---- the client's link
def resolve(db: Session, raw: str) -> tuple[ProposalLink, Proposal]:
    link = db.scalar(select(ProposalLink).where(ProposalLink.token_hash == token_hash(raw or "")).limit(1)) if raw and len(raw) < 200 else None
    if link is None:
        raise NotFound("This link is not valid. Use the link in your most recent email.")
    p = db.get(Proposal, link.proposal_id)
    if p.status == "accepted":
        return link, p  # the record of what was accepted stays readable
    if link.revoked_at is not None or p.status == "superseded":
        raise Gone("This link has been replaced by a newer one. Use the link in your most recent email.")
    if link.expires_at <= utcnow() or p.status == "expired":
        raise Gone("This proposal has expired. Ask your Futran contact for a new one.")
    return link, p


def _owner(db: Session, p: Proposal) -> User | None:
    from app.sales.models import Opportunity

    opp = db.get(Opportunity, p.opportunity_id)
    return db.get(User, opp.owner_id) if opp and opp.owner_id else db.get(User, p.sent_by) if p.sent_by else None


def mark_opened(db: Session, link: ProposalLink, p: Proposal) -> None:
    from app.notifications.service import notify

    now = utcnow()
    first = link.opened_at is None
    link.opened_at = link.opened_at or now
    link.last_opened_at, link.open_count = now, (link.open_count or 0) + 1
    if p.status == "sent":
        p.status = "viewed"
    if first:
        _event(db, p, "opened", by_name=link.name, link=link)
        company = document.merge_values(db, p)["Company"]
        notify(db, [_owner(db, p)], "proposal_opened", f"{link.name} opened the {company} proposal v{p.version}", None, f"/sales/proposals/{p.id}/send")
    db.flush()


def public_view(db: Session, link: ProposalLink, p: Proposal) -> dict:
    """What the client sees: this version's summary, pricing, terms and full document. Nothing internal."""
    from app.proposals.service import lines

    ls = lines(db, p)
    values = document.merge_values(db, p)
    rep = db.get(User, p.sent_by) if p.sent_by else None
    acc = db.scalar(select(Acceptance).where(Acceptance.proposal_id == p.id))
    rows = document.pricing_rows(p, ls)
    return {
        "company": values["Company"], "title": p.title, "version": p.version, "status": p.status,
        "valid_until": p.valid_until.isoformat() if p.valid_until else None, "valid_until_label": values["Valid until"],
        "rep": {"name": rep.name if rep else None, "email": rep.email if rep else None},
        "included": [{"name": ln.name, "summary": document._summary(ln.description or ln.deliverables_text)} for ln in document.offered(ls)],
        "optional": [{"name": ln.name} for ln in document.optional(ls)],
        "pricing": [{"name": r["name"], "qty": r["qty"], "billing": r["billing"], "unit": r["unit"], "value": r["value"], "recurring": r["recurring"]} for r in rows],
        "totals": {k: (p.totals or {}).get(k) for k in ("one_time", "recurring_y1", "discount", "y1_total", "arr")},
        "discount_recurring_pct": p.discount_recurring_pct or 0, "terms": document.terms_lines(p),
        "sections": document.html_sections(db, p), "contact": {"name": link.name, "email": link.email},
        "accepted": {"name": acc.name, "title": acc.title, "at": acc.accepted_at.isoformat(), "po_number": acc.po_number} if acc else None,
        "can_respond": p.status in LIVE,
    }


def public_pdf(db: Session, settings: Settings, p: Proposal) -> tuple[bytes, str]:
    from app.files.models import FileObject
    from app.files.service import read

    f = db.get(FileObject, (p.file_ids or {}).get("pdf")) if (p.file_ids or {}).get("pdf") else None
    if f is not None:
        return read(settings, f), f.filename
    return document.to_pdf(db, p), document.filename(db, p, "pdf")


def _tell(db: Session, settings: Settings | None, p: Proposal, kind: str, title: str, body: str | None) -> None:
    """Owner, Sales Managers, and the Chief Auditor when the independence flag is set (spec §4.10): in-app and email."""
    from app.notifications.service import notify

    people = [_owner(db, p)] + approvals.users_with(db, ["sales_manager"])
    if (p.independence or {}).get("flag"):
        people += approvals.users_with(db, ["chief_auditor"])
    notify(db, people, kind, title, body, f"/sales/proposals/{p.id}/send", settings=settings, email_template="notification" if settings is not None else None)


def accept(db: Session, settings: Settings, link: ProposalLink, p: Proposal, *, name: str, title: str, email: str, authorised: bool,
           po_number: str | None, po_file: tuple[bytes, str, str | None] | None, ip: str | None, user_agent: str | None) -> Acceptance:
    from app.files.service import upload
    from app.sales.models import Opportunity

    if p.status == "accepted":
        raise Conflict("This proposal has already been accepted.")
    if p.status not in LIVE:
        raise Conflict("This proposal can no longer be accepted.")
    name, title, email = " ".join((name or "").split())[:200], " ".join((title or "").split())[:200], (email or "").strip().lower()
    errors = []
    if not name:
        errors.append({"field": "name", "message": "Enter your full name."})
    if not title:
        errors.append({"field": "title", "message": "Enter your title."})
    if not EMAIL.match(email) or len(email) > 254:
        errors.append({"field": "email", "message": "Enter your work email."})
    if not authorised:
        errors.append({"field": "authorised", "message": f"Confirm you are authorised to accept for {document.merge_values(db, p)['Company']}."})
    po_number = " ".join((po_number or "").split())[:80] or None
    if errors:
        raise Invalid(errors=errors)
    file_id = None
    if po_file is not None and po_file[0]:
        f = upload(db, settings, None, data=po_file[0], filename=po_file[1] or "purchase-order", content_type=po_file[2], organization_id=futran_org(db).id,
                   linked_type="ProposalAcceptance", linked_id=p.id)
        file_id = f.id
    now = utcnow()
    a = Acceptance(proposal_id=p.id, link_id=link.id, name=name, title=title, email=email, authorised_confirmed=True, po_number=po_number, po_file_id=file_id,
                   ip=(ip or "")[:64] or None, user_agent=(user_agent or "")[:400] or None, accepted_at=now)
    db.add(a)
    p.status = "accepted"
    for other in ps.thread(db, p.thread_id):
        if other.id != p.id and other.status not in ("superseded",):
            other.status = "superseded"
    db.flush()
    _event(db, p, "accepted", by_name=name, link=link, detail=f"{name}, {title} <{email}>" + (f" · PO {po_number}" if po_number else ""))
    opp = db.get(Opportunity, p.opportunity_id)
    company = document.merge_values(db, p)["Company"]
    if opp is not None:
        ps.move_stage(db, opp, "won", None)
        ps._log_opp(db, opp, f"{name} ({title}) accepted proposal v{p.version}" + (f" with PO {po_number}" if po_number else "") + ".", None)
    audit.record(db, actor_id=None, action="proposal.accepted", organization_id=p.organization_id, object_type="Proposal", object_id=p.id,
                 summary=f"{company} proposal v{p.version} accepted by {name} ({title}) from {a.ip or 'unknown address'}")
    _handoff(db, p, a)
    _tell(db, settings, p, "proposal_accepted", f"{company} accepted proposal v{p.version}",
          f"{name}, {title}" + (f" · PO {po_number}" if po_number else "") + f". Year-1 total ${(p.totals or {}).get('y1_total', 0):,}.")
    return a


def _handoff(db: Session, p: Proposal, a: Acceptance) -> None:
    """R5's hand-off (SM-13): client from prospect, order, engagement drafts, subscription, hours banks, commission."""
    try:
        from app.commercial import handoff
    except ImportError:
        return
    fn = getattr(handoff, "create_from_acceptance", None)
    if fn is None:
        return
    try:
        h = fn(db, p, a, None)
        a.handoff_id = getattr(h, "id", None)
        db.flush()
    except Exception as exc:  # noqa: BLE001  the acceptance stands; the owner finishes the hand-off by hand
        _event(db, p, "handoff_failed", detail=str(exc)[:500])
        from app.notifications.service import notify

        notify(db, [_owner(db, p)], "proposal_handoff_failed", f"Hand-off records were not created for proposal v{p.version}",
               "The acceptance is recorded. Open the opportunity to finish the hand-off.", f"/sales/proposals/{p.id}/send")


def request_changes(db: Session, settings: Settings, link: ProposalLink, p: Proposal, message: str, name: str | None = None) -> ProposalEvent:
    from app.sales.models import Opportunity

    if p.status not in LIVE:
        raise Conflict("This proposal can no longer be changed from here.")
    text = (message or "").replace("\r\n", "\n").strip()
    if not text:
        raise Invalid(errors=[{"field": "message", "message": "Say what you would like changed."}])
    if len(text) > 4000:
        raise Invalid(errors=[{"field": "message", "message": "Keep it under 4,000 characters."}])
    who = " ".join((name or "").split())[:200] or link.name
    p.status = "changes_requested"
    ev = _event(db, p, "changes_requested", by_name=who, link=link, detail=text)
    opp = db.get(Opportunity, p.opportunity_id)
    if opp is not None:
        ps.move_stage(db, opp, "negotiation", None)
        ps._log_opp(db, opp, f"{who} asked for changes to proposal v{p.version}: {text[:300]}", None)
    company = document.merge_values(db, p)["Company"]
    _tell(db, settings, p, "proposal_changes_requested", f"{company} asked for changes to proposal v{p.version}", f"{who}: {text[:1000]}")
    return ev


# ---- daily: owner alerts and expiry
def run_daily(db: Session, settings: Settings, now) -> int:
    from app.notifications.service import notify

    now = now if isinstance(now, datetime) else datetime.combine(now, time(10))
    n = 0
    for p in db.scalars(select(Proposal).where(Proposal.status.in_(LIVE))):
        if p.valid_until is None:
            continue
        company = document.merge_values(db, p)["Company"]
        alerts = dict(p.alerts or {})
        if _expiry(p) <= now:
            p.status = "expired"
            _event(db, p, "expired")
            notify(db, [_owner(db, p)], "proposal_expired", f"{company} proposal v{p.version} expired", None, f"/sales/proposals/{p.id}")
            n += 1
            continue
        opened = db.scalar(select(ProposalLink.id).where(ProposalLink.proposal_id == p.id, ProposalLink.opened_at.is_not(None)).limit(1))
        if not opened and not alerts.get("not_opened") and p.sent_at and p.sent_at <= now - timedelta(days=NOT_OPENED_DAYS):
            notify(db, [_owner(db, p)], "proposal_not_opened", f"{company} has not opened proposal v{p.version} after {NOT_OPENED_DAYS} days",
                   "Send a reminder from the proposal's send page.", f"/sales/proposals/{p.id}/send")
            alerts["not_opened"] = now.isoformat()
            n += 1
        if not alerts.get("expiring") and (p.valid_until - now.date()).days <= EXPIRING_DAYS:
            notify(db, [_owner(db, p)], "proposal_expiring", f"{company} proposal v{p.version} expires on {document.fmt_day(p.valid_until)}", None,
                   f"/sales/proposals/{p.id}/send")
            alerts["expiring"] = now.isoformat()
            n += 1
        p.alerts = alerts
    db.flush()
    return n


def log(db: Session, p: Proposal) -> list[dict]:
    """The send log for every version of this proposal, newest first."""
    ids = [v.id for v in ps.thread(db, p.thread_id)]
    versions = {v.id: v.version for v in ps.thread(db, p.thread_id)}
    out = []
    for ev in db.scalars(select(ProposalEvent).where(ProposalEvent.proposal_id.in_(ids)).order_by(ProposalEvent.at.desc())):
        out.append({"kind": ev.kind, "at": ev.at.isoformat(), "by": ev.by_name, "detail": ev.detail, "version": versions.get(ev.proposal_id)})
    return out


def links_out(db: Session, p: Proposal) -> list[dict]:
    return [{"id": ln.id, "name": ln.name, "email": ln.email, "sent_at": ln.sent_at.isoformat(), "expires_at": ln.expires_at.isoformat(),
             "opened_at": ln.opened_at.isoformat() if ln.opened_at else None, "open_count": ln.open_count, "active": ln.revoked_at is None}
            for ln in db.scalars(select(ProposalLink).where(ProposalLink.proposal_id == p.id).order_by(ProposalLink.sent_at))]
