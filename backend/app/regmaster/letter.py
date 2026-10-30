"""Intro letter (spec §25.5): generated from the applicability result, edited and approved by the Chief Auditor,
sent to the client's Chief AI Compliance Officer as a PDF and on the platform, and attached to the initiation package.

Workflow: draft -> approved -> sent. A later draft supersedes the last sent letter and lists only what changed."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.clock import today, utcnow
from app.core.config import Settings
from app.core.errors import Conflict, Invalid
from app.documents.pdf import to_pdf
from app.documents.render import render_markdown
from app.engagements.models import ClientContact, Engagement
from app.files.service import upload
from app.laws.models import Regulation
from app.reference.models import Jurisdiction
from app.regmaster import engine
from app.regmaster.models import ChangeImpact, IntroLetter, LawVersion, ProposedChange, Requirement
from app.tenancy.models import Organization, User

STATUS_LABELS = {
    "in_force": "In force", "in_force_phased": "In force, phased", "enacted_not_in_force": "Enacted, not yet in force", "phased": "Phased",
    "delayed": "Delayed or under amendment", "guidance": "Guidance", "repealed": "Repealed or lapsed", "pending": "Pending bill",
}
STAGE_LABELS = {"program_setup": "Now", "procurement": "Before purchase", "development": "Now", "go_live": "Before go-live", "ongoing": "Ongoing", "yearly": "Every year"}
AI_TYPE_SECTIONS = [
    ("agent", "AI agents"),
    ("decision", "AI or ML software deciding about people"),
    ("embedded", "Embedded AI features"),
    ("genai", "Generative AI tools and chatbots"),
    ("all", "Every AI system"),
]
FOOTER = "General information, not legal advice. Confirm obligations with your counsel."


def letters(db: Session, org_id: str) -> list[IntroLetter]:
    return list(db.scalars(select(IntroLetter).where(IntroLetter.organization_id == org_id, IntroLetter.deleted_at.is_(None)).order_by(IntroLetter.version_no.desc())))


def last_sent(db: Session, org_id: str) -> IntroLetter | None:
    return next((x for x in letters(db, org_id) if x.status == "sent"), None)


def caico_contact(db: Session, org_id: str) -> ClientContact | None:
    return db.scalar(select(ClientContact).where(ClientContact.organization_id == org_id, ClientContact.contact_role == "caico", ClientContact.deleted_at.is_(None), ClientContact.not_appointed.is_(False)).order_by(ClientContact.created_at.desc()).limit(1))


def _list(names: list[str]) -> str:
    names = list(dict.fromkeys(n for n in names if n))
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _first_sentence(text: str | None, limit: int = 180) -> str | None:
    if not text:
        return None
    s = " ".join(text.split())
    cut = s.find(". ")
    s = s[: cut + 1] if 0 < cut < limit else s
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def build_body(db: Session, org: Organization) -> dict:
    """The letter's content as structured data, from the current applicability result."""
    contact = caico_contact(db, org.id)
    geos = [db.get(Jurisdiction, g.jurisdiction_id) for g in engine.geographies(db, org.id)]
    pairs = engine.in_scope_versions(db, org.id)
    laws = []
    for reg, v in sorted(pairs, key=lambda p: (p[0].binding is False, engine.law_label(p[0]))):
        j = db.get(Jurisdiction, reg.jurisdiction_id)
        laws.append({"regulation_id": reg.id, "law_version_id": v.id, "version_no": v.version_no, "geography": j.name if j else "", "law": engine.law_label(reg),
                     "status": STATUS_LABELS.get(v.status, v.status), "binding": reg.binding is not False, "main_duty": v.main_duty or _first_sentence(reg.obligations_text) or "—"})
    roles = []
    for r in engine.required_roles(db, org.id):
        req_by = [s["law"] for s in r["sources"] if s["level"] == "required"] or [s["law"] for s in r["sources"]]
        roles.append({"code": r["code"], "name": r["name"], "level": r["level"], "level_kind": r["level_kind"], "responsibility": r["description"] or "",
                      "required_by": " · ".join(dict.fromkeys(req_by)), "needed_by": STAGE_LABELS.get(r["needed_by"], r["needed_by"])})
    rules: dict[str, list[str]] = {k: [] for k, _ in AI_TYPE_SECTIONS}
    for reg, v in pairs:
        for q in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id).order_by(Requirement.order)):
            line = f"{q.text} ({engine.law_label(reg)}{', ' + q.citation if q.citation else ''})"
            for t in q.ai_types or ["all"]:
                if t in rules and line not in rules[t]:
                    rules[t].append(line)
    return {
        "date": today().isoformat(),
        "organization": org.trading_name or org.name,
        "to": {"name": contact.name if contact else None, "title": contact.title if contact else "Chief AI Compliance Officer"},
        "geographies": [g.name for g in geos if g],
        "laws": laws,
        "committees": engine.committees(db, org.id),
        "roles": roles,
        "rules": [{"type": k, "title": t, "items": rules[k]} for k, t in AI_TYPE_SECTIONS if rules[k]],
        "versions": [f"{x['law']} v{x['version_no']}" for x in laws],
    }


def _cell(text) -> str:
    return str(text or "").replace("|", "/").replace("\n", " ")


def to_markdown(letter: IntroLetter) -> str:
    b = letter.body
    edits = letter.edited_text or {}
    to = b["to"]
    out = [f"**Futran Solutions** · Edison, New Jersey · {b['date']}", "",
           f"To: {to['name'] or '[Name]'}, {to['title'] or 'Chief AI Compliance Officer'}, {b['organization']}", "",
           "# AI governance requirements for your operations", ""]
    where = _list(b["geographies"]) or "the geographies recorded for you"
    opening = edits.get("opening") or (f"{b['organization']} uses AI in {where}. This letter sets out the laws that apply, the committee to form, "
                                        "the roles to fill, and the rules for each type of AI you use. Your AI system register on the Futran platform has been set up to match.")
    out += [opening, ""]
    if letter.changes:
        out += [f"## What changed since letter v{letter.version_no - 1}", ""]
        out += [f"- {c['text']}" for c in letter.changes] + [""]
    out += ["## 1. Laws that apply", "", "| Geography | Law | Status | Main duty |", "|---|---|---|---|"]
    out += [f"| {_cell(x['geography'])} | {_cell(x['law'])} | {_cell(x['status'])} | {_cell(x['main_duty'])} |" for x in b["laws"]] or ["| — | No laws in scope yet | — | — |"]
    out += ["", "## 2. Committee to form", ""]
    if not b["committees"]:
        out += ["No committee or program is required by the laws in scope.", ""]
    for c in b["committees"]:
        basis = "; ".join(f"{s['law']}{': ' + s['basis'] if s.get('basis') else ''}" for s in c["sources"])
        legal = "Required" if c["level"] == "required" else "Not legally required in your geographies, but recommended"
        out += [f"**{c['title'] or c['committee_type']}** — {legal} ({basis}).", ""]
        if c.get("condition_text"):
            out += [f"{c['condition_text']}.", ""]
        out += [f"- {i}" for i in c["items"]] + [""]
    req = [r for r in b["roles"] if r["level"] == "required"]
    rec = [r for r in b["roles"] if r["level"] != "required"]
    out += [f"## 3. Roles and responsibilities ({len(b['roles'])})", "", "| Role | Responsibility | Required by | Needed by |", "|---|---|---|---|"]
    out += [f"| {_cell(r['name'])}{' (per system)' if r['level_kind'] == 'system' else ' (per agent)' if r['level_kind'] == 'agent' else ''} | {_cell(r['responsibility'])} | {_cell(r['required_by'])} | {_cell(r['needed_by'])} |" for r in req]
    out += [f"| {_cell(r['name'])} (recommended) | {_cell(r['responsibility'])} | {_cell(r['required_by'])} | {_cell(r['needed_by'])} |" for r in rec]
    out += ["", "The full list, with a space for the person you name to each role, is in Appendix A.", "", "## 4. Rules for each type of AI you use", ""]
    for sec in b["rules"]:
        out += [f"**{sec['title']}**", ""] + [f"- {i}" for i in sec["items"]] + [""]
    out += ["## 5. How we keep this current", "",
            "Futran reviews these laws every two weeks. When an approved change affects you, you get an alert on the platform and an updated letter. "
            f"Rule versions used in this letter: {', '.join(b['versions']) or 'none'}.", ""]
    if edits.get("closing"):
        out += [edits["closing"], ""]
    out += ["<!-- pagebreak -->", "", "## Appendix A. Roles and the person named to each", "", "| Role | Level | Needed by | Person named |", "|---|---|---|---|"]
    out += [f"| {_cell(r['name'])} | {'Required' if r['level'] == 'required' else 'Recommended'} | {_cell(r['needed_by'])} | |" for r in b["roles"]]
    out += ["", f"*{FOOTER}*"]
    return "\n".join(out)


def to_html(letter: IntroLetter) -> str:
    return render_markdown(to_markdown(letter))


def changes_since(db: Session, org_id: str) -> dict | None:
    """Approved changes to in-scope laws since the last sent letter, plus pending ones that touch this client."""
    sent = last_sent(db, org_id)
    if sent is None:
        return None
    from app.laws.publish import current_version_of

    used = {}
    for vid in sent.law_versions_used or []:
        v = db.get(LawVersion, vid)
        live = current_version_of(db, v.regulation_id) if v is not None else None
        if live is not None:
            used[live.id] = v  # the letter used an earlier row of the law: compare with the live row
    items = []
    now_pairs = engine.in_scope_versions(db, org_id)
    current = {reg.id: (reg, v) for reg, v in now_pairs}
    for reg_id, (reg, v) in current.items():
        old = used.get(reg_id)
        if old is None:
            items.append({"regulation_id": reg_id, "text": f"{engine.law_label(reg)}: now applies to you", "pending": False})
        elif old.id != v.id:
            items.append({"regulation_id": reg_id, "text": f"{engine.law_label(reg)}: {v.change_summary or 'updated'} (v{old.version_no} to v{v.version_no})", "pending": False})
    for reg_id, old in used.items():
        if reg_id not in current:
            reg = db.get(Regulation, reg_id)
            items.append({"regulation_id": reg_id, "text": f"{engine.law_label(reg)}: no longer applies to you", "pending": False})
    pending = db.execute(select(ProposedChange, ChangeImpact).join(ChangeImpact, ChangeImpact.proposed_change_id == ProposedChange.id)
                         .where(ChangeImpact.organization_id == org_id, ProposedChange.status.in_(("pending", "held", "legal_review")))).all()
    for pc, _imp in pending:
        reg = current_version_of(db, pc.regulation_id) if pc.regulation_id else None
        items.append({"regulation_id": reg.id if reg else pc.regulation_id, "text": f"{engine.law_label(reg) if reg else 'New law'}: {pc.summary} [pending approval]", "pending": True})
    return {"letter_id": sent.id, "version_no": sent.version_no, "sent_at": sent.sent_at.isoformat() if sent.sent_at else None,
            "approved_count": sum(not i["pending"] for i in items), "items": items}


def draft(db: Session, org: Organization, actor: User) -> IntroLetter:
    """Create the next draft, or refresh the open draft from the current applicability result."""
    engine.run(db, org.id, actor.id)
    existing = letters(db, org.id)
    open_draft = next((x for x in existing if x.status == "draft"), None)
    sent = last_sent(db, org.id)
    body = build_body(db, org)
    changes = [c for c in (changes_since(db, org.id) or {}).get("items", []) if not c["pending"]] if sent else None
    if open_draft is None:
        open_draft = IntroLetter(organization_id=org.id, version_no=(existing[0].version_no + 1) if existing else 1, status="draft", body=body,
                                 supersedes_id=sent.id if sent else None, created_by=actor.id)
        db.add(open_draft)
    open_draft.body, open_draft.changes = body, changes
    open_draft.law_versions_used = [x["law_version_id"] for x in body["laws"]]
    open_draft.engagement_id = _engagement(db, org.id).id if _engagement(db, org.id) else None
    open_draft.updated_by = actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="intro_letter.draft", obj=open_draft, summary=f"Drafted intro letter v{open_draft.version_no}")
    return open_draft


def edit(db: Session, letter: IntroLetter, actor: User, opening: str | None, closing: str | None) -> IntroLetter:
    if letter.status != "draft":
        raise Conflict("Only a draft letter can be edited. Draft a new version to change a sent letter.")
    edits = dict(letter.edited_text or {})
    for k, v in (("opening", opening), ("closing", closing)):
        if v is not None:
            v = v.strip()
            if len(v) > 4000:
                raise Invalid(errors=[{"field": k, "message": "Keep this under 4,000 characters."}])
            if v:
                edits[k] = v
            else:
                edits.pop(k, None)
    letter.edited_text, letter.updated_by = edits, actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="intro_letter.edit", obj=letter, after=edits, summary=f"Edited intro letter v{letter.version_no}")
    return letter


def _engagement(db: Session, org_id: str) -> Engagement | None:
    return db.scalar(select(Engagement).where(Engagement.client_id == org_id, Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc()).limit(1))


def _title(letter: IntroLetter) -> str:
    return f"AI governance requirements (intro letter v{letter.version_no})"


def render_pdf(db: Session, settings: Settings, letter: IntroLetter, actor: User | None) -> str:
    org = db.get(Organization, letter.organization_id)
    data = to_pdf(to_markdown(letter), _title(letter), {"audit_ref": org.client_ref or ""})
    f = upload(db, settings, actor, data=data, filename=f"{org.client_ref or org.name} intro letter v{letter.version_no}.pdf".replace("/", "-"), content_type="application/pdf",
               organization_id=org.id, engagement_id=letter.engagement_id, linked_type="intro_letter", linked_id=letter.id)
    letter.file_id = f.id
    return f.id


def approve(db: Session, settings: Settings, letter: IntroLetter, actor: User) -> IntroLetter:
    if letter.status != "draft":
        raise Conflict("This letter has already been approved.")
    if not letter.body.get("laws"):
        raise Conflict("No laws are in scope for this client yet. Add the client's geographies first.")
    letter.status, letter.approved_by, letter.approved_at, letter.updated_by = "approved", actor.id, utcnow(), actor.id
    render_pdf(db, settings, letter, actor)
    attach_to_package(db, settings, actor, letter)
    db.flush()
    audit.record(db, actor_id=actor.id, action="intro_letter.approve", obj=letter, summary=f"Approved intro letter v{letter.version_no}")
    return letter


def send(db: Session, settings: Settings, letter: IntroLetter, actor: User) -> IntroLetter:
    from app.mail import service as mail
    from app.notifications.service import notify

    if letter.status != "approved":
        raise Conflict("Approve the letter before sending it.")
    org = db.get(Organization, letter.organization_id)
    contact = caico_contact(db, org.id)
    if contact is None or not contact.email:
        raise Conflict("Add the client's Chief AI Compliance Officer (client set-up, step 4) before sending the letter.")
    paragraphs = [
        f"Dear {contact.name},",
        f"Futran has set out the AI governance requirements that apply to {org.trading_name or org.name}: the laws in scope, the committee to form, the roles to fill and the rules for each type of AI you use. The letter is attached on the platform as a PDF.",
        "[Link]",
        FOOTER,
    ]
    mail.send(db, settings, "client_alert", to=[contact.email], context={"subject": f"AI governance requirements for {org.trading_name or org.name} (letter v{letter.version_no})", "paragraphs": paragraphs,
              "link": f"{settings.base_url}/start", "button": "Open the letter"}, organization_id=org.id, related=letter, actor_id=actor.id)
    if contact.user_id:
        u = db.get(User, contact.user_id)
        if u is not None:
            notify(db, [u], "intro_letter", f"Intro letter v{letter.version_no} from Futran", "The AI governance requirements for your operations.", "/start")
    letter.status, letter.sent_at, letter.sent_by, letter.updated_by = "sent", utcnow(), actor.id, actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="intro_letter.send", obj=letter, summary=f"Sent intro letter v{letter.version_no} to {contact.email}")
    return letter


INTRO_ITEM = 8


def attach_to_package(db: Session, settings: Settings, actor: User | None, letter: IntroLetter, pkg=None) -> None:
    """Put the approved letter in the client's initiation package (§25.8: step 5 attaches the intro letter)."""
    from app.initiation.models import PackageDocument
    from app.initiation.service import current_package

    e = db.get(Engagement, letter.engagement_id) if letter.engagement_id else _engagement(db, letter.organization_id)
    if e is None:
        return
    pkg = pkg or current_package(db, e)
    if pkg is None:
        return
    for old in db.scalars(select(PackageDocument).where(PackageDocument.package_id == pkg.id, PackageDocument.template_key == "intro_letter", PackageDocument.deleted_at.is_(None))):
        old.deleted_at = utcnow()
    db.add(PackageDocument(organization_id=e.client_id, package_id=pkg.id, engagement_id=e.id, item=INTRO_ITEM, template_key="intro_letter", template_version=letter.version_no,
                           title=_title(letter), format="md", requires_action="read", body_md=to_markdown(letter), pdf_file_id=letter.file_id, created_by=actor.id if actor else None))
    db.flush()


def latest_approved(db: Session, org_id: str) -> IntroLetter | None:
    return next((x for x in letters(db, org_id) if x.status in ("approved", "sent")), None)
