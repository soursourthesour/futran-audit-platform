"""Starter data for platform trust (spec §21 F19), loaded idempotently at start-up and by the demo.

- A short SOC 2 starter list: one or two controls per area of the AICPA trust services criteria, worded for this
  platform. The Futran Admin assigns owners, records evidence and adds controls.
- The platform's own AI features as register systems in Futran's own organization (§21 rule 5: Futran governs its own AI
  and audits it with the same template). A row is added only when missing (matched on its dedupe key); edits are kept.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platformtrust.models import SocControl
from app.register.models import RegisterSystem
from app.tenancy.models import Organization

STARTER: list[tuple[str, str, str, str]] = [
    ("CC1.1", "security", "Code of conduct", "Everyone at Futran signs the code of conduct when they join and again each year."),
    ("CC1.4", "security", "Background checks and security training", "Staff with access to client data pass a background check and complete security awareness training each year."),
    ("CC2.2", "security", "Information security policy", "The information security policy is approved by management, published to staff and reviewed each year."),
    ("CC3.2", "security", "Risk assessment", "A yearly risk assessment of the platform covers security, fraud and AI-specific risks, with owners for each treatment."),
    ("CC4.1", "security", "Independent penetration test", "An external penetration test of the platform and the public API each year; findings tracked to closure."),
    ("CC6.1", "security", "Access control and tenant isolation", "Sign-in with MFA, role-based permissions, and every query scoped to the signed-in user's organization."),
    ("CC6.2", "security", "Joiners, movers and leavers", "Access is granted on approval and removed on the day a person leaves; access is reviewed each quarter."),
    ("CC6.6", "security", "Protection at the boundary", "TLS 1.2 or later, rate limits on public endpoints, and webhooks that never call private network addresses."),
    ("CC6.7", "security", "Encryption of data and secrets", "Data encrypted in transit and at rest; mailbox tokens and webhook secrets encrypted; API secrets stored only as hashes."),
    ("CC6.8", "security", "Malicious file protection", "Uploaded files are checked before staff open them."),
    ("CC7.2", "security", "Logging and monitoring", "An append-only audit log of every change and API call, with alerts on failures."),
    ("CC7.4", "security", "Incident response", "A written incident response plan, tested each year, including client and regulator notification."),
    ("CC8.1", "security", "Change management", "Every change is reviewed, tested and approved before release; database changes only add, never remove, client data."),
    ("CC9.2", "security", "Vendor and subprocessor management", "Hosting, email and AI providers (including Anthropic) are reviewed each year against their SOC 2 reports and contracts."),
    ("A1.2", "availability", "Backups", "Daily backups of the database and stored files, kept encrypted in a separate location."),
    ("A1.3", "availability", "Recovery testing", "A restore from backup is tested each year and the recovery time recorded."),
    ("C1.1", "confidentiality", "Confidential information identified", "Client documents and evidence are classified confidential and seen only by the client and the assigned audit team."),
    ("C1.2", "confidentiality", "Disposal at end of retention", "Client data is deleted at the end of the agreed retention period and the deletion recorded."),
    ("PI1.3", "processing_integrity", "AI output reviewed by a person", "AI suggestions cite their source and reach a client only after a named Futran user accepts them."),
    ("PI1.2", "processing_integrity", "Input validation", "Imports and API calls are validated in full; nothing is saved while any row has an error."),
    ("P1.1", "privacy", "Privacy notice", "Clients' employees receive a notice about the personal data the platform holds before they use it."),
    ("P4.2", "privacy", "Retention of personal data", "Personal data is kept only as long as the engagement retention period and then deleted."),
]

PLATFORM_AI: list[dict] = [
    {"code": "refresh", "name": "Law refresh with Claude (M3)", "stage": "live",
     "purpose": "Searches official sources for changes to AI laws and proposes updates to the law library. A Futran reviewer approves every change."},
    {"code": "draft", "name": "Draft with Claude for law records (M1b)", "stage": "live",
     "purpose": "Reads the official text of a bill and fills the add-a-law form. Nothing is saved until a person checks every field and the Chief Auditor approves."},
    {"code": "copilot", "name": "AI audit copilot (F1)", "stage": "in_development",
     "purpose": "Suggests answers, evidence checks and draft findings from the engagement's documents, with citations. Every suggestion needs a named auditor's acceptance."},
    {"code": "questionnaire", "name": "Security questionnaire answers (F10)", "stage": "in_development",
     "purpose": "Drafts answers to clients' customer questionnaires from their own answer library and signed reports. The client's reviewer accepts each answer."},
    {"code": "obligation", "name": "Obligation extraction from laws (F5)", "stage": "in_development",
     "purpose": "Proposes obligations (actor, action, deadline, citation) from stored law text. The Legal Reviewer or Chief Auditor approves each one."},
]
DEDUPE = "futran-platform|"


def futran_org(db: Session) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.type == "futran", Organization.is_internal.is_(False), Organization.deleted_at.is_(None)))


def seed_controls(db: Session) -> int:
    org = futran_org(db)
    if org is None:
        return 0
    have = set(db.scalars(select(SocControl.code).where(SocControl.organization_id == org.id)))
    n = 0
    for i, (code, crit, title, desc) in enumerate(STARTER):
        if code in have:
            continue
        db.add(SocControl(organization_id=org.id, code=code, criterion=crit, title=title, description=desc, status="not_started", review_months=12, order=i + 1))
        n += 1
    db.flush()
    return n


def seed_platform_ai(db: Session, settings=None) -> int:
    from app.register.service import apply_tier, log_change, next_reference

    org = futran_org(db)
    if org is None:
        return 0
    have = set(db.scalars(select(RegisterSystem.dedupe_key).where(RegisterSystem.organization_id == org.id, RegisterSystem.dedupe_key.like(f"{DEDUPE}%"))))
    model = getattr(settings, "claude_model", None) or "Claude"
    n = 0
    for f in PLATFORM_AI:
        key = DEDUPE + f["code"]
        if key in have:
            continue
        stage = f["stage"]  # features still being built start in development; the Futran Admin moves them on
        s = RegisterSystem(organization_id=org.id, reference=next_reference(db, org.id), name=f["name"], type="embedded_feature", sourcing="in_house", stage=stage,
                           purpose=f["purpose"], users_scope="role", users_description="Futran auditors, reviewers and the clients they work with", ai_provider="anthropic",
                           model_name=model, algorithm_type=None, hosting=None, decision_impact="informs", company_wide=True, origin="manual", dedupe_key=key,
                           vendor_documents=[], source_refs=[], history_answers={})
        db.add(s)
        db.flush()
        apply_tier(db, s)
        log_change(db, None, s, "created", None, f"{s.reference} {s.name}", "Registered at start-up: the platform's own AI feature (spec §21 F19).", raw=True)
        n += 1
    db.flush()
    return n


def counts(db: Session, org_id: str) -> dict:
    rows = dict(db.execute(select(SocControl.status, func.count()).where(SocControl.organization_id == org_id, SocControl.deleted_at.is_(None)).group_by(SocControl.status)).all())
    return rows
