"""Sending to groups (spec §26.4, §26.5).

`send_to_groups` is the single entry point for group email. Other workstreams (client alerts, A1) call it like this:

    from app.mail.sending import send_to_groups

    send = send_to_groups(
        db, settings, actor,                      # actor: the User who sends, or None for an automatic send
        organization_id=client_id,                # the client whose groups are expanded (or the Futran organisation)
        group_ids=[group.id, ...],                # MailGroup IDs; nested groups are expanded too
        template_key="regulatory_change_alert",   # a MailTemplate key (the client's copy wins), or template_id=...
        engagement_id=engagement.id,              # optional; links the send to the engagement's log and threads
        context={"Changes": "...", "Due date": "15 November 2026"},   # extra merge values: [Changes], [Due date]
        mode=None,                                # personal | bcc; None uses the template's default
        exclude_group_ids=[], exclude_responded=False, campaign=None,  # campaign=("attestation", campaign_id)
        reminder_days=None,                       # e.g. [3, 7]; reminders go only to people who have not responded
        link_days=14,                             # personal link lifetime
        subject=None, body=None,                  # optional overrides of the template text (merge fields still apply)
        sender="organization",                    # organization | futran | me
    )

It expands the groups now, saves the expanded recipient list and the count after each step on the MailSend, writes
an admin log entry, and starts delivery (paced; the scheduler finishes large sends). It returns the MailSend. When no
mailbox is connected the email still goes out through the outbox or SMTP.

`preview_expansion` returns the same steps without sending, for the E4 preview.
"""
import base64
import hashlib
import hmac
import html as html_lib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Invalid, NotFound
from app.mail import adminlog, delivery, library, tokens
from app.mail.groups import ensure_default_groups, resolve
from app.mail.models import DirectoryPerson, MailGroup, MailRecipient, MailSend, MailTemplate, MailThread
from app.tenancy.models import Department, Organization, User

log = logging.getLogger(__name__)

LINK_DAYS_DEFAULT = 14
BCC_BATCH_DEFAULT = 450  # Exchange Online allows 500 recipients per message by default; leave headroom
RETRY_MINUTES = (1, 5, 15)  # after the third failure the recipient shows as bounced
SUBJECT_PREFIX = "FAP"  # subject reference for reply sync: [FAP-1042] (Futran Audit Platform)
NUMBER_START = 1000

# campaign type -> function(db, campaign_id) returning the lower-case emails that have already responded
RESPONDED: dict = {}
# campaign type -> function(db, settings, recipient, send) called when a personal-link answer is recorded
LINK_PURPOSES: dict = {}


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class Expansion:
    steps: list[dict] = field(default_factory=list)
    people: list[DirectoryPerson] = field(default_factory=list)


def _groups(db: Session, org_id: str, ids) -> list[MailGroup]:
    ids = [i for i in dict.fromkeys(ids or []) if isinstance(i, str)]
    rows = {g.id: g for g in db.scalars(select(MailGroup).where(MailGroup.id.in_(ids), MailGroup.deleted_at.is_(None)))} if ids else {}
    out = []
    for i in ids:
        g = rows.get(i)
        if g is None or g.organization_id != org_id:
            raise NotFound("One of the groups no longer exists.")
        out.append(g)
    return out


def responded_emails(db: Session, campaign: tuple[str, str] | None) -> set[str]:
    if not campaign:
        return set()
    kind, cid = campaign
    out = set(RESPONDED[kind](db, cid)) if kind in RESPONDED else set()
    done = db.scalars(select(MailRecipient.email).join(MailSend, MailSend.id == MailRecipient.send_id)
                      .where(MailSend.campaign_type == kind, MailSend.campaign_id == cid, MailRecipient.status == "completed"))
    return out | {e.lower() for e in done}


def expand(db: Session, org_id: str, group_ids, *, exclude_group_ids=(), exclude_responded: bool = False, campaign: tuple[str, str] | None = None,
           department_ids=None, offices=None, department_scope=None, reminder: bool = False) -> Expansion:
    """Resolve groups to people, step by step, as the E4 preview shows them."""
    if not group_ids:
        raise Invalid(errors=[{"field": "group_ids", "message": "Choose at least one group."}])
    ensure_default_groups(db, org_id)
    steps: list[dict] = []
    union: dict[str, DirectoryPerson] = {}
    total = 0
    for i, g in enumerate(_groups(db, org_id, group_ids)):
        members = resolve(db, g)
        steps.append({"label": g.name, "count": len(members), "kind": "group" if i == 0 else "add"})
        total += len(members)
        union.update(members)
    if total > len(union):
        steps.append({"label": "In more than one group (counted once)", "count": -(total - len(union)), "kind": "remove"})
    people = dict(union)

    def drop(label: str, keep) -> None:
        before = len(people)
        for pid in [k for k, p in people.items() if not keep(p)]:
            people.pop(pid)
        if before != len(people):
            steps.append({"label": label, "count": -(before - len(people)), "kind": "remove"})

    if department_scope is not None:
        scope = set(department_scope)
        drop("Outside your departments", lambda p: p.department_id in scope)
    if department_ids:
        chosen = set(department_ids)
        drop("Not in the chosen departments", lambda p: p.department_id in chosen)
    if offices:
        wanted = {o.strip().lower() for o in offices if o}
        drop("Not in the chosen locations", lambda p: (p.office or "").strip().lower() in wanted)
    for g in _groups(db, org_id, exclude_group_ids):
        out = set(resolve(db, g))
        drop(f"Left out: {g.name}", lambda p, out=out: p.id not in out)
    if exclude_responded:
        done = responded_emails(db, campaign)
        drop("Already responded", lambda p: p.email.lower() not in done)
    drop("Left the company or on leave", lambda p: p.status == "active")
    if reminder:
        drop("Unsubscribed from reminders", lambda p: not p.reminders_opt_out)
    final = sorted(people.values(), key=lambda p: (p.name.lower(), p.email))
    steps.append({"label": "Will receive", "count": len(final), "kind": "total"})
    return Expansion(steps=steps, people=final)


def preview_expansion(db: Session, org_id: str, group_ids, **kw) -> Expansion:
    return expand(db, org_id, group_ids, **kw)


def next_subject_ref(db: Session) -> str:
    refs = db.scalars(select(MailThread.subject_ref))
    highest = max((int(r.split("-", 1)[1]) for r in refs if r and r.split("-", 1)[1].isdigit()), default=NUMBER_START - 1)
    return f"{SUBJECT_PREFIX}-{highest + 1}"


def _template(db: Session, org_id: str, template_key: str | None, template_id: str | None) -> MailTemplate:
    if template_id:
        t = db.get(MailTemplate, template_id)
        if t is None or t.deleted_at is not None or t.organization_id not in (org_id, "futran"):
            raise NotFound("The template no longer exists.")
        return t
    if not template_key:
        raise Invalid(errors=[{"field": "template", "message": "Choose a template."}])
    return library.for_send(db, org_id, template_key)


def _plus(d: datetime, days: int) -> datetime:
    return d + timedelta(days=days)


def fmt_day(d: datetime) -> str:
    return f"{d.day} {d:%B %Y}"


def send_to_groups(db: Session, settings: Settings, actor: User | None, *, organization_id: str, group_ids, template_key: str | None = None,
                   template_id: str | None = None, engagement_id: str | None = None, exclude_group_ids=(), exclude_responded: bool = False,
                   campaign: tuple[str, str] | None = None, department_ids=None, offices=None, department_scope=None, mode: str | None = None,
                   reminder_days=None, link_days: int | None = None, batch_size: int | None = None, scheduled_at: datetime | None = None,
                   context: dict | None = None, subject: str | None = None, body: str | None = None, sender: str = "organization", related=None) -> MailSend:
    t = _template(db, organization_id, template_key, template_id)
    mode = mode or t.default_mode
    if mode not in ("personal", "bcc"):
        raise Invalid(errors=[{"field": "mode", "message": "Choose personal links or BCC."}])
    days = int(link_days or LINK_DAYS_DEFAULT)
    if days < 1 or days > 90:
        raise Invalid(errors=[{"field": "link_days", "message": "Links can last from 1 to 90 days."}])
    plan = sorted({int(d) for d in reminder_days or [] if str(d).isdigit() and 0 < int(d) <= 60})
    ex = expand(db, organization_id, group_ids, exclude_group_ids=exclude_group_ids, exclude_responded=exclude_responded, campaign=campaign,
                department_ids=department_ids, offices=offices, department_scope=department_scope)
    if not ex.people:
        raise Invalid(errors=[{"field": "group_ids", "message": "Nobody would receive this email. Check the groups and what is left out."}])
    now = utcnow()
    who = delivery.resolve_sender(db, settings, organization_id, prefer=sender, user_id=actor.id if actor else None)
    names = {g.id: g.name for g in db.scalars(select(MailGroup).where(MailGroup.id.in_(list(group_ids) + list(exclude_group_ids or []))))}
    s = MailSend(organization_id=organization_id, engagement_id=engagement_id, kind="group", template_id=t.id, template_version=t.version, template_key=t.key,
                 template_name=t.name, subject=subject or t.subject, sender_connection_id=who.connection.id if who.connection else None,
                 sender_user_id=actor.id if who.user_connection is not None and actor else None, sender_label=who.label, channel=who.channel,
                 groups=[{"id": g, "name": names.get(g)} for g in dict.fromkeys(group_ids)],
                 exclusions=[{"id": g, "name": names.get(g)} for g in dict.fromkeys(exclude_group_ids or [])] + ([{"id": "responded", "name": "Already responded"}] if exclude_responded else []),
                 mode=mode, batch_size=int(batch_size or getattr(settings, "mail_bcc_batch_size", BCC_BATCH_DEFAULT)) if mode == "bcc" else None,
                 scheduled_at=scheduled_at, sent_by=actor.id if actor else None, sent_by_name=_who(db, actor), reminder_plan=plan or None, link_days=days,
                 campaign_type=campaign[0] if campaign else None, campaign_id=campaign[1] if campaign else None,
                 context={**(context or {}), **({"_body": body} if body else {})}, expansion=ex.steps, recipient_count=len(ex.people),
                 status="scheduled" if scheduled_at and scheduled_at > now else "queued", department_scope=list(department_scope) if department_scope is not None else None,
                 related_type=type(related).__name__ if related is not None else None, related_id=getattr(related, "id", None),
                 retain_until=adminlog.retain_until(now), created_by=actor.id if actor else None)
    db.add(s)
    db.flush()
    db.add(MailThread(organization_id=organization_id, send_id=s.id, engagement_id=engagement_id, connection_id=s.sender_connection_id, subject_ref=next_subject_ref(db)))
    for i, p in enumerate(ex.people):
        db.add(MailRecipient(organization_id=organization_id, send_id=s.id, person_id=p.id, email=p.email, name=p.name, status="queued",
                             batch_no=(i // s.batch_size) + 1 if mode == "bcc" else None))
    db.flush()
    adminlog.write(db, organization_id=organization_id, category="send", action="send", actor=actor, engagement_id=engagement_id, send_id=s.id,
                   department_id=(list(department_scope)[0] if department_scope else None),
                   summary=f"{t.name} to {len(s.groups)} {'group' if len(s.groups) == 1 else 'groups'} ({len(ex.people):,} {'person' if len(ex.people) == 1 else 'people'})"
                           + (", scheduled" if s.status == "scheduled" else ""),
                   details={"groups": [g["name"] for g in s.groups], "mode": mode, "steps": ex.steps})
    if s.status == "queued":
        dispatch(db, settings, s)
    return s


def _who(db: Session, actor: User | None) -> str:
    if actor is None:
        return "System"
    org = db.get(Organization, actor.organization_id)
    from app.policy.roles import role_label
    from app.tenancy.service import roles_of

    roles = [r.role for r in roles_of(db, actor.id)]
    label = role_label(roles[0]) if roles else ""
    return f"{'Futran · ' if org and org.type == 'futran' else ''}{actor.name}{' · ' + label if label else ''}"


# ---- rendering
def _merge_values(db: Session, s: MailSend, person: DirectoryPerson | None, link: str | None, expires: datetime | None) -> dict:
    org = db.get(Organization, s.organization_id)
    dept = None
    if person is not None and person.department_id:
        d = db.get(Department, person.department_id)
        dept = d.name if d else None
    name = person.name if person else ""
    values = {"First name": (name.split()[0] if name else "there"), "Name": name or "colleague", "Department": dept or (person.department if person else "") or "your department",
              "Organization": org.name if org else "", "Sender name": (s.sent_by_name or "").split(" · ")[0 if not (s.sent_by_name or "").startswith("Futran · ") else 1] or (org.name if org else ""),
              "Due date": fmt_day(expires) if expires else ""}
    for k, v in (s.context or {}).items():
        if not k.startswith("_"):
            values[k] = str(v)
    if link:
        values["Link"] = link
    return values


def render(db: Session, s: MailSend, person: DirectoryPerson | None, link: str | None, expires: datetime | None, ref: str | None) -> tuple[str, str, str]:
    t = db.get(MailTemplate, s.template_id) if s.template_id else None
    values = _merge_values(db, s, person, link, expires)
    subject = delivery.one_line(library.merge(s.subject or (t.subject if t else ""), values))
    if ref:
        subject = f"{subject} [{ref}]"
    body = (s.context or {}).get("_body") or (t.body if t else "")
    button = (t.button_label if t else None) or "Open"
    paras_html, paras_text = [], []
    for para in [p.strip() for p in body.replace("\r\n", "\n").split("\n\n") if p.strip()]:
        if para == "[Link]":
            if link:
                paras_html.append(f'<p style="margin:24px 0"><a href="{html_lib.escape(link)}" style="background:#1B3A6B;color:#ffffff;padding:12px 20px;text-decoration:none;display:inline-block">{html_lib.escape(button)}</a></p>')
                paras_text.append(f"{button}: {link}")
            continue
        merged = library.merge(para, values)
        paras_html.append("<p>" + "<br>".join(html_lib.escape(line) for line in merged.split("\n")) + "</p>")
        paras_text.append(merged)
    from app.mail.service import render_layout

    return subject[:300], render_layout("\n".join(paras_html)), "\n\n".join(paras_text) + "\n"


# ---- delivery
def _issue_link(db: Session, settings: Settings, s: MailSend, r: MailRecipient, now: datetime) -> tuple[str, datetime]:
    """A new personal link for this person. Any other active link of theirs for the same campaign stops working."""
    raw = secrets.token_urlsafe(32)  # 256 bits
    expires = _plus(now, s.link_days or LINK_DAYS_DEFAULT)
    root = s.parent_send_id or s.id
    same = ((MailSend.campaign_type == s.campaign_type) & (MailSend.campaign_id == s.campaign_id)) if s.campaign_type and s.campaign_id else \
        ((MailSend.id == root) | (MailSend.parent_send_id == root))
    others = select(MailRecipient).join(MailSend, MailSend.id == MailRecipient.send_id).where(
        same, MailRecipient.id != r.id, func.lower(MailRecipient.email) == r.email.lower(), MailRecipient.link_token_hash.is_not(None), MailRecipient.link_revoked_at.is_(None))
    for o in db.scalars(others):
        o.link_revoked_at = now
    r.link_token_hash, r.link_expires_at, r.link_revoked_at = token_hash(raw), expires, None
    return f"{settings.base_url}/m/{raw}", expires


def _thread(db: Session, s: MailSend) -> MailThread | None:
    return db.scalar(select(MailThread).where(MailThread.send_id == s.id).limit(1))


def _sender_for(db: Session, settings: Settings, s: MailSend) -> delivery.Sender:
    prefer = "me" if s.sender_user_id else ("futran" if db.get(Organization, s.organization_id).type == "futran" else "organization")
    return delivery.resolve_sender(db, settings, s.organization_id, prefer=prefer, user_id=s.sender_user_id)


def pace_limit(settings: Settings, sender: delivery.Sender) -> int | None:
    """Messages per dispatch run (once a minute). None = no limit (test mode: nothing leaves the platform)."""
    if sender.channel == "outbox":
        return None
    return max(1, int(getattr(settings, "mail_pace_per_minute", 30)))


def _claim(db: Session, r: MailRecipient) -> bool:
    """Take a queued recipient for this run before the provider is called: a conditional update checked by its row
    count. A scheduler run that overlaps waits for the other's commit and then finds the recipient taken, so nobody
    gets the message twice. The claim is part of the run's transaction: if the run fails it is undone too."""
    res = db.execute(update(MailRecipient).where(MailRecipient.id == r.id, MailRecipient.status == "queued").values(status="sending")
                     .execution_options(synchronize_session=False))
    if res.rowcount != 1:
        db.refresh(r)
        return False
    set_committed_value(r, "status", "sending")
    return True


def dispatch(db: Session, settings: Settings, s: MailSend, now: datetime | None = None, limit: int | None = None) -> int:
    """Deliver the send's queued recipients that are due, at most `limit` messages (default: the pace for the channel).
    Returns the number of messages sent."""
    now = now or utcnow()
    if s.status == "scheduled":
        if s.scheduled_at and s.scheduled_at > now:
            return 0
        s.status = "queued"
    sender = _sender_for(db, settings, s)
    limit = limit if limit is not None else pace_limit(settings, sender)
    thread = _thread(db, s)
    ref = thread.subject_ref if thread else None
    due = [r for r in db.scalars(select(MailRecipient).where(MailRecipient.send_id == s.id, MailRecipient.status == "queued").order_by(MailRecipient.batch_no, MailRecipient.name))
           if r.next_attempt_at is None or r.next_attempt_at <= now]
    sent = 0
    if s.mode == "bcc":
        sent = _dispatch_bcc(db, settings, s, sender, due, now, ref, limit)
    else:
        for r in due:
            if limit is not None and sent >= limit:
                break
            if not _claim(db, r):
                continue
            link, expires = _issue_link(db, settings, s, r, now)
            person = db.get(DirectoryPerson, r.person_id) if r.person_id else None
            subj, html, text = render(db, s, person, link, expires, ref)
            stored = None
            if settings.email_mode != "outbox":
                subj2, html2, text2 = render(db, s, person, f"{settings.base_url}/m/(personal link, not stored)", expires, ref)
                stored = delivery.Envelope(to=[r.email], subject=subj2, html=html2, text=text2)
            env = delivery.Envelope(to=[r.email], subject=subj, html=html, text=text, thread_ref=ref)
            msg = delivery.record(db, organization_id=s.organization_id, env=env, stored=stored, template_key=s.template_key or "group", mail_send_id=s.id, channel=sender.channel)
            _apply(r, delivery.deliver(db, settings, sender, env, msg), now)
            sent += 1
    _finish(db, s, now)
    return sent


def _shared_token(settings: Settings, s: MailSend) -> str:
    """The send's one shared link token. It is derived from the send and the platform's token key (the key that
    encrypts mailbox tokens), so a retry or a later paced batch carries the same link as the batches already delivered,
    and only its hash is stored."""
    _, material = tokens._key_material(settings)
    digest = hmac.new(f"mail-shared-link:{material}".encode(), s.id.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _dispatch_bcc(db: Session, settings: Settings, s: MailSend, sender: delivery.Sender, due: list[MailRecipient], now: datetime, ref: str | None, limit: int | None) -> int:
    """BCC mode: one message per batch, everyone in BCC, one shared link for the whole send. The link is issued once
    and reused on retries and later batches; at most `limit` batches go per run (the pacing limit). Only the batches
    that go in this run are claimed."""
    if not due:
        return 0
    raw = _shared_token(settings, s)
    if s.shared_token_hash != token_hash(raw):
        # first batch (or the token key changed since): issue the link now
        s.shared_token_hash, s.shared_link_expires_at = token_hash(raw), _plus(now, s.link_days or LINK_DAYS_DEFAULT)
    link = f"{settings.base_url}/m/s/{raw}"
    grouped: dict[int, list[MailRecipient]] = {}
    for r in due:
        grouped.setdefault(r.batch_no or 1, []).append(r)
    batches: dict[int, list[MailRecipient]] = {}
    for n, rows in sorted(grouped.items()):
        if limit is not None and len(batches) >= limit:
            break
        claimed = [r for r in rows if _claim(db, r)]
        if claimed:
            batches[n] = claimed
    if not batches:
        return 0
    subj, html, text = render(db, s, None, link, s.shared_link_expires_at, ref)
    stored = None
    if settings.email_mode != "outbox":
        subj2, html2, text2 = render(db, s, None, f"{settings.base_url}/m/s/(shared link, not stored)", s.shared_link_expires_at, ref)
    sent = 0
    for n, rows in sorted(batches.items()):
        to = [sender.from_address] if sender.from_address else []
        env = delivery.Envelope(to=to, bcc=[r.email for r in rows], subject=subj, html=html, text=text, thread_ref=ref)
        if settings.email_mode != "outbox":
            stored = delivery.Envelope(to=to, bcc=env.bcc, subject=subj2, html=html2, text=text2)
        msg = delivery.record(db, organization_id=s.organization_id, env=env, stored=stored, template_key=s.template_key or "group", mail_send_id=s.id, channel=sender.channel)
        res = delivery.deliver(db, settings, sender, env, msg)
        for r in rows:
            _apply(r, res, now)
        sent += 1
    return sent


def _apply(r: MailRecipient, res: delivery.Result, now: datetime) -> None:
    r.last_event_at = now
    if res.ok:
        r.status, r.error, r.next_attempt_at = "sent", None, None
        r.provider_message_id, r.provider_thread_id = res.provider_message_id, res.provider_thread_id
        return
    r.attempts = (r.attempts or 0) + 1
    r.error = res.error
    if r.attempts >= len(RETRY_MINUTES):
        r.status, r.next_attempt_at = "bounced", None
    else:
        r.status, r.next_attempt_at = "queued", now + timedelta(minutes=RETRY_MINUTES[r.attempts - 1])  # release the claim for the retry


def _finish(db: Session, s: MailSend, now: datetime) -> None:
    db.flush()
    waiting = db.scalar(select(func.count(MailRecipient.id)).where(MailRecipient.send_id == s.id, MailRecipient.status == "queued"))
    if waiting:
        s.status = "sending"
    else:
        s.status = "sent"
        s.sent_at = s.sent_at or now


def dispatch_due(db: Session, settings: Settings, now: datetime | None = None) -> int:
    """Scheduler: continue every send that still has queued recipients (scheduled sends start at their time). Each send
    runs in its own savepoint: one that fails is rolled back, logged and tried again next minute, and the others go on."""
    now = now or utcnow()
    n = 0
    for sid in list(db.scalars(select(MailSend.id).where(MailSend.status.in_(["scheduled", "queued", "sending"])))):
        try:
            with db.begin_nested():
                n += dispatch(db, settings, db.get(MailSend, sid), now)
        except Exception:  # noqa: BLE001 (any failure in one send must not stop the others)
            log.exception("Email send %s failed in the scheduler; it is tried again next minute", sid)
    return n
