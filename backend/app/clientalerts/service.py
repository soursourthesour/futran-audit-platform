"""Client alerts: queue one send per affected client, wait for approval where the rule says so, then email it
(spec §27.6). Each email lists only that client's affected systems and the to-dos from the Requirement rows."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.clientalerts.models import AlertRule, AlertSend
from app.core.clock import utcnow
from app.core.config import Settings
from app.laws.models import Regulation
from app.litigation.models import Case, CaseClientMatch
from app.register.models import RegisterSystem, RegisterSystemLaw
from app.regmaster.models import ChangeImpact, ClientLawApplicability, LawVersion, ProposedChange, Requirement
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

DEFAULT_RULES = [
    # trigger, audience, groups, email label, approval, days_before
    ("law_change", "law_applies", ["AIComplianceTeam"], "New or changed rule: what to do", "chief_auditor", []),
    ("new_law", "geography", ["AIComplianceTeam"], "New AI law: does it apply to you?", "chief_auditor", []),
    ("effective_date", "law_applies", ["AIComplianceTeam", "DeptHeads"], "Deadline reminder with to-do list", "automatic", [90, 30]),
    ("case", "similar_ai", ["AIComplianceTeam"], "Case briefing: what it means for you", "chief_auditor", []),
    ("tracing_addon", "untraced_systems", ["ChiefAIComplianceOfficer"], "Recommended add-on", "sales_owner", []),
]
WHEN_LABELS = {
    "law_change": "Law change approved", "new_law": "New law in a client's geography", "effective_date": "Effective date in 90 and 30 days",
    "case": "Relevant case added or updated", "tracing_addon": "Tracing add-on recommended",
}
AUDIENCE_LABELS = {
    "law_applies": "Every client where the law applies", "geography": "Clients in that geography", "similar_ai": "Clients using similar AI",
    "untraced_systems": "Clients with Tier 3 or agent systems untraced",
}
APPROVAL_LABELS = {"chief_auditor": "Chief Auditor approves each send", "automatic": "Automatic", "sales_owner": "Sales Team owner approves"}
GROUP_ROLES = {"AIComplianceTeam": {"caico", "dpo"}, "DeptHeads": {"dept_compliance_lead"}, "ChiefAIComplianceOfficer": {"caico"}}
CHANGE_LABELS = {
    "new_rule": "New rule", "amendment": "Amended law", "effective_date": "Date change", "guidance": "New guidance", "new_law": "New AI law",
    "repeal": "Law repealed", "role_mapping": "Role change", "enforcement": "Enforcement",
}


def ensure_rules(db: Session) -> list[AlertRule]:
    have = {r.trigger: r for r in db.scalars(select(AlertRule))}
    for i, (trigger, audience, groups, label, approval, days) in enumerate(DEFAULT_RULES):
        if trigger not in have:
            r = AlertRule(trigger=trigger, audience_rule=audience, client_groups=groups, email_label=label, approval=approval, days_before=days, active=trigger != "tracing_addon", order=i)
            db.add(r)
            have[trigger] = r
    db.flush()
    return sorted(have.values(), key=lambda r: r.order)


def rule_for(db: Session, trigger: str) -> AlertRule | None:
    ensure_rules(db)
    return db.scalar(select(AlertRule).where(AlertRule.trigger == trigger).order_by(AlertRule.order).limit(1))


def _deadline(v: LawVersion | None) -> date | None:
    return (v.compliance_on or v.effective_on) if v else None


def _todos(db: Session, version: LawVersion | None, law_name: str, first_code: str | None = None) -> list[dict]:
    if version is None:
        return []
    reqs = list(db.scalars(select(Requirement).where(Requirement.law_version_id == version.id).order_by(Requirement.order, Requirement.code)))
    if first_code:
        reqs.sort(key=lambda r: r.code != first_code)
    d = _deadline(version)
    return [{"code": r.code, "text": r.text, "deadline": d.isoformat() if d else None, "law": law_name} for r in reqs]


def _queue(db: Session, settings: Settings, rule: AlertRule, org_id: str, change_ref: str, headline: str, systems: list[str], todos: list[dict],
           deadline: date | None, owner_id: str | None = None, actor_id: str | None = None) -> AlertSend:
    existing = db.scalar(select(AlertSend).where(AlertSend.alert_rule_id == rule.id, AlertSend.organization_id == org_id, AlertSend.change_ref == change_ref))
    if existing is not None:
        return existing
    s = AlertSend(alert_rule_id=rule.id, organization_id=org_id, change_ref=change_ref[:120], headline=headline[:300], affected_system_ids=systems,
                  todo_items=todos, deadline=deadline, status="waiting_approval", owner_id=owner_id, created_by=actor_id, sent_from=sender_label(db, org_id))
    db.add(s)
    db.flush()
    if rule.approval == "automatic":
        deliver(db, settings, s, approver_id=None)
    return s


def queue_for_change(db: Session, settings: Settings, change: ProposedChange, actor_id: str | None = None) -> list[AlertSend]:
    """After the Chief Auditor approves a law change (M3): one send per affected client, waiting for approval."""
    rule = rule_for(db, "new_law" if change.change_type == "new_law" else "law_change")
    if rule is None or not rule.active:
        return []
    reg = db.get(Regulation, change.regulation_id) if change.regulation_id else None
    version = db.get(LawVersion, change.applied_version_id) if change.applied_version_id else (db.get(LawVersion, reg.current_version_id) if reg and reg.current_version_id else None)
    law_name = reg.short_name if reg else "New law"
    code = change.field_path.split(".", 1)[1] if change.field_path.startswith("requirement.") else None
    todos = _todos(db, version, law_name, code)
    headline = f"{CHANGE_LABELS.get(change.change_type, 'Change')}: {law_name}: {change.summary}"
    out = []
    targets = [(imp.organization_id, list(imp.ai_system_ids or [])) for imp in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == change.id).order_by(ChangeImpact.created_at))]
    if change.change_type == "new_law" and change.jurisdiction_id:
        from app.regmaster.models import ClientGeography

        seen = {o for o, _ in targets}
        for org_id in dict.fromkeys(db.scalars(select(ClientGeography.organization_id).where(ClientGeography.jurisdiction_id == change.jurisdiction_id, ClientGeography.deleted_at.is_(None)))):
            if org_id not in seen:
                targets.append((org_id, []))
    for org_id, systems in targets:
        out.append(_queue(db, settings, rule, org_id, f"change:{change.id}", headline, systems, todos, _deadline(version), actor_id=actor_id))
    return out


def queue_for_case(db: Session, settings: Settings, case: Case, org_ids: list[str] | None = None, actor_id: str | None = None) -> list[AlertSend]:
    """A case briefing for each client using similar AI (L1, L2), waiting for the Chief Auditor."""
    rule = rule_for(db, "case")
    if rule is None or not rule.active:
        return []
    lines = [ln.strip(" -•\t") for ln in (case.talking_points_client or "").splitlines() if ln.strip(" -•\t")]
    todos = [{"code": f"{i}", "text": t, "deadline": None, "law": case.name} for i, t in enumerate(lines, start=1)]
    out = []
    for m in db.scalars(select(CaseClientMatch).where(CaseClientMatch.case_id == case.id)):
        if org_ids is not None and m.organization_id not in org_ids:
            continue
        out.append(_queue(db, settings, rule, m.organization_id, f"case:{case.id}:v{case.version}", f"Case briefing: {case.name}", list(m.ai_system_ids or []), todos, None, actor_id=actor_id))
    return out


def queue_effective_dates(db: Session, settings: Settings, on: date) -> list[AlertSend]:
    """Daily: deadline reminders 90 and 30 days before a law's compliance (or effective) date. Sent automatically."""
    rule = rule_for(db, "effective_date")
    if rule is None or not rule.active:
        return []
    marks = sorted(rule.days_before or [90, 30], reverse=True)
    out = []
    for reg in db.scalars(select(Regulation).where(Regulation.current_version_id.is_not(None))):
        v = db.get(LawVersion, reg.current_version_id)
        d = _deadline(v)
        if d is None:
            continue
        left = (d - on).days
        for i, mark in enumerate(marks):
            lower = marks[i + 1] if i + 1 < len(marks) else -1
            if lower < left <= mark:
                for app_row in db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.regulation_id == reg.id, ClientLawApplicability.in_scope.is_(True))):
                    ref = f"date:{v.id}:{mark}"
                    if db.scalar(select(AlertSend.id).where(AlertSend.alert_rule_id == rule.id, AlertSend.organization_id == app_row.organization_id, AlertSend.change_ref == ref)):
                        continue
                    systems = list(db.scalars(select(RegisterSystemLaw.register_system_id).where(RegisterSystemLaw.organization_id == app_row.organization_id, RegisterSystemLaw.regulation_id == reg.id, RegisterSystemLaw.status == "active")))
                    out.append(_queue(db, settings, rule, app_row.organization_id, ref, f"{reg.short_name}: {mark} days to {d.day} {d:%B %Y}", systems, _todos(db, v, reg.short_name), d))
    return out


def queue_tracing_addon(db: Session, settings: Settings, org_id: str, system_ids: list[str], owner_id: str | None, ref: str) -> AlertSend | None:
    rule = rule_for(db, "tracing_addon")
    if rule is None or not rule.active:
        return None
    todos = [{"code": "1", "text": "Review the systems below and decide whether to add tracing and incident logging.", "deadline": None, "law": "Tracing add-on"}]
    return _queue(db, settings, rule, org_id, f"addon:{ref}", "Recommended add-on: tracing for high-risk and agent systems", system_ids, todos, None, owner_id=owner_id)


# ---- delivery
GROUP_KEYS = {"AIComplianceTeam": "ai_compliance_team", "DeptHeads": "dept_heads"}  # E3 default client groups


def sender_label(db: Session, org_id: str, settings: Settings | None = None) -> str:
    """The client's own mailbox when connected (E2), else Futran on the client's behalf."""
    from app.mail.delivery import org_connection

    conn = org_connection(db, org_id)
    if conn is not None and conn.status == "connected" and conn.sender_mode == "own" and conn.mailbox_address:
        return conn.mailbox_address
    return "Futran on behalf (no client mailbox)"


def _caico_users(db: Session, org_id: str, roles: set[str]) -> list[User]:
    out = []
    for u in db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None), User.status != "disabled").order_by(User.name)):
        if {r.role for r in roles_of(db, u.id)} & roles:
            out.append(u)
    return out


def _group_ids(db: Session, org_id: str, groups: list[str]) -> list[str]:
    from app.mail.groups import default_group

    ids = []
    for g in groups:
        key = GROUP_KEYS.get(g)
        grp = default_group(db, org_id, key) if key else None
        if grp is not None:
            ids.append(grp.id)
    return ids


def group_recipients(db: Session, org_id: str, groups: list[str]) -> tuple[list[str], list[str], bool]:
    """(group ids, emails, fell_back). Groups are expanded as E4 would; when they hold no one, the alert goes to the
    client's Chief AI Compliance Officer directly so it is not lost."""
    from app.mail.sending import preview_expansion

    ids = _group_ids(db, org_id, groups)
    people = preview_expansion(db, org_id, ids).people if ids else []
    if people:
        return ids, [p.email for p in people], False
    roles = set().union(*(GROUP_ROLES.get(g, set()) for g in groups)) if groups else {"caico"}
    return [], [u.email for u in _caico_users(db, org_id, roles)], True


def system_names(db: Session, ids: list[str]) -> list[str]:
    out = []
    for sid in ids or []:
        s = db.get(RegisterSystem, sid)
        if s is None:
            from app.systems.models import AISystem

            s = db.get(AISystem, sid)
        if s is not None:
            out.append(s.name)
    return out


def subject_of(db: Session, s: AlertSend) -> str:
    if s.subject:
        return s.subject
    n = len(s.affected_system_ids or [])
    return s.headline + (f" · {n} {'system' if n == 1 else 'systems'} affected" if n else "")


FOOTER = "From Futran Solutions, your independent AI governance auditor. General information, not legal advice."


def paragraphs(db: Session, s: AlertSend) -> list[str]:
    """The email body, one entry per paragraph; "[Link]" becomes the button into the platform."""
    out = ["Hi [First name],", s.headline]
    if s.intro:
        out.append(s.intro)
    names = system_names(db, s.affected_system_ids)
    if names:
        out.append("Affects: " + ", ".join(names))
    if s.todo_items:
        out.append("What to do:\n" + "\n".join(f"- {t['text']}" for t in s.todo_items))
    if s.deadline:
        out.append(f"By: {s.deadline.day} {s.deadline:%B %Y}")
    out += ["[Link]", FOOTER]
    return out


def preview(db: Session, settings: Settings, s: AlertSend) -> dict:
    from app.mail.service import render

    rule = db.get(AlertRule, s.alert_rule_id)
    _, emails, fell_back = group_recipients(db, s.organization_id, rule.client_groups if rule else [])
    subject, html, text = render("client_alert", {"subject": subject_of(db, s), "paragraphs": [p.replace("[First name]", "[first name]") for p in paragraphs(db, s)],
                                                  "link": f"{settings.base_url}/start", "button": "Open the to-dos in Futran Audit"})
    return {"subject": subject, "html": html, "text": text, "from": sender_label(db, s.organization_id), "to": emails, "groups": rule.client_groups if rule else [],
            "fallback": fell_back}


def deliver(db: Session, settings: Settings, s: AlertSend, approver_id: str | None) -> AlertSend:
    """Send through the group email service (E4: client mailbox where connected, logged in E5). If the client group
    is empty, email the Chief AI Compliance Officer directly and say so in the admin log."""
    from app.mail import adminlog

    rule = db.get(AlertRule, s.alert_rule_id)
    approver = db.get(User, approver_id) if approver_id else None
    ids, emails, fell_back = group_recipients(db, s.organization_id, rule.client_groups)
    if not emails:
        s.status = "held"
        adminlog.write(db, organization_id=s.organization_id, category="send", action="alert_not_sent", actor=approver,
                       summary=f"Client alert held: nobody in {', '.join(rule.client_groups)} and no Chief AI Compliance Officer to send to")
        return s
    if not fell_back:
        from app.mail import library
        from app.mail.sending import send_to_groups

        library.ensure_defaults(db)
        ms = send_to_groups(db, settings, approver, organization_id=s.organization_id, group_ids=ids, template_key="regulatory_change_alert",
                            subject=subject_of(db, s), body="\n\n".join(paragraphs(db, s)), sender="organization", mode="personal", related=s)
        s.mail_send_id = ms.id
    else:
        from app.mail.service import send

        msg = send(db, settings, "client_alert", to=emails, organization_id=s.organization_id, related=s, actor_id=approver_id,
                   context={"subject": subject_of(db, s), "paragraphs": [p.replace("[First name]", "there") for p in paragraphs(db, s)],
                            "link": f"{settings.base_url}/start", "button": "Open the to-dos in Futran Audit"})
        s.outbox_message_id = msg.id
        adminlog.write(db, organization_id=s.organization_id, category="send", action="send", actor=approver,
                       summary=f"Client alert to the Chief AI Compliance Officer ({', '.join(rule.client_groups)} has no members): {subject_of(db, s)}"[:500])
    now = utcnow()
    s.status, s.sent_at, s.recipient_count = "sent", now, len(emails)
    s.approved_by, s.approved_at = (approver_id, now) if approver_id else (None, None)
    s.sent_from = sender_label(db, s.organization_id)
    same_day = rule.last_sent_at is not None and rule.last_sent_at.date() == now.date()
    rule.last_sent_count = (rule.last_sent_count or 0) + 1 if same_day else 1
    rule.last_sent_at = now
    audit.record(db, actor_id=approver_id, action="client_alert.sent", object_type="AlertSend", object_id=s.id, organization_id=s.organization_id, summary=f"Client alert sent: {subject_of(db, s)}")
    db.flush()
    return s
