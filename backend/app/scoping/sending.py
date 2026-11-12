"""Client links for the scoping questionnaire (SM-06, SM-07; spec §4.4, plan "token-link pattern").

- A personal link per contact: a random 256-bit token, stored only as its SHA-256 hash, expiring after 14 days, for
  this one purpose. It shows only the questions the rep picked, never an internal-only one, and only this contact's own
  earlier answers.
- Sent from the rep's own mailbox when connected (v0.6.1 §27.1), else Futran's mailbox, SMTP or the outbox.
- The client can forward to a colleague, who gets their own link (at most 5 forwards per link).
- Reminders on the days the rep chose (day 3 and day 7 by default) carry a fresh link; the old one stops working.
- The owner is told when a contact submits (completed or partly completed) and, once, when the due date passes on a
  partly answered link (spec §4.10).
"""
import html as html_lib
import re
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.mail.sending import token_hash
from app.scoping import bank
from app.scoping.models import QuestionnaireSend, ScopingAnswer, ScopingQuestionnaire
from app.tenancy.models import Organization, User

LINK_DAYS = 14
MAX_FORWARDS = 5
DEFAULT_REMINDERS = [3, 7]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUBJECT = "A few questions to scope your AI compliance review"
MESSAGE = ("Hi [First name],\n\nThanks for the call today. To size the work properly, could you or a colleague answer a few questions about "
           "the AI tools [Company] uses? It takes about 10 minutes, and \"not sure\" is a fine answer.\n\n[Link]\n\n"
           "Due [Due date]. Your answers are only used to prepare our proposal.\n\n[Rep name] · Futran Solutions")
FORWARD_MESSAGE = ("Hi [First name],\n\n[Forwarded by] asked us to send you some questions about the AI tools [Company] uses, so Futran Solutions "
                   "can prepare a proposal. \"Not sure\" is a fine answer.\n\n[Link]\n\nDue [Due date]. Your answers are only used to prepare our proposal.\n\n"
                   "[Rep name] · Futran Solutions")
REMINDER_MESSAGE = ("Hi [First name],\n\nA reminder about the scoping questions for [Company]. Your answers so far are saved; this link opens "
                    "where you left off. The link in the earlier email no longer works.\n\n[Link]\n\nDue [Due date].\n\n[Rep name] · Futran Solutions")
FOOTER = "General information, not legal advice. Futran Solutions uses your answers only to prepare its proposal."
PRIVACY = ("Your answers are stored by Futran Solutions against your company's sales record and are seen only by the Futran sales team "
           "preparing the proposal. They are not shared with anyone else.")


class Gone(AppError):
    status_code = 410


def futran_org(db: Session) -> Organization:
    return db.scalar(select(Organization).where(Organization.type == "futran").limit(1))


def _first(name: str) -> str:
    return (name or "").split()[0] if (name or "").strip() else "there"


def fmt_day(d: date | None) -> str:
    return f"{d.day} {d:%B %Y}" if d else "when you can"


def merge(text: str, values: dict) -> str:
    return re.sub(r"\[([A-Za-z ]+)\]", lambda m: values.get(m.group(1), m.group(0)), text or "")


def _render(body: str, link: str, values: dict) -> tuple[str, str]:
    """(html, text) for the message; `[Link]` on its own paragraph becomes the button."""
    from app.mail.service import render_layout

    paras = [p.strip() for p in (body or "").replace("\r\n", "\n").split("\n\n") if p.strip()]
    if "[Link]" not in paras:
        paras.append("[Link]")
    h, t = [], []
    for p in paras:
        if p == "[Link]":
            h.append(f'<p style="margin:24px 0"><a href="{html_lib.escape(link)}" style="background:#1B3A6B;color:#ffffff;padding:12px 20px;'
                     f'text-decoration:none;display:inline-block">Open the questions</a></p>')
            t.append(f"Open the questions: {link}")
            continue
        merged = merge(p, values)
        h.append("<p>" + "<br>".join(html_lib.escape(line) for line in merged.split("\n")) + "</p>")
        t.append(merged)
    return render_layout("\n".join(h)), "\n\n".join(t) + "\n"


def _deliver(db: Session, settings: Settings, s: QuestionnaireSend, rep: User | None, subject: str, body: str, link: str, values: dict, *, reminder: bool = False) -> None:
    """One email from the rep's mailbox, recorded in the email log; the readable copy has the link removed when real
    email is on, so nobody can read the link back from the outbox."""
    from app.mail import adminlog, delivery
    from app.mail.models import MailRecipient, MailSend, MailThread
    from app.mail.sending import next_subject_ref

    org = futran_org(db)
    sender = delivery.resolve_sender(db, settings, org.id, prefer="me", user_id=rep.id if rep else None)
    now = utcnow()
    subject = delivery.one_line(merge(subject, values))[:280]
    ms = MailSend(organization_id=org.id, kind="reminder" if reminder else "system", mode="direct", template_key="scoping_questionnaire",
                  template_name="Scoping questionnaire" + (" reminder" if reminder else ""), subject=subject, channel=sender.channel, sender_label=sender.label,
                  sender_connection_id=sender.connection.id if sender.connection else None,
                  sender_user_id=rep.id if rep is not None and sender.user_connection is not None else None, recipient_count=1, sent_by=rep.id if rep else None,
                  sent_by_name=rep.name if rep else "System", related_type="QuestionnaireSend", related_id=s.id, status="queued",
                  retain_until=adminlog.retain_until(now), created_by=rep.id if rep else None, link_days=LINK_DAYS)
    db.add(ms)
    db.flush()
    if sender.is_provider:  # replies come back to the rep's thread
        ref = next_subject_ref(db)
        db.add(MailThread(organization_id=org.id, send_id=ms.id, connection_id=ms.sender_connection_id, subject_ref=ref,
                          user_connection_id=sender.user_connection.id if sender.user_connection is not None else None))
        subject = f"{subject} [{ref}]"
    html, text = _render(body, link, values)
    env = delivery.Envelope(to=[s.contact_email], subject=subject, html=html, text=text)
    stored = None
    if settings.email_mode != "outbox":
        sh, st = _render(body, "(personal link sent to the recipient, not stored)", values)
        stored = delivery.Envelope(to=[s.contact_email], subject=subject, html=sh, text=st)
    msg = delivery.record(db, organization_id=org.id, env=env, stored=stored, template_key="scoping_questionnaire", related=s,
                          actor_id=rep.id if rep else None, mail_send_id=ms.id, channel=sender.channel)
    res = delivery.deliver(db, settings, sender, env, msg)
    r = MailRecipient(organization_id=org.id, send_id=ms.id, email=s.contact_email.lower(), name=s.contact_name, status="sent" if res.ok else "bounced",
                      error=None if res.ok else res.error, provider_message_id=res.provider_message_id, provider_thread_id=res.provider_thread_id,
                      last_event_at=now, attempts=1)
    db.add(r)
    ms.status, ms.sent_at = "sent", now
    db.flush()
    s.mail_send_id, s.mail_recipient_id = ms.id, r.id
    adminlog.write(db, organization_id=org.id, category="send", action="system_send", actor_name=ms.sent_by_name, send_id=ms.id,
                   summary=f"{ms.template_name} to {s.contact_email}" + ("" if res.ok else " (not delivered)"))


def _issue(settings: Settings, s: QuestionnaireSend) -> str:
    raw = secrets.token_urlsafe(32)  # 256 bits
    s.token_hash = token_hash(raw)
    return f"{settings.base_url}/q/{raw}"


def _values(db: Session, s: QuestionnaireSend, rep: User | None, extra: dict | None = None) -> dict:
    q = db.get(ScopingQuestionnaire, s.questionnaire_id)
    org = db.get(Organization, q.prospect_id) if q else None
    return {"First name": _first(s.contact_name), "Name": s.contact_name, "Company": org.name if org else "your company",
            "Due date": fmt_day(s.due_on), "Rep name": rep.name if rep else "Futran Solutions", **(extra or {})}


def _codes(db: Session, q: ScopingQuestionnaire, codes) -> list[str]:
    """The client-visible questions asked for, in bank order. Internal-only questions are dropped whatever was asked."""
    wanted = {str(c) for c in codes or []}
    out = [x.code for x in bank.questions(db, q.bank_version) if x.code in wanted and not x.internal_only]
    if not out:
        raise Invalid(errors=[{"field": "question_codes", "message": "Choose at least one question to send."}])
    return out


def _contact(contact: dict) -> tuple[str | None, str, str]:
    name = str((contact or {}).get("name") or "").strip()[:200]
    email = str((contact or {}).get("email") or "").strip().lower()[:254]
    errors = []
    if not name:
        errors.append({"field": "contact", "message": "Choose who to send it to."})
    if not EMAIL.match(email):
        errors.append({"field": "email", "message": "Enter a valid email address."})
    if errors:
        raise Invalid(errors=errors)
    return (contact or {}).get("id"), name, email


def send(db: Session, settings: Settings, q: ScopingQuestionnaire, rep: User, *, contact: dict, question_codes, due_on: date | None = None,
         reminders=None, allow_forward: bool = True, subject: str | None = None, message: str | None = None) -> QuestionnaireSend:
    if q.status == "locked":
        raise Conflict("This version is locked. Unlock it to make a new version before sending questions.")
    cid, name, email = _contact(contact)
    codes = _codes(db, q, question_codes)
    now = utcnow()
    if due_on is not None and due_on < now.date():
        raise Invalid(errors=[{"field": "due_on", "message": "Choose a due date from today on."}])
    days = sorted({int(d) for d in (DEFAULT_REMINDERS if reminders is None else reminders) if str(d).isdigit() and 0 < int(d) < LINK_DAYS})
    subject = (subject or SUBJECT).strip() or SUBJECT
    message = (message or MESSAGE).strip() or MESSAGE
    if len(subject) > 250 or len(message) > 5000:
        raise Invalid(errors=[{"field": "message", "message": "Keep the subject under 250 and the message under 5,000 characters."}])
    s = QuestionnaireSend(questionnaire_id=q.id, contact_id=cid, contact_name=name, contact_email=email, question_codes=codes, due_on=due_on,
                          reminder_days=days, reminders_sent=[], allow_forward=bool(allow_forward), status="sent", expires_at=now + timedelta(days=LINK_DAYS),
                          subject=subject, message=message, sent_by=rep.id, sent_at=now)
    db.add(s)
    db.flush()
    link = _issue(settings, s)
    _deliver(db, settings, s, rep, subject, message, link, _values(db, s, rep))
    has_rep = db.scalar(select(ScopingAnswer.id).where(ScopingAnswer.questionnaire_id == q.id, ScopingAnswer.slot == "rep").limit(1)) is not None
    q.mode = "hybrid" if has_rep or q.mode == "hybrid" else "sent"
    if q.status == "draft":
        q.status = "sent"
    from app.sales.models import Opportunity
    from app.scoping.service import _log, move_to_scoping

    opp = db.get(Opportunity, q.opportunity_id)
    if opp is not None:
        _log(db, opp, f"Scoping questions sent to {name} ({len(codes)} question{'s' if len(codes) != 1 else ''}).", rep.id, kind="email")
        move_to_scoping(db, opp, rep.id)
    db.flush()
    return s


def close_links(db: Session, q: ScopingQuestionnaire) -> None:
    """Locking a version closes its client links."""
    now = utcnow()
    for s in db.scalars(select(QuestionnaireSend).where(QuestionnaireSend.questionnaire_id == q.id, QuestionnaireSend.revoked_at.is_(None))):
        s.revoked_at = now


def revoke(db: Session, s: QuestionnaireSend) -> None:
    if s.revoked_at is None:
        s.revoked_at, s.status = utcnow(), "revoked"
    db.flush()


# ---- the public side
def resolve(db: Session, raw: str) -> QuestionnaireSend:
    s = db.scalar(select(QuestionnaireSend).where(QuestionnaireSend.token_hash == token_hash(raw or "")).limit(1)) if raw and len(raw) < 200 else None
    if s is None:
        raise NotFound("This link is not valid. Use the link in your most recent email.")
    if s.revoked_at is not None:
        raise Gone("These questions are closed. Contact your Futran representative if you have more to add.")
    if s.expires_at is None or s.expires_at <= utcnow():
        raise Gone("This link has expired. Ask your Futran representative for a new one.")
    return s


def _mail_recipient(db: Session, s: QuestionnaireSend, status: str) -> None:
    from app.mail.models import MailRecipient

    r = db.get(MailRecipient, s.mail_recipient_id) if s.mail_recipient_id else None
    if r is None:
        return
    now = utcnow()
    if status == "opened" and r.status in ("queued", "sent", "delivered"):
        r.status, r.opened_at = "opened", r.opened_at or now
    elif status == "completed":
        r.status, r.completed_at = "completed", now
    r.last_event_at = now


def view(db: Session, s: QuestionnaireSend) -> dict:
    q = db.get(ScopingQuestionnaire, s.questionnaire_id)
    org = db.get(Organization, q.prospect_id)
    rep = db.get(User, s.sent_by) if s.sent_by else None
    if s.opened_at is None:
        s.opened_at = utcnow()
        if s.status == "sent":
            s.status = "opened"
        _mail_recipient(db, s, "opened")
        db.flush()
    qs = bank.by_code(db, q.bank_version)
    wanted = [qs[c] for c in s.question_codes if c in qs and not qs[c].internal_only and qs[c].active]
    sections: list[dict] = []
    for x in wanted:
        if not sections or sections[-1]["key"] != x.section:
            sections.append({"key": x.section, "label": bank.SECTION_LABELS.get(x.section, x.section), "questions": []})
        sections[-1]["questions"].append({"code": x.code, "label": x.client_label or x.label, "help": None, "type": x.type,  # help text is written for the rep
                                          "options": x.options or []})
    mine = {a.question_code: {"value": a.value, "confidence": a.confidence} for a in db.scalars(
        select(ScopingAnswer).where(ScopingAnswer.questionnaire_id == q.id, ScopingAnswer.slot == "client", ScopingAnswer.question_code.in_(s.question_codes)))}
    return {"company": org.name if org else "", "first_name": _first(s.contact_name), "rep_name": rep.name if rep else "Futran Solutions",
            "due_on": s.due_on.isoformat() if s.due_on else None, "allow_forward": s.allow_forward,
            "submitted": s.submitted_at is not None, "sections": sections, "answers": mine,
            "questions_label": f"{sum(len(x['questions']) for x in sections)} questions in {len(sections)} section{'s' if len(sections) != 1 else ''}",
            "footer": FOOTER, "privacy": PRIVACY, "expires_at": s.expires_at.isoformat()}


def save(db: Session, s: QuestionnaireSend, items: list) -> int:
    if s.submitted_at is not None:
        raise Conflict("These answers have been submitted. Contact your Futran representative to change them.")
    from app.scoping import service

    q = db.get(ScopingQuestionnaire, s.questionnaire_id)
    if not isinstance(items, list) or len(items) > 200:
        raise Invalid(errors=[{"field": "answers", "message": "Send a list of answers."}])
    n = service.save_client_answers(db, q, [i for i in items if isinstance(i, dict)], send_id=s.id, name=s.contact_name, allowed=set(s.question_codes))
    s.last_saved_at = utcnow()
    if s.status in ("sent", "opened"):
        s.status = "in_progress"
    db.flush()
    return n


def _answered(db: Session, s: QuestionnaireSend) -> int:
    return db.scalar(select(func.count(ScopingAnswer.id)).where(ScopingAnswer.questionnaire_id == s.questionnaire_id, ScopingAnswer.slot == "client",
                                                               ScopingAnswer.question_code.in_(s.question_codes))) or 0


def _tell_owner(db: Session, settings: Settings | None, s: QuestionnaireSend, complete: bool) -> None:
    from app.notifications.service import notify
    from app.sales.models import Opportunity

    q = db.get(ScopingQuestionnaire, s.questionnaire_id)
    opp = db.get(Opportunity, q.opportunity_id)
    org = db.get(Organization, q.prospect_id)
    owner = db.get(User, opp.owner_id) if opp is not None and opp.owner_id else None
    owner = owner or (db.get(User, s.sent_by) if s.sent_by else None)
    if owner is None:
        return
    done, total = _answered(db, s), len(s.question_codes)
    what = "completed" if complete else "partly completed"
    notify(db, [owner], "scoping_client_answers", f"{s.contact_name} {what} the scoping questions for {org.name if org else 'the prospect'}",
           f"{done} of {total} questions answered. Review the answers before locking the questionnaire.",
           f"/sales/opportunities/{q.opportunity_id}/scoping/review", settings=settings,
           email_template="notification" if settings is not None else None)  # spec §4.10: in-app and email


def submit(db: Session, settings: Settings, s: QuestionnaireSend) -> dict:
    if s.submitted_at is not None:
        return {"submitted": True}
    s.submitted_at, s.status = utcnow(), "submitted"
    q = db.get(ScopingQuestionnaire, s.questionnaire_id)
    if q.status in ("draft", "sent", "client_in_progress"):
        q.status = "client_submitted"
    _mail_recipient(db, s, "completed")
    complete = _answered(db, s) >= len(s.question_codes)
    _tell_owner(db, settings, s, complete)
    db.flush()
    return {"submitted": True, "complete": complete}


def forward(db: Session, settings: Settings, s: QuestionnaireSend, name: str, email: str) -> QuestionnaireSend:
    if not s.allow_forward:
        raise Conflict("Forwarding is switched off for these questions.")
    if s.submitted_at is not None:
        raise Conflict("These answers have been submitted.")
    root = s.forwarded_from_id or s.id
    count = db.scalar(select(func.count(QuestionnaireSend.id)).where(QuestionnaireSend.forwarded_from_id == root)) or 0
    if count >= MAX_FORWARDS:
        raise Conflict("These questions have been forwarded the most times allowed. Contact your Futran representative.")
    _, name, email = _contact({"name": name, "email": email})
    if email == s.contact_email:
        raise Invalid(errors=[{"field": "email", "message": "Enter your colleague's email address, not yours."}])
    now = utcnow()
    f = QuestionnaireSend(questionnaire_id=s.questionnaire_id, contact_name=name, contact_email=email, question_codes=list(s.question_codes), due_on=s.due_on,
                          reminder_days=list(s.reminder_days or []), reminders_sent=[], allow_forward=s.allow_forward, forwarded_from_id=root, status="sent",
                          expires_at=now + timedelta(days=LINK_DAYS), subject=s.subject, message=FORWARD_MESSAGE, sent_by=s.sent_by, sent_at=now)
    db.add(f)
    db.flush()
    rep = db.get(User, s.sent_by) if s.sent_by else None
    link = _issue(settings, f)
    _deliver(db, settings, f, rep, s.subject or SUBJECT, FORWARD_MESSAGE, link, _values(db, f, rep, {"Forwarded by": s.contact_name}))
    db.flush()
    return f


# ---- daily job: reminders and the partly-answered notice
def run_reminders(db: Session, settings: Settings, now: datetime | None = None) -> int:
    now = now or utcnow()
    sent = 0
    rows = db.scalars(select(QuestionnaireSend).where(QuestionnaireSend.submitted_at.is_(None), QuestionnaireSend.revoked_at.is_(None)))
    for s in list(rows):
        if s.expires_at is not None and s.expires_at <= now:
            if s.status != "expired":
                s.status = "expired"
            continue
        due_days = [d for d in s.reminder_days or [] if d not in (s.reminders_sent or []) and now >= s.sent_at + timedelta(days=d)]
        if due_days:
            rep = db.get(User, s.sent_by) if s.sent_by else None
            link = _issue(settings, s)
            _deliver(db, settings, s, rep, f"Reminder: {s.subject or SUBJECT}", REMINDER_MESSAGE, link, _values(db, s, rep), reminder=True)
            s.reminders_sent = sorted(set(s.reminders_sent or []) | set(due_days))
            sent += 1
        if s.due_on is not None and now.date() > s.due_on and s.partial_notified_at is None and s.last_saved_at is not None:
            s.partial_notified_at = now
            _tell_owner(db, settings, s, complete=False)
    db.flush()
    return sent


def send_out(db: Session, s: QuestionnaireSend) -> dict:
    expired = s.expires_at is not None and s.expires_at <= utcnow() and s.submitted_at is None
    return {"id": s.id, "contact_name": s.contact_name, "contact_email": s.contact_email, "question_count": len(s.question_codes or []),
            "answered": _answered(db, s), "status": "expired" if expired and s.status not in ("revoked",) else s.status,
            "due_on": s.due_on.isoformat() if s.due_on else None, "sent_at": s.sent_at.isoformat(), "opened_at": s.opened_at.isoformat() if s.opened_at else None,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None, "reminder_days": s.reminder_days, "reminders_sent": s.reminders_sent,
            "forwarded": s.forwarded_from_id is not None, "closed": s.revoked_at is not None}
