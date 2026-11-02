"""AI literacy training (spec §21 F12, screen 33).

Modules are assigned by department, by platform role or by email group. Assigning creates one TrainingAssignment per
person and sends each a personal link through the email service (campaign type "training"; reminders reuse the email
service's reminder plan). People with a login also find their modules under "My training". A learner passes by
scoring at least the module's pass mark; the first answer to each question in an attempt counts.

Completion feeds: the named users of the client's current engagement (`NamedUser.training_complete`) once a person has
finished every module assigned to them; and, on request, a completion record saved as evidence on the AI literacy and
training owner role (EU AI Act Art. 4). The monitoring checks are in `monitor_checks.py`.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.errors import Conflict, Invalid, NotFound
from app.mail import sending
from app.mail.groups import create_group, default_group
from app.mail.models import DirectoryPerson, MailGroup, MailSend
from app.policy.roles import CLIENT_ROLES, role_label
from app.tenancy.models import Department, Organization, User
from app.training import modules as M
from app.training.models import TrainingAssignment, TrainingCampaign, TrainingModule, TrainingProgram

CAMPAIGN = "training"
TEMPLATE_KEY = "training_ai_literacy"
DEFAULT_TARGET = 80


# ---- content
def ensure_modules(db: Session) -> dict[str, TrainingModule]:
    out = {}
    for code, m in M.library().items():
        row = db.scalar(select(TrainingModule).where(TrainingModule.code == code, TrainingModule.version == m["version"]))
        if row is None:
            raw = json.dumps(m, sort_keys=True)
            row = TrainingModule(code=code, version=m["version"], title=m["title"], minutes=m["minutes"], audience=m.get("audience"), pass_mark=m["pass_mark"],
                                 content=m, content_sha256=hashlib.sha256(raw.encode()).hexdigest())
            db.add(row)
            db.flush()
        out[code] = row
    return out


def module_of(db: Session, a: TrainingAssignment) -> dict:
    row = db.get(TrainingModule, a.module_id)
    if row is None:
        raise NotFound()
    return row.content


def program(db: Session, org_id: str) -> TrainingProgram:
    p = db.scalar(select(TrainingProgram).where(TrainingProgram.organization_id == org_id, TrainingProgram.deleted_at.is_(None)))
    if p is None:
        p = TrainingProgram(organization_id=org_id, target_pct=DEFAULT_TARGET, evidence_file_ids=[])
        db.add(p)
        db.flush()
    return p


def set_program(db: Session, actor: User, org_id: str, data: dict) -> TrainingProgram:
    p = program(db, org_id)
    errs = []
    pct = data.get("target_pct", p.target_pct)
    try:
        pct = int(pct)
        if not 1 <= pct <= 100:
            raise ValueError
    except (TypeError, ValueError):
        errs.append({"field": "target_pct", "message": "Enter a target from 1 to 100 percent."})
    d = p.target_date
    if "target_date" in data:
        try:
            d = date.fromisoformat(str(data["target_date"])) if data["target_date"] else None
        except ValueError:
            errs.append({"field": "target_date", "message": "Enter a date."})
    if errs:
        raise Invalid(errors=errs)
    before = {"target_pct": p.target_pct, "target_date": p.target_date.isoformat() if p.target_date else None}
    p.target_pct, p.target_date, p.updated_by = pct, d, actor.id
    audit.record(db, actor_id=actor.id, action="training.target", obj=p, before=before, after={"target_pct": pct, "target_date": d.isoformat() if d else None},
                 summary=f"Set the AI literacy training target to {pct}%" + (f" by {d:%d %B %Y}" if d else ""))
    return p


# ---- audiences
def _role_group(db: Session, actor: User, org_id: str, role: str) -> MailGroup:
    if role not in {r.value for r in CLIENT_ROLES}:
        raise Invalid(errors=[{"field": "audience.role", "message": "Choose a role."}])
    name = f"Training · {role_label(role)}"
    g = db.scalar(select(MailGroup).where(MailGroup.organization_id == org_id, MailGroup.name == name, MailGroup.deleted_at.is_(None)))
    return g or create_group(db, actor, org_id, name=name, source="rule", rule={"kind": "role", "role": role}, purpose="Everyone who holds this role",
                             used_by="AI literacy training")


def audience_args(db: Session, actor: User, org_id: str, audience: dict) -> tuple[list[str], list[str] | None, str]:
    """(group ids, department ids or None, label) for the email service."""
    audience = audience if isinstance(audience, dict) else {}
    kind = audience.get("kind")
    ids = [i for i in audience.get("ids") or [] if isinstance(i, str)]
    if kind == "departments":
        depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org_id, Department.deleted_at.is_(None)))}
        if not ids or any(i not in depts for i in ids):
            raise Invalid(errors=[{"field": "audience.ids", "message": "Choose at least one department."}])
        return [default_group(db, org_id, "all_employees").id], ids, ", ".join(depts[i] for i in ids)
    if kind == "role":
        role = str(audience.get("role") or "")
        return [_role_group(db, actor, org_id, role).id], None, role_label(role)
    if kind == "groups":
        groups = list(db.scalars(select(MailGroup).where(MailGroup.id.in_(ids), MailGroup.organization_id == org_id, MailGroup.deleted_at.is_(None)))) if ids else []
        if not groups or len(groups) != len(set(ids)):
            raise Invalid(errors=[{"field": "audience.ids", "message": "Choose at least one group."}])
        return [g.id for g in groups], None, ", ".join(g.name for g in groups)
    raise Invalid(errors=[{"field": "audience.kind", "message": "Assign by department, role or group."}])


def _modules(db: Session, codes) -> list[TrainingModule]:
    rows = ensure_modules(db)
    codes = [c for c in dict.fromkeys(codes or []) if isinstance(c, str)]
    if not codes or any(c not in rows for c in codes):
        raise Invalid(errors=[{"field": "module_codes", "message": "Choose at least one module."}])
    return [rows[c] for c in codes]


def preview(db: Session, actor: User, org_id: str, body: dict) -> dict:
    _modules(db, body.get("module_codes"))
    group_ids, dept_ids, label = audience_args(db, actor, org_id, body.get("audience"))
    ex = sending.expand(db, org_id, group_ids, department_ids=dept_ids)
    return {"label": label, "steps": ex.steps, "total": len(ex.people), "people": [{"name": p.name, "email": p.email} for p in ex.people[:500]]}


def _open_or_done(db: Session, org_id: str, module: TrainingModule) -> set[str]:
    """Emails that already have this module: still open, or completed in this version."""
    rows = db.scalars(select(TrainingAssignment).where(TrainingAssignment.organization_id == org_id, TrainingAssignment.module_code == module.code,
                                                       TrainingAssignment.deleted_at.is_(None)))
    return {a.email for a in rows if a.status != "completed" or a.module_id == module.id}


def assign(db: Session, settings, actor: User, org: Organization, body: dict) -> dict:
    mods = _modules(db, body.get("module_codes"))
    group_ids, dept_ids, label = audience_args(db, actor, org.id, body.get("audience"))
    due = None
    if body.get("due_date"):
        try:
            due = date.fromisoformat(str(body["due_date"]))
        except ValueError:
            raise Invalid(errors=[{"field": "due_date", "message": "Enter a date."}]) from None
        if due <= today():
            raise Invalid(errors=[{"field": "due_date", "message": "The due date must be in the future."}])
    ex = sending.expand(db, org.id, group_ids, department_ids=dept_ids)
    users = {u.email.lower(): u for u in db.scalars(select(User).where(User.organization_id == org.id, User.deleted_at.is_(None)))}
    total, campaigns = 0, []
    for mod in mods:
        have = _open_or_done(db, org.id, mod)
        new = [p for p in ex.people if p.email.lower() not in have]
        if not new:
            continue
        c = TrainingCampaign(organization_id=org.id, module_id=mod.id, module_code=mod.code, due_date=due,
                             audience={"kind": (body.get("audience") or {}).get("kind"), "label": label}, assigned_by=actor.id, created_by=actor.id)
        db.add(c)
        db.flush()
        for p in new:
            u = users.get(p.email.lower())
            db.add(TrainingAssignment(organization_id=org.id, campaign_id=c.id, module_id=mod.id, module_code=mod.code, email=p.email.lower(), name=p.name,
                                      person_id=p.id, user_id=(p.user_id or (u.id if u else None)), department_id=p.department_id, due_date=due, status="assigned",
                                      answers={}, created_by=actor.id))
        db.flush()
        if body.get("send_email", True):
            days = body.get("reminder_days")
            s = sending.send_to_groups(db, settings, actor, organization_id=org.id, group_ids=group_ids, department_ids=dept_ids, template_key=TEMPLATE_KEY,
                                       exclude_responded=True, campaign=(CAMPAIGN, c.id), mode="personal",
                                       reminder_days=[3, 7] if days is None else [int(d) for d in days if str(d).isdigit()] or None,
                                       link_days=int(body.get("link_days") or 30), context={"Module": M.for_client(mod.content, org.name)["title"]}, related=c)
            c.send_id = s.id
        total += len(new)
        campaigns.append(c.id)
        audit.record(db, actor_id=actor.id, action="training.assign", obj=c, after={"module": f"{mod.code} v{mod.version}", "people": len(new), "audience": label},
                     summary=f"Assigned {mod.code.replace('_', ' ')} to {len(new)} {'person' if len(new) == 1 else 'people'} ({label})")
    return {"assigned": total, "campaign_ids": campaigns}


def responded(db: Session, campaign_id: str) -> set[str]:
    """For the email service: everyone who should not get this campaign's email or reminders — people who finished the
    module, and people whose open assignment for it belongs to another campaign."""
    c = db.get(TrainingCampaign, campaign_id)
    if c is None:
        return set()
    rows = list(db.scalars(select(TrainingAssignment).where(TrainingAssignment.organization_id == c.organization_id, TrainingAssignment.module_code == c.module_code,
                                                            TrainingAssignment.deleted_at.is_(None))))
    waiting_here = {a.email for a in rows if a.campaign_id == c.id and a.status != "completed"}
    return {a.email for a in rows} - waiting_here


# ---- the learner
def for_user(db: Session, user: User) -> list[TrainingAssignment]:
    return list(db.scalars(select(TrainingAssignment).where(TrainingAssignment.organization_id == user.organization_id, TrainingAssignment.deleted_at.is_(None),
                                                            (TrainingAssignment.user_id == user.id) | (func.lower(TrainingAssignment.email) == user.email.lower()))
                           .order_by(TrainingAssignment.status == "completed", TrainingAssignment.due_date, TrainingAssignment.created_at)))


def by_email(db: Session, org_id: str, campaign_id: str, email: str) -> TrainingAssignment:
    c = db.get(TrainingCampaign, campaign_id)
    if c is None or c.organization_id != org_id:
        raise NotFound("This link is not valid.")
    a = db.scalar(select(TrainingAssignment).where(TrainingAssignment.organization_id == org_id, TrainingAssignment.module_code == c.module_code,
                                                   TrainingAssignment.email == email.lower(), TrainingAssignment.deleted_at.is_(None))
                  .order_by(TrainingAssignment.status == "completed", TrainingAssignment.created_at.desc()).limit(1))
    if a is None:
        raise NotFound("This link is not valid.")
    return a


def assignment_out(db: Session, a: TrainingAssignment, company: str) -> dict:
    m = module_of(db, a)
    return {"id": a.id, "module": M.card(m, company), "status": a.status, "due_date": a.due_date.isoformat() if a.due_date else None,
            "started_at": a.started_at.isoformat() if a.started_at else None, "completed_at": a.completed_at.isoformat() if a.completed_at else None,
            "score": a.score, "attempts": a.attempts, "overdue": a.status != "completed" and a.due_date is not None and a.due_date < today()}


def player(db: Session, a: TrainingAssignment, company: str) -> dict:
    m = module_of(db, a)
    answered = {}
    for qid, opt in (a.answers or {}).items():
        q = M.question(m, qid)
        if q is not None:
            answered[qid] = {"option_id": opt, "correct": opt == q["answer"], "explanation": M.for_client(q, company)["explanation"], "correct_option": q["answer"]}
    return assignment_out(db, a, company) | {"name": a.name, "module": M.learner_view(m, company), "answered": answered}


def check(db: Session, a: TrainingAssignment, qid: str, option_id: str, company: str) -> dict:
    if a.status == "completed":
        raise Conflict("You have completed this module.")
    m = module_of(db, a)
    q = M.question(m, str(qid or ""))
    if q is None or option_id not in {o["id"] for o in q["options"]}:
        raise Invalid(errors=[{"field": "option_id", "message": "Choose one of the answers."}])
    answers = dict(a.answers or {})
    if qid not in answers:  # the first answer counts for this attempt
        answers[qid] = option_id
        a.answers = answers
    if a.status == "assigned":
        a.status, a.started_at = "in_progress", a.started_at or utcnow()
    chosen = answers[qid]
    return {"question_id": qid, "option_id": chosen, "correct": chosen == q["answer"], "correct_option": q["answer"],
            "explanation": M.for_client(q, company)["explanation"]}


def finish(db: Session, a: TrainingAssignment, actor_id: str | None = None) -> dict:
    if a.status == "completed":
        return {"passed": True, "score": a.score, "attempts": a.attempts, "status": a.status, "certificate_no": a.certificate_no}
    m = module_of(db, a)
    missing = [q["id"] for q in m["quiz"] if q["id"] not in (a.answers or {})]
    if missing:
        raise Invalid(f"Answer every question first ({len(missing)} left).", [{"field": q, "message": "Answer this question."} for q in missing])
    s = M.score(m, a.answers)
    a.attempts = (a.attempts or 0) + 1
    passed = s >= m["pass_mark"]
    a.score = s
    if passed:
        a.status, a.completed_at = "completed", utcnow()
        a.certificate_no = f"FTC-{secrets.token_hex(5).upper()}"
        audit.record(db, actor_id=actor_id, actor_name=a.name or a.email, action="training.complete", obj=a, organization_id=a.organization_id,
                     after={"module": a.module_code, "score": s, "attempts": a.attempts}, summary=f"{a.name or a.email} completed {m['code'].replace('_', ' ')} with {s}%")
        _feed_named_users(db, a)
    else:
        a.answers, a.status = {}, "in_progress"
    return {"passed": passed, "score": s, "attempts": a.attempts, "status": a.status, "pass_mark": m["pass_mark"], "certificate_no": a.certificate_no}


def _feed_named_users(db: Session, a: TrainingAssignment) -> None:
    """Once the person has finished every module assigned to them, their named-user rows in the client's current
    engagement show training complete (§21 F12). Closed engagements are never changed."""
    from app.engagements.models import Engagement
    from app.inventory.models import NamedUser, UseCase
    from app.sales.service import CURRENT_ENGAGEMENT

    open_left = db.scalar(select(func.count(TrainingAssignment.id)).where(TrainingAssignment.organization_id == a.organization_id, TrainingAssignment.email == a.email,
                                                                          TrainingAssignment.status != "completed", TrainingAssignment.deleted_at.is_(None)))
    if open_left:
        return
    from sqlalchemy import or_

    who = [func.lower(NamedUser.email) == a.email] + ([NamedUser.user_id == a.user_id] if a.user_id else [])
    rows = db.scalars(select(NamedUser).join(UseCase, UseCase.id == NamedUser.use_case_id).join(Engagement, Engagement.id == UseCase.engagement_id).where(
        NamedUser.organization_id == a.organization_id, NamedUser.deleted_at.is_(None), Engagement.status.in_(CURRENT_ENGAGEMENT), or_(*who)))
    for n in rows:
        if n.training_complete is not True:
            n.training_complete = True
            audit.record(db, actor_id=None, actor_name="AI literacy training", action="inventory.named_user_training", obj=n, after={"training_complete": True},
                         summary=f"{n.person_name}: training complete (finished every assigned AI literacy module)")


def certificate_pdf(db: Session, a: TrainingAssignment) -> bytes:
    from app.documents.pdf import to_pdf

    if a.status != "completed":
        raise Conflict("The certificate is available once the module is completed.")
    org = db.get(Organization, a.organization_id)
    m = M.for_client(module_of(db, a), org.name)
    md = (f"# Certificate of completion\n\n**{a.name or a.email}** completed the AI literacy module\n\n## {m['title']}\n\n"
          f"on {a.completed_at:%d %B %Y} with a quiz score of {a.score}% (pass mark {m['pass_mark']}%).\n\n"
          f"- Organization: {org.name}\n- Module: Futran {m['code'].replace('_', ' ')} module, version {m['version']}, about {m['minutes']} minutes\n"
          f"- Certificate number: {a.certificate_no}\n\n"
          "This module supports the organization's AI acceptable use policy and its measures to support AI literacy under "
          "Article 4 of the EU AI Act, as amended by Regulation (EU) 2026/1744. Content by Futran Solutions.\n")
    return to_pdf(md, f"Certificate {a.certificate_no}", {"audit_ref": org.name})


# ---- the owner's view
def _latest(db: Session, org_id: str) -> list[TrainingAssignment]:
    return list(db.scalars(select(TrainingAssignment).where(TrainingAssignment.organization_id == org_id, TrainingAssignment.deleted_at.is_(None))))


def _pct(done: int, total: int) -> int | None:
    return round(100 * done / total) if total else None


def overview(db: Session, org: Organization) -> dict:
    mods = ensure_modules(db)
    prog = program(db, org.id)
    rows = _latest(db, org.id)
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org.id, Department.deleted_at.is_(None)).order_by(Department.name))}
    cards = []
    for code, mod in mods.items():
        mine = [a for a in rows if a.module_code == code]
        done = sum(a.status == "completed" for a in mine)
        cards.append(M.card(mod.content, org.name) | {"assigned": len(mine), "completed": done, "pct": _pct(done, len(mine))})
    by_dept = []
    for did, name in list(depts.items()) + [(None, "No department recorded")]:
        mine = [a for a in rows if a.department_id == did]
        if not mine:
            continue
        done = sum(a.status == "completed" for a in mine)
        pct = _pct(done, len(mine))
        by_dept.append({"id": did, "name": name, "assigned": len(mine), "completed": done, "pct": pct, "below_target": pct is not None and pct < prog.target_pct})
    done = sum(a.status == "completed" for a in rows)
    return {"modules": cards, "departments": by_dept,
            "overall": {"assigned": len(rows), "completed": done, "pct": _pct(done, len(rows)), "overdue": sum(a.status != "completed" and a.due_date is not None and a.due_date < today() for a in rows)},
            "program": {"target_pct": prog.target_pct, "target_date": prog.target_date.isoformat() if prog.target_date else None,
                        "evidence": [{"id": f} for f in prog.evidence_file_ids or []]}}


def assignment_rows(db: Session, org: Organization, module_code: str | None = None) -> list[dict]:
    depts = {d.id: d.name for d in db.scalars(select(Department).where(Department.organization_id == org.id))}
    out = []
    for a in sorted(_latest(db, org.id), key=lambda a: ((a.name or a.email).lower(), a.module_code)):
        if module_code and a.module_code != module_code:
            continue
        out.append(assignment_out(db, a, org.name) | {"name": a.name, "email": a.email, "department": depts.get(a.department_id)})
    return out


def send_reminders(db: Session, settings, actor: User, org_id: str, module_code: str | None = None) -> int:
    from app.mail.reminders import non_responders, remind

    n = 0
    q = select(TrainingCampaign).where(TrainingCampaign.organization_id == org_id, TrainingCampaign.deleted_at.is_(None), TrainingCampaign.send_id.is_not(None))
    if module_code:
        q = q.where(TrainingCampaign.module_code == module_code)
    for c in db.scalars(q):
        s = db.get(MailSend, c.send_id)
        if s is None:
            continue
        rem = remind(db, settings, s, non_responders(db, s), utcnow(), actor=actor)
        n += rem.recipient_count if rem is not None else 0
    audit.record(db, actor_id=actor.id, action="training.remind", organization_id=org_id, object_type="TrainingProgram", object_id=program(db, org_id).id,
                 summary=f"Sent AI literacy training reminders to {n} {'person' if n == 1 else 'people'}")
    return n


def save_evidence(db: Session, settings, actor: User, org: Organization) -> dict:
    """A dated completion record (PDF) kept on the training programme and on the company-wide AI literacy owner role."""
    from app.documents.pdf import to_pdf
    from app.files.service import upload
    from app.training.access import owner_assignments

    ov = overview(db, org)
    lines = [f"# AI literacy training record\n\n{org.name}, as at {utcnow():%d %B %Y}. Target {ov['program']['target_pct']}% completion"
             + (f" by {date.fromisoformat(ov['program']['target_date']):%d %B %Y}" if ov['program']['target_date'] else "") + ".\n",
             f"Overall: {ov['overall']['completed']} of {ov['overall']['assigned']} assignments completed"
             + (f" ({ov['overall']['pct']}%)" if ov['overall']['pct'] is not None else "") + ".\n", "## By module\n"]
    lines += [f"- {m['title']}: {m['completed']} of {m['assigned']} completed" for m in ov["modules"] if m["assigned"]]
    lines += ["\n## By department\n"] + [f"- {d['name']}: {d['completed']} of {d['assigned']} ({d['pct']}%)" + (" — below target" if d["below_target"] else "") for d in ov["departments"]]
    lines += ["\nFutran modules support the organization's measures to support the AI literacy of its staff (EU AI Act Art. 4, as amended by Regulation (EU) 2026/1744)."]
    data = to_pdf("\n".join(lines) + "\n", "AI literacy training record", {"audit_ref": org.name})
    f = upload(db, settings, actor, data=data, filename=f"AI literacy training record {utcnow():%Y-%m-%d}.pdf", content_type="application/pdf",
               organization_id=org.id, linked_type="training_record", linked_id=program(db, org.id).id)
    prog = program(db, org.id)
    prog.evidence_file_ids = [*(prog.evidence_file_ids or []), f.id]
    roles = owner_assignments(db, org.id)
    for r in roles:
        r.evidence_ids = [*(r.evidence_ids or []), f.id]
    audit.record(db, actor_id=actor.id, action="training.evidence", obj=prog, after={"file_id": f.id, "roles_updated": len(roles)},
                 summary="Saved the AI literacy training record as evidence" + (" on the AI literacy and training owner role" if roles else ""))
    return {"file_id": f.id, "filename": f.filename, "roles_updated": len(roles)}
