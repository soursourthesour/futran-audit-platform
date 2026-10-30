"""Demo data for the v0.4–v0.6.1 screens: the regulatory master, the AI system register, email and groups, the law
refresh, client alerts, opportunities, tracing and the role homes (spec §13.1, §24–§27).

Called only from `seed_demo.run` (demo.bat). Everything goes through the platform's API as the person who would do it,
so gates, the change log and the audit log apply. The few direct writes are marked "no service" where they appear.
Nothing touches the network: the law refresh uses an in-process client with fixed replies, and email stays in the
outbox (or SMTP, if the laptop is set up for it) with no mailbox connected.

ABC Corp's register (AIS-001 to AIS-010) is built in two steps. `abc_register_core` runs during the audit, before
fieldwork, so the auditor can link SYS-001 to SYS-004 to the client's register rows. `abc_after_audit` runs once the
engagement is completed and records what ABC did next: the independent bias audit, the Pune sourcing centre (India comes
into scope), the recruiting agent with the tracing add-on, and the systems still in the pipeline.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.demo.seed_demo import ABC, Demo, DemoError

LEGAL = ("Jordan Ellis", "legal@futran.demo", "legal_reviewer", "Legal and Compliance Reviewer")
BIAS_AUDITOR = "Halden Analytics LLC"
BIAS_AUDITOR_CONTACT = "audits@haldenanalytics.example"


# ---------------------------------------------------------------- small helpers
def legal_reviewer(m: Demo) -> None:
    """A Futran Legal/Compliance Reviewer, so every Futran role has a demo sign-in."""
    from app.auth.passwords import hash_password
    from app.cli import _futran_org
    from app.demo.seed_demo import DEMO_PASSWORD
    from app.tenancy.models import User
    from app.tenancy.service import assign_role, create_user

    name, email, role, title = LEGAL
    u = m.db.scalar(select(User).where(User.email == email)) or create_user(m.db, _futran_org(m.db), name=name, email=email, job_title=title)
    u.password_hash, u.status, u.mfa_enabled = hash_password(DEMO_PASSWORD), "active", False
    assign_role(m.db, u, role)
    m.db.commit()


def _law(m: Demo, prefix: str) -> str:
    from app.laws.publish import current_regulations

    hits = [r for r in current_regulations(m.db) if (r.short_name or "").startswith(prefix)]
    if not hits:
        raise DemoError(f"No law starting {prefix!r} in the library")
    return hits[0].id


def _depts(m: Demo, cid: str) -> dict[str, str]:
    from app.tenancy.models import Department

    return {d.name: d.id for d in m.db.scalars(select(Department).where(Department.organization_id == cid, Department.deleted_at.is_(None)))}


def _ago(m: Demo, days: int, hour: int = 10, minute: int = 0) -> str:
    return datetime.combine(m.today - timedelta(days=days), datetime.min.time()).replace(hour=hour, minute=minute).isoformat()


def _upload(m: Demo, path: str, filename: str, data: bytes, content_type: str) -> dict:
    r = m.c.post(f"/api/v1{path}", files={"file": (filename, data, content_type)})
    if r.status_code != 200:
        raise DemoError(f"POST {path} → {r.status_code}: {r.text[:800]}")
    m.db.expire_all()
    return r.json()


def _role_body(m: Demo, spec, row: dict) -> dict:
    """spec: an email (assigned), ("external", party, contact), ("none", reason) or ("pending", days, reason)."""
    if isinstance(spec, str):
        body = {"status": "assigned", "user_id": m.user(spec).id, "effective_from": m.d(-30)}
        if row.get("extra_checks") == "oversight_confirmations":
            body |= {"training_completed": True, "has_authority_to_override": True}
        return body
    kind = spec[0]
    if kind == "external":
        return {"status": "external", "external_party": spec[1], "external_contact": spec[2]}
    if kind == "none":
        return {"status": "no_such_person", "reason": spec[1]}
    if kind == "pending":
        return {"status": "pending_committee", "target_date": m.d(spec[1]), "reason": spec[2]}
    raise DemoError(f"Unknown role spec {spec!r}")


def fill_roles(m: Demo, sid: str, people: dict) -> None:
    for row in m.get(f"/register/{sid}/roles")["rows"]:
        spec = people.get(row["code"])
        if spec is None or row["level"] == "company":
            continue
        m.put(f"/register/{sid}/roles/{row['role_id']}", _role_body(m, spec, row))


def set_requirements(m: Demo, sid: str, statuses: dict, entries: dict | None = None) -> None:
    """statuses: requirement code -> (status, note). entries: code -> history entry ids that prove it."""
    for row in m.get(f"/register/{sid}/requirements")["rows"]:
        if row["code"] not in statuses:
            continue
        status, note = statuses[row["code"]]
        body = {"status": status, "note": note}
        if entries and row["code"] in entries:
            body["history_entry_ids"] = entries[row["code"]]
        m.put(f"/register/{sid}/requirements/{row['id']}", body)


def go_live(m: Demo, sid: str, submitter: str, approver: str, comment: str) -> None:
    m.as_(m.user(submitter)).post(f"/register/{sid}/go-live/submit")
    m.as_(m.user(approver)).post(f"/register/{sid}/go-live/decide", {"approve": True, "comment": comment})


def _backdate_live(m: Demo, sid: str, since: str) -> None:
    """No service: go-live approval records today's date. These systems were in use before ABC started its register, so
    the date they went into use is kept, as the client would tell its auditor. The approval itself stays as recorded."""
    from datetime import date

    from app.register.models import RegisterSystem

    s = m.db.get(RegisterSystem, sid)
    s.live_since = date.fromisoformat(since)
    m.db.commit()


# ---------------------------------------------------------------- requirement notes (what a client records)
NIST_MET = {
    "NIST-GV2.1": ("met", "Roles and reporting lines are set out in the AI Governance Committee charter and recorded in this register."),
    "NIST-GV2.3": ("met", "The Chief Operating Officer is the accountable executive and approves Tier 3 systems."),
    "NIST-GV3.1": ("met", "Approved by the AI Governance Committee, which has HR, IT, privacy and business members."),
    "NIST-GV6.1": ("met", "Vendor AI terms, data use and audit rights were checked during procurement by the vendor AI risk owner."),
    "NIST-MG4.3": ("met", "Incidents go to the AI Incident Response Lead and are logged in this system's history."),
}
IL_MET = {
    "IL-02": ("met", "Zip code is not an input. Confirmed against the model documentation."),
    "IL-03": ("met", "AI use notice added to the Illinois employee handbook and the careers site."),
}
LL144_NOTICES = {
    "LL144-03": ("met", "Notice on the careers site and in the application acknowledgement email, at least 10 business days before use, with how to ask for an alternative process."),
    "LL144-04": ("met", "The notice lists the qualifications and characteristics the tool assesses for each job family."),
    "LL144-05": ("met", "The data collected and its sources are described on the careers site privacy page."),
}


# ---------------------------------------------------------------- ABC Corp: company roles and committee (during the audit)
def _company_roles(m: Demo, cid: str, extra: dict | None = None) -> None:
    roles = {
        "accountable_executive": f"robert.chen@{ABC}", "ai_compliance_officer": f"maria.lopez@{ABC}", "dpo": f"daniel.kim@{ABC}",
        "incident_response_lead": f"sam.okafor@{ABC}", "vendor_ai_risk_owner": f"grace.liu@{ABC}", "records_retention_owner": f"daniel.kim@{ABC}",
        "ai_governance_committee": f"maria.lopez@{ABC}",
    } | (extra or {})
    m.as_(m.user(f"maria.lopez@{ABC}"))
    rows = {r["code"]: r for r in m.get("/governance/company-roles")["rows"]}
    for code, spec in roles.items():
        if code in rows:
            m.put(f"/governance/company-roles/{rows[code]['role_id']}", _role_body(m, spec, rows[code]))


def _committee(m: Demo) -> None:
    m.as_(m.user(f"maria.lopez@{ABC}"))
    roles = {r["code"]: r["role_id"] for r in m.get("/governance/company-roles")["rows"]}
    for email, role, covers in ((f"maria.lopez@{ABC}", "chair", "ai_compliance_officer"), (f"robert.chen@{ABC}", "business", "accountable_executive"),
                                (f"daniel.kim@{ABC}", "legal", "dpo"), (f"sam.okafor@{ABC}", "technical", "incident_response_lead"),
                                (f"priya.shah@{ABC}", "secretary", None)):
        m.post("/governance/committee/members", {"user_id": m.user(email).id, "committee_role": role, "covers_role_id": roles.get(covers) if covers else None})
    m.post("/governance/committee/formed", {"formed_on": m.d(-240), "meeting_cadence": "monthly", "approval_scope": "tier3_and_exceptions",
                                            "charter_note": "AI Governance Committee charter v1.0, approved by the Chief Operating Officer"})


# ---------------------------------------------------------------- ABC Corp: the four audited systems (before fieldwork)
def abc_register_core(m: Demo, cid: str, depts: dict) -> dict:
    """The register as ABC kept it during the audit. Returns the register id for each fieldwork system reference."""
    maria = f"maria.lopez@{ABC}"
    _company_roles(m, cid)
    _committee(m)
    nist, ll144, il = _law(m, "NIST AI Risk"), _law(m, "NYC Local Law 144"), _law(m, "HB 3773")
    m.as_(m.user(maria))
    ats = m.post("/register", {
        "name": "ATS résumé screening (ScreenRank)", "type": "vendor_app", "sourcing": "vendor", "department_id": depts["HR"], "stage": "ready_for_go_live",
        "purpose": "Ranks applicants for New York and Chicago roles before a recruiter reviews them.", "users_scope": "role",
        "users_description": "Recruiters for New York and Chicago roles", "user_count": 6, "owner_user_id": m.user(f"lee.park@{ABC}").id,
        "vendor_name": "ScreenRank Inc.", "ai_provider": "unknown", "model_name": "ScreenRank Match", "algorithm_type": "ranking", "hosting": "vendor_cloud_us",
        "vendor_trains_on_data": "no", "vendor_documents": ["contract_ai_terms", "dpa", "vendor_bias_audit", "security_report"], "decision_impact": "consequential",
        "bias_next_due": m.d(-200),
        "data": {"data_categories": ["personal", "sensitive"], "data_subjects": ["candidates"], "consent_basis": "notice_only", "consent_ref": "Candidate privacy notice v3",
                 "retention_period": "4 years after the hiring decision", "cross_border": "no"},
        "regulation_ids": [ll144, il, nist]})
    invoice = m.post("/register", {
        "name": "Invoice anomaly detection", "type": "in_house_model", "sourcing": "in_house", "department_id": depts["Finance"], "stage": "in_development",
        "purpose": "Flags unusual supplier invoices for review before payment. Built and validated by the Finance analytics team.", "users_scope": "role",
        "users_description": "Accounts payable clerks", "user_count": 5, "owner_user_id": m.user(f"grace.liu@{ABC}").id, "ai_provider": "in_house",
        "model_name": "AP anomaly model", "model_version": "2.3", "algorithm_type": "classifier", "hosting": "our_cloud", "decision_impact": "none",
        "data": {"data_categories": ["confidential"], "data_subjects": ["none"], "consent_basis": "na", "retention_period": "7 years (financial records)", "cross_border": "no"},
        "regulation_ids": [nist]})
    copilot = m.post("/register", {
        "name": "Sales proposal assistant (Microsoft 365 Copilot)", "type": "embedded_feature", "sourcing": "vendor", "department_id": depts["Sales & Marketing"],
        "stage": "in_development", "purpose": "Drafts client proposals from CRM notes. Also used across the company to summarise meetings.", "users_scope": "role",
        "users_description": "Account executives; meeting summaries company-wide", "user_count": 12, "owner_user_id": m.user(f"owen.hart@{ABC}").id,
        "vendor_name": "Microsoft Corporation", "ai_provider": "azure_openai", "model_name": "Microsoft 365 Copilot", "algorithm_type": "llm", "hosting": "our_cloud",
        "vendor_trains_on_data": "no", "vendor_documents": ["contract_ai_terms", "dpa", "security_report"], "decision_impact": "none",
        "data": {"data_categories": ["confidential"], "data_subjects": ["customers"], "consent_basis": "other_lawful_basis", "consent_ref": "Client master services agreement, confidentiality clause",
                 "retention_period": "As the source documents", "cross_border": "no"},
        "regulation_ids": [nist]})
    chatbot = m.post("/register", {
        "name": "Customer support chatbot (Zendesk Answer Bot)", "type": "vendor_app", "sourcing": "vendor", "department_id": depts["Sales & Marketing"], "stage": "in_development",
        "purpose": "Answers customer questions on the website and hands complex requests to a support agent.", "users_scope": "role",
        "users_description": "Website visitors; support agents take over hand-offs", "user_count": 8, "owner_user_id": m.user(f"owen.hart@{ABC}").id,
        "vendor_name": "Zendesk, Inc.", "ai_provider": "unknown", "model_name": "Answer Bot", "algorithm_type": "llm", "hosting": "vendor_cloud_us",
        "vendor_trains_on_data": "unknown", "vendor_documents": ["contract_ai_terms", "dpa"], "decision_impact": "informs",
        "data": {"data_categories": ["personal"], "data_subjects": ["customers", "public"], "consent_basis": "notice_only", "consent_ref": "Website privacy notice, chat banner",
                 "retention_period": "2 years", "cross_border": "no"},
        "regulation_ids": [nist]})
    hr_people = {"ai_system_owner": f"lee.park@{ABC}", "technical_owner": f"sam.okafor@{ABC}", "human_oversight_person": f"tom.reyes@{ABC}",
                 "transparency_notice_owner": f"priya.shah@{ABC}", "data_consent_steward": f"lee.park@{ABC}",
                 "bias_testing_lead": ("none", "ABC relies on the vendor's March 2024 audit and has not appointed its own independent auditor.")}
    fill_roles(m, ats["id"], hr_people)
    set_requirements(m, ats["id"], NIST_MET | IL_MET | LL144_NOTICES | {
        "LL144-01": ("not_met", "The vendor's last independent bias audit is dated March 2024. ABC has not commissioned its own."),
        "LL144-02": ("not_met", "No summary of results is published on the careers site."),
        "IL-01": ("partly_met", "The vendor's documentation was reviewed. There is no impact analysis on ABC's Illinois applicants yet."),
        "NIST-MS2.11": ("not_met", "No bias evaluation on ABC's own applicant data."),
    })
    fill_roles(m, invoice["id"], {"ai_system_owner": f"grace.liu@{ABC}", "technical_owner": f"nina.patel@{ABC}", "human_oversight_person": f"nina.patel@{ABC}"})
    set_requirements(m, invoice["id"], NIST_MET | {"NIST-GV6.1": ("not_applicable", "Built in-house by the Finance analytics team; no third-party AI.")})
    fill_roles(m, copilot["id"], {"ai_system_owner": f"owen.hart@{ABC}", "technical_owner": f"sam.okafor@{ABC}"})
    set_requirements(m, copilot["id"], NIST_MET)
    fill_roles(m, chatbot["id"], {"ai_system_owner": f"owen.hart@{ABC}", "technical_owner": f"sam.okafor@{ABC}", "human_oversight_person": f"marco.diaz@{ABC}"})
    set_requirements(m, chatbot["id"], NIST_MET | {
        "NIST-MS2.11": ("partly_met", "Containment and hand-off rates are monitored. Answers are not yet sampled for accuracy or fair treatment."),
    })
    go_live(m, invoice["id"], f"grace.liu@{ABC}", maria, "Quarterly validation by Finance analytics is in place.")
    go_live(m, copilot["id"], f"marco.diaz@{ABC}", maria, "Company licence with data protection terms; no decisions about people.")
    go_live(m, chatbot["id"], f"marco.diaz@{ABC}", maria, "Agents take over complex requests. Answer sampling to follow.")
    _backdate_live(m, invoice["id"], "2024-07-01")
    _backdate_live(m, copilot["id"], "2025-09-15")
    _backdate_live(m, chatbot["id"], "2025-02-03")
    return {"SYS-001": ats["id"], "SYS-002": invoice["id"], "SYS-003": copilot["id"], "SYS-004": chatbot["id"]}


# ---------------------------------------------------------------- ABC Corp after the audit
def _register_ids(m: Demo, cid: str) -> dict[str, str]:
    from app.register.models import RegisterSystem

    return {s.reference: s.id for s in m.db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == cid))}


def abc_after_audit(m: Demo, cid: str) -> dict:
    """What ABC recorded once the audit closed. Returns the ids the later steps need."""
    maria, priya = f"maria.lopez@{ABC}", f"priya.shah@{ABC}"
    depts = _depts(m, cid)
    # Pune sourcing centre: a new manager, and India comes into scope (Futran records the geography, M5)
    m.as_(m.user(f"sam.okafor@{ABC}")).post(f"/clients/{cid}/users", {"first_name": "Arjun", "last_name": "Mehta", "email": f"arjun.mehta@{ABC}", "job_title": "",
                                                                     "department": "HR", "role": "contributor"})
    m.activate(cid)
    from app.demo.seed_demo import _people_titles

    _people_titles(m.db, {f"arjun.mehta@{ABC}": "Sourcing Centre Manager, Pune"})
    chief = m.user("chief@futran.demo")
    m.as_(chief).post(f"/clients/{cid}/geographies", {"jurisdiction_code": "IN-MH", "basis": "employees"})
    m.post(f"/clients/{cid}/geographies", {"jurisdiction_code": "US-NJ", "basis": "candidates"})
    m.get(f"/clients/{cid}/applicability")
    letter = m.post(f"/clients/{cid}/letters")
    m.patch(f"/clients/{cid}/letters/{letter['id']}", {"opening": "Following the audit and the opening of your Pune sourcing centre, this letter sets out the AI laws that now apply to "
                                                                  "ABC Corp, the roles each needs and the committee that oversees them."})
    m.post(f"/clients/{cid}/letters/{letter['id']}/approve")
    m.post(f"/clients/{cid}/letters/{letter['id']}/send")
    _company_roles(m, cid, {"grievance_officer_india": f"arjun.mehta@{ABC}",
                            "ai_literacy_owner": ("pending", 30, "The committee appoints the owner when it approves the AI acceptable use policy.")})
    refs = _register_ids(m, cid)
    nist, ll144, il = _law(m, "NIST AI Risk"), _law(m, "NYC Local Law 144"), _law(m, "HB 3773")
    dpdp, certin, aivia = _law(m, "Digital Personal Data Protection Act"), _law(m, "CERT-In Directions"), _law(m, "AI Video Interview Act")

    # AIS-001: ABC's own bias audit (the remediation), then go-live approval
    ats = refs["AIS-001"]
    m.as_(m.user(priya))
    vendor = m.post(f"/register/{ats}/history", {"type": "vendor_audit", "occurred_on": "2024-03-15", "summary": "Vendor's independent bias audit of ScreenRank Match received",
                                                  "result": "Covers the vendor's pooled customer data, not ABC's applicants. Kept as background evidence."})
    notice = m.post(f"/register/{ats}/history", {"type": "notice_consent", "occurred_on": m.d(-400), "summary": "Candidate notice for New York roles published on the careers site",
                                                  "details": {"audience": "Applicants for New York City roles", "channel": "Careers site and acknowledgement email", "version": "v3"}})
    fill_roles(m, ats, {"bias_testing_lead": ("external", BIAS_AUDITOR, BIAS_AUDITOR_CONTACT)})
    test = m.post(f"/register/{ats}/bias-tests", {
        "tested_on": m.d(-3), "tester_type": "independent", "tester_name": BIAS_AUDITOR, "method": "Impact ratios on selection rates (6 RCNY § 5-301), January to June applicant data",
        "groups_tested": "Sex; race/ethnicity; intersectional categories", "result": "passed", "unknown_share": 18,
        "result_text": "Lowest impact ratio 0.84 (Hispanic or Latino). 112 applicants in the unknown category, reported in the summary.",
        "summary": "Independent bias audit of ScreenRank on ABC's New York applicant data"})
    set_requirements(m, ats, {
        "LL144-01": ("met", f"Independent bias audit by {BIAS_AUDITOR} on ABC's own data."),
        "LL144-02": ("met", "Summary of results and the distribution date published on the careers site. Rankings for New York roles resume on the distribution date."),
        "IL-01": ("met", "The same impact analysis covered Illinois applicants. No category below the four-fifths guide."),
        "NIST-MS2.11": ("met", "Independent bias audit recorded in the history log; repeated every year."),
    }, entries={"LL144-01": [test["id"]], "LL144-02": [test["id"]], "IL-01": [test["id"]], "NIST-MS2.11": [test["id"]], "LL144-03": [notice["id"]]})
    go_live(m, ats, priya, maria, "Independent bias audit done and summary published. Remediation of the audit findings verified by Futran.")
    m.as_(m.user(maria)).post(f"/register/{ats}/history", {"type": "approval", "occurred_on": m.d(0), "summary": "Go-live approved by the Chief AI Compliance Officer after the bias audit",
                                                            "details": {"approver": "Maria Lopez", "scope": "New York and Chicago roles"}})

    # AIS-002: monitoring history and the system owner's no-incident statement
    inv = refs["AIS-002"]
    m.as_(m.user(f"grace.liu@{ABC}"))
    for days, summary, result in ((185, "Q1 validation: back-test against confirmed fraud cases", "Precision 0.81, recall 0.74. No change needed."),
                                  (94, "Q2 validation: back-test against confirmed fraud cases", "Precision 0.83, recall 0.76. Validation pack filed with the audit evidence."),
                                  (2, "Q3 validation: back-test against confirmed fraud cases", "Precision 0.82, recall 0.77. Threshold unchanged.")):
        m.post(f"/register/{inv}/history", {"type": "monitoring_review", "occurred_on": m.d(-days), "summary": summary, "result": result})
    m.post(f"/register/{inv}/history", {"type": "model_change", "occurred_on": m.d(-60), "summary": "Retrained on first-half invoices; new supplier categories added",
                                        "details": {"old_version": "2.2", "new_version": "2.3", "reassessment_needed": False}})
    m.post(f"/register/{inv}/history-answers", {"incidents": "no", "bias_tests": "not_applicable", "deployment_tests": "yes", "approvals": "yes", "notices": "not_applicable"})
    m.post(f"/register/{inv}/no-incident/sign", {"typed_name": "Grace Liu"})

    # AIS-003: deployment test; AIS-004: an incident and the monthly answer review the audit asked for
    m.as_(m.user(f"marco.diaz@{ABC}"))
    m.post(f"/register/{refs['AIS-003']}/history", {"type": "deployment_test", "occurred_on": "2025-09-01", "summary": "User acceptance test of proposal drafting with 5 account executives",
                                                    "details": {"kind": "user_acceptance", "sample_size": 40, "result": "Drafts needed light editing; no client data from other accounts appeared."}})
    bot = refs["AIS-004"]
    m.post(f"/register/{bot}/history", {"type": "incident", "occurred_on": m.d(-71), "severity": "low",
                                        "summary": "Chatbot quoted the old 30-day refund window after the policy changed to 14 days",
                                        "result": "Knowledge base article corrected the same day; the 37 customers affected were contacted and offered the old terms.",
                                        "details": {"people_affected": 37, "cause": "The refund article in the bot's knowledge base was not updated with the policy.",
                                                    "containment": "Article corrected and the bot's answer re-tested.", "fix": "Policy changes now include a knowledge base check.",
                                                    "closed_on": m.d(-69), "reportable": False}})
    review = m.post(f"/register/{bot}/history", {"type": "monitoring_review", "occurred_on": m.d(-5), "summary": "First monthly review of 50 sampled conversations",
                                                 "result": "47 accurate, 3 incomplete answers corrected. No sign of unfair treatment."})
    set_requirements(m, bot, {"NIST-MS2.11": ("met", "Monthly sample of 50 conversations reviewed for accuracy and fair treatment.")}, entries={"NIST-MS2.11": [review["id"]]})

    # AIS-005: personal ChatGPT accounts, retired after the audit
    m.as_(m.user(maria))
    shadow = m.post("/register", {"name": "ChatGPT (personal accounts)", "type": "genai_chat_tool", "sourcing": "shadow", "department_id": depts["HR"], "stage": "proposed",
                                  "purpose": "Recruiters drafted job adverts and outreach messages, sometimes with candidate details.", "vendor_name": "OpenAI",
                                  "ai_provider": "openai", "decision_impact": "none", "vendor_trains_on_data": "unknown",
                                  "data": {"data_categories": ["personal"], "data_subjects": ["candidates"], "consent_basis": "not_obtained"}})
    m.post(f"/register/{shadow['id']}/retire", {"reason": "Replaced by the company Copilot licence. Personal AI accounts are blocked on company devices (audit finding closed)."})

    # AIS-006: attrition model, live, with the notice owner gone: Live · finding raised
    m.as_(m.user(priya))
    attr = m.post("/register", {"name": "Employee attrition risk model", "type": "in_house_model", "sourcing": "in_house", "department_id": depts["HR"], "stage": "in_development",
                                "purpose": "Scores the risk that an employee leaves in the next six months, so HR business partners can plan retention conversations.",
                                "users_scope": "named", "users_description": "HR business partners", "user_count": 4, "owner_user_id": m.user(priya).id,
                                "ai_provider": "in_house", "model_name": "Attrition score", "model_version": "1.1", "algorithm_type": "classifier", "hosting": "our_cloud",
                                "decision_impact": "informs",
                                "data": {"data_categories": ["personal"], "data_subjects": ["employees"], "consent_basis": "notice_only", "consent_ref": "Employee privacy notice 2025",
                                         "retention_period": "Scores kept 12 months", "cross_border": "no"},
                                "regulation_ids": [il, nist]})["id"]
    fill_roles(m, attr, {"ai_system_owner": priya, "technical_owner": f"lee.park@{ABC}", "human_oversight_person": priya, "transparency_notice_owner": priya,
                         "bias_testing_lead": f"lee.park@{ABC}", "data_consent_steward": f"daniel.kim@{ABC}"})
    internal_test = m.post(f"/register/{attr}/bias-tests", {"tested_on": m.d(-120), "tester_type": "internal", "tester_name": "HR analytics", "method": "Score distribution by group",
                                                            "groups_tested": "Sex; age band; race/ethnicity", "result": "passed", "unknown_share": 6,
                                                            "result_text": "No group's average score differs by more than 4 points."})
    set_requirements(m, attr, NIST_MET | IL_MET | {
        "NIST-GV6.1": ("not_applicable", "Built in-house; no third-party AI."),
        "IL-01": ("met", "Internal bias test of scores by group recorded in the history log."),
        "NIST-MS2.11": ("met", "Internal bias test recorded; repeated every year."),
    }, entries={"IL-01": [internal_test["id"]], "NIST-MS2.11": [internal_test["id"]]})
    go_live(m, attr, priya, maria, "Scores inform conversations only; no decision is taken on the score.")
    _backdate_live(m, attr, "2025-11-03")
    rows = {r["code"]: r for r in m.as_(m.user(maria)).get(f"/register/{attr}/roles")["rows"]}
    m.put(f"/register/{attr}/roles/{rows['transparency_notice_owner']['role_id']}",
          {"status": "no_such_person", "reason": "The HR business partner who owned the employee notice left in September. No replacement named yet."})

    # AIS-007: recruiting outreach agent used by the Pune sourcing team (India in scope), go-live
    lee = f"lee.park@{ABC}"
    m.as_(m.user(priya))
    agent = m.post("/register", {
        "name": "Recruiting outreach agent (HireLoop)", "type": "agent", "sourcing": "vendor", "department_id": depts["HR"], "stage": "in_development",
        "purpose": "Contacts shortlisted candidates, answers questions about the role and books interviews in recruiters' calendars. Used by the New York team and the Pune sourcing centre.",
        "users_scope": "role", "users_description": "Recruiters in New York and sourcing specialists in Pune", "user_count": 14, "owner_user_id": m.user(lee).id,
        "vendor_name": "HireLoop Inc.", "ai_provider": "anthropic", "model_name": "HireLoop Agent", "model_version": "2026.09", "algorithm_type": "llm_agent",
        "hosting": "vendor_cloud_us", "vendor_trains_on_data": "no", "vendor_documents": ["contract_ai_terms", "dpa", "model_card", "security_report", "incident_clause"],
        "autonomy": "acts_with_approval", "guardrail_policy_ref": "HL-POL-07 outreach limits", "agentassure_status": "vendor_only", "decision_impact": "none",
        "actions": [{"action_code": "read_records"}, {"action_code": "send_email"}, {"action_code": "write_calendar"}],
        "data": {"data_categories": ["personal"], "data_subjects": ["candidates"], "consent_basis": "consent", "consent_ref": "Candidate consent at application, v4",
                 "retention_period": "4 years after the hiring decision", "cross_border": "india"},
        "regulation_ids": [il, nist, dpdp, certin]})["id"]
    fill_roles(m, agent, {"ai_system_owner": lee, "technical_owner": f"sam.okafor@{ABC}", "human_oversight_person": f"tom.reyes@{ABC}", "stop_authority": lee,
                          "agent_permissions_approver": f"sam.okafor@{ABC}", "transparency_notice_owner": priya, "data_consent_steward": f"daniel.kim@{ABC}",
                          "bias_testing_lead": lee})
    uat = m.post(f"/register/{agent}/history", {"type": "deployment_test", "occurred_on": m.d(-45), "summary": "User acceptance test with the Pune sourcing team",
                                                "details": {"kind": "user_acceptance", "sample_size": 120, "result": "All 120 emails reviewed before sending; 6 corrected. Calendar writes limited to working hours."}})
    set_requirements(m, agent, NIST_MET | {
        "NIST-MG2.4": ("met", "Lee Park can pause the agent from the HireLoop console; the stop was tested before go-live."),
        "DPDP-01": ("met", "Consent notice in English and Hindi shown before candidates reply to the agent."),
        "DPDP-02": ("met", "Consent is limited to recruitment for the advertised role."),
        "DPDP-03": ("met", "The Data Protection Officer's contact is on the India careers page."),
        "DPDP-04": ("met", "Grievances go to the Pune Sourcing Centre Manager and are answered within 30 days."),
        "DPDP-05": ("met", "Access and erasure requests handled through the HireLoop admin console within 90 days."),
        "DPDP-06": ("not_applicable", "ABC is not notified as a significant data fiduciary."),
        "CERTIN-01": ("met", "Cyber incidents go to the AI Incident Response Lead, who reports to CERT-In within 6 hours."),
        "CERTIN-02": ("met", "Sam Okafor, IT Manager, is the point of contact with CERT-In."),
        "CERTIN-03": ("met", "HireLoop keeps logs for 180 days in its Mumbai region, confirmed in the contract."),
        "CERTIN-04": ("met", "Vendor confirms NTP synchronisation to NPL time servers for the India region."),
    }, entries={"NIST-MG2.4": [uat["id"]]})
    go_live(m, agent, priya, maria, "Emails need recruiter approval for the first 30 days; reviewed by the committee.")
    _backdate_live(m, agent, m.d(-40))

    # AIS-008 to AIS-010: the pipeline
    m.as_(m.user(priya))
    m.post("/register", {"name": "Video interview analysis", "type": "vendor_app", "sourcing": "vendor", "department_id": depts["HR"], "stage": "proposed",
                         "purpose": "Proposed: analyse recorded first-round video interviews and suggest a shortlist.", "vendor_name": "VidAssess Ltd.", "ai_provider": "unknown",
                         "algorithm_type": "speech", "decision_impact": "consequential", "owner_user_id": m.user(priya).id,
                         "data": {"data_categories": ["personal", "biometric"], "data_subjects": ["candidates"]},
                         "regulation_ids": [aivia, ll144, il, nist]})
    skills = m.post("/register", {
        "name": "Skills assessment scoring (SkillCheck)", "type": "vendor_app", "sourcing": "vendor", "department_id": depts["HR"], "stage": "ready_for_go_live",
        "purpose": "Scores online skills tests for finance and IT roles and ranks candidates for recruiter review.", "users_scope": "role", "users_description": "Recruiters",
        "user_count": 6, "owner_user_id": m.user(lee).id, "vendor_name": "SkillCheck Assessments LLC", "ai_provider": "unknown", "algorithm_type": "ranking",
        "hosting": "vendor_cloud_us", "vendor_trains_on_data": "no", "vendor_documents": ["contract_ai_terms", "dpa"], "decision_impact": "consequential",
        "data": {"data_categories": ["personal"], "data_subjects": ["candidates"], "consent_basis": "notice_only", "retention_period": "4 years after the hiring decision", "cross_border": "no"},
        "regulation_ids": [ll144, il, nist]})["id"]
    fill_roles(m, skills, {"ai_system_owner": lee, "technical_owner": f"sam.okafor@{ABC}", "human_oversight_person": f"tom.reyes@{ABC}", "transparency_notice_owner": priya,
                           "data_consent_steward": lee, "bias_testing_lead": ("pending", 21, "The committee is choosing the independent auditor for this tool.")})
    set_requirements(m, skills, NIST_MET | IL_MET | LL144_NOTICES | {
        "IL-01": ("partly_met", "Vendor impact analysis received; ABC's own analysis waits for the independent auditor."),
    })
    m.as_(m.user(f"grace.liu@{ABC}"))
    m.post("/register", {"name": "Cash forecasting model", "type": "in_house_model", "sourcing": "in_house", "department_id": depts["Finance"], "stage": "in_development",
                         "purpose": "Forecasts weekly cash position from receivables, payables and payroll.", "owner_user_id": m.user(f"grace.liu@{ABC}").id,
                         "ai_provider": "in_house", "algorithm_type": "regression", "hosting": "our_cloud", "decision_impact": "none",
                         "data": {"data_categories": ["confidential"], "data_subjects": ["none"], "consent_basis": "na"}, "regulation_ids": [nist]})
    return {"agent": agent, "ats": ats, "skills": skills}


# ---------------------------------------------------------------- tracing (R7, R8)
TRACE_ACTIONS = [
    ("Read candidate profile from the ATS", "ats.read_profile", "Candidate profile", "allowed", "HL-POL-07", None),
    ("Sent outreach email to a shortlisted candidate", "email.send", "Candidate name and email", "allowed", "HL-POL-07", "Approved by recruiter"),
    ("Answered a candidate question about the role", "chat.reply", "Job description", "allowed", "HL-POL-07", None),
    ("Booked a first-round interview in a recruiter's calendar", "calendar.create_event", "Recruiter calendar", "allowed", "HL-POL-07", None),
    ("Tried to book an interview outside working hours", "calendar.create_event", "Recruiter calendar", "blocked", "HL-POL-07 §3 working hours", None),
    ("Candidate asked about salary: handed to a recruiter", "handoff.recruiter", "Candidate message", "escalated", "HL-POL-07 §5 pay questions", "Tom Reyes"),
    ("Tried to attach a CV to an outreach email", "email.attach", "Candidate CV", "blocked", "HL-POL-07 §2 attachments", None),
]


def _trace_rows(m: Demo) -> list[dict]:
    from app.core.clock import utcnow

    now = utcnow().replace(microsecond=0) - timedelta(minutes=95)
    rows, n = [], 0
    for day in range(6, -1, -1):
        for i, (action, tool, data, decision, policy, approver) in enumerate(TRACE_ACTIONS):
            if day > 0 and i % 2:
                continue
            n += 1
            at = now - timedelta(days=day) - timedelta(minutes=37 * i + 11 * day)
            rows.append({"Time": at.isoformat(timespec="seconds"), "Session": f"S-{4100 + day * 10 + (i // 3)}", "Action": action, "Tool": tool, "Data touched": data,
                         "Decision": decision, "Policy": policy, "Approver or note": approver or "", "Agent": "hireloop-agent@abccorp.example", "Event id": f"HL-{20260000 + n}"})
    return rows


def abc_tracing(m: Demo, cid: str, ids: dict) -> None:
    maria, sponsor = m.user(f"maria.lopez@{ABC}"), m.user(f"robert.chen@{ABC}")
    m.as_(maria)
    sub = m.post("/addons/tracing/requests", {"system_ids": [ids["agent"]], "plan": "per_system", "approver_id": sponsor.id, "trial": False,
                                              "note": "The recruiting agent sends email and books calendars for candidates in New York and Pune. We want its actions on record."})
    m.as_(sponsor).post(f"/addons/requests/{sub['id']}/decide", {"approve": True, "comment": "Approved for the recruiting agent. Review cost at the next committee meeting."})
    # imported traces: a CSV export from the agent's console
    rows = _trace_rows(m)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    sam = m.user(f"sam.okafor@{ABC}")
    m.as_(m.user(f"priya.shah@{ABC}"))  # the Department Head imports the agent's action log; the Incident Response Lead handles incidents
    _upload(m, f"/register/{ids['agent']}/tracing/traces/import", "hireloop-actions-last-7-days.csv", buf.getvalue().encode(), "text/csv")
    from app.core.clock import utcnow

    start = utcnow().replace(microsecond=0) - timedelta(minutes=60)
    later = [{"time": (start + timedelta(minutes=9 * k)).isoformat(timespec="seconds"), "action": a, "tool": t, "data": dt, "decision": d,
              "policy": p, "agent": "hireloop-agent@abccorp.example", "event_id": f"HL-JSON-{k}", "session": "S-4200"}
             for k, (a, t, dt, d, p, _) in enumerate(TRACE_ACTIONS[:4])]
    _upload(m, f"/register/{ids['agent']}/tracing/traces/import", "hireloop-actions-last-hour.json", json.dumps(later).encode(), "application/json")
    # a closed incident with its CERT-In notice recorded, and an open one whose 6-hour clock is running
    m.as_(sam)
    path = f"/register/{ids['agent']}/tracing/incidents"
    closed = m.post(path, {"description": "The agent sent 12 candidates an interview invitation with another candidate's CV attached",
                           "found_at": _ago(m, 34, 15, 20), "severity": "high", "serious_kind": "none", "cyber_incident": True, "people_affected": 13, "owner_id": sam.id,
                           "cause": "A template change in HireLoop let the agent attach files from the shortlist folder.",
                           "containment": "Attachments switched off in the agent policy within the hour; recipients asked to delete the email."})
    for d in closed["deadlines"]:
        if d["status"] == "open":
            m.post(f"/register/{ids['agent']}/tracing/deadlines/{d['id']}", {"action": "done", "done_at": _ago(m, 34, 19, 5), "reference": "CERT-In acknowledgement ref. CERTIN-2026-114872"})
    m.post(f"{path}/{closed['id']}/close", {"closed_on": m.d(-27), "fix": "HireLoop removed file access from the agent's tool list; the policy now blocks attachments (HL-POL-07 §2)."})
    from app.core.clock import utcnow

    now = utcnow().replace(microsecond=0)
    m.post(path, {"description": "Sign-in to the HireLoop admin console from an unrecognised IP address using a sourcing specialist's account",
                  "found_at": (now - timedelta(minutes=90)).isoformat(), "severity": "high", "serious_kind": "none", "cyber_incident": True, "owner_id": sam.id,
                  "cause": "Under investigation. The account's password was reused on another site.",
                  "containment": "Account disabled and the agent's API key rotated. Sessions from the address blocked."})
    # R8: a second request waiting for the Executive Sponsor
    m.as_(maria).post("/addons/tracing/requests", {"system_ids": [ids["ats"]], "plan": "per_system", "approver_id": sponsor.id, "trial": True,
                                                   "note": "ScreenRank makes consequential decisions about candidates. A 30-day trial before the next bias audit cycle."})


# ---------------------------------------------------------------- Meridian: draft letter and a finding for QA
def meridian_after(m: Demo, mid: str) -> None:
    chief = m.user("chief@futran.demo")
    m.as_(chief)
    m.get(f"/clients/{mid}/applicability")
    m.post(f"/clients/{mid}/letters")
    f = m.post(f"/clients/{mid}/findings", {
        "title": "No executive sponsor for the AI governance programme", "severity": "medium", "template_section": "4.1", "proposed_owner": "Head of AI Compliance",
        "description": "Meridian has not named an executive sponsor for its AI governance programme. The Head of AI Compliance reports to the Chief Risk Officer, but no member of "
                       "the management board has taken responsibility for decisions about AI risk, including the credit risk scoring model.\n\n"
                       "Risk: Without an accountable executive, decisions on high-risk AI, such as whether the scoring model may go on being used while it is assessed, "
                       "have no clear owner, and resources for the EU AI Act programme depend on goodwill.",
        "recommended_remediation": "Name a management board member as executive sponsor, record the appointment and give them sign-off on Tier 3 systems.",
        "control_refs": ["ISO_42001 5.1", "NIST_AI_RMF GOVERN 2.3"]})
    m.post(f"/findings/{f['id']}/submit")


# ---------------------------------------------------------------- email (E1–E5)
ABC_STAFF = [
    ("Hannah Brooks", "HR"), ("Luis Fernandez", "HR"), ("Megan O'Connor", "HR"), ("Kwame Asante", "HR"), ("Sofia Romano", "HR"), ("Jared Kim", "HR"),
    ("Aisha Rahman", "Finance"), ("Peter Novak", "Finance"), ("Rachel Green", "Finance"), ("Victor Chen", "Finance"),
    ("Emily Carter", "Sales & Marketing"), ("Daniel Ortiz", "Sales & Marketing"), ("Fatima Hassan", "Sales & Marketing"), ("George Miller", "Sales & Marketing"),
    ("Ines Duarte", "Sales & Marketing"), ("Noah Fischer", "Sales & Marketing"), ("Olivia Grant", "Sales & Marketing"), ("Ravi Iyer", "HR"),
]
BOUNCED = "j.morales@abccorp.example"


def _email(name: str) -> str:
    first, last = name.lower().replace("'", "").split(" ", 1)
    return f"{first}.{last.replace(' ', '')}@{ABC}"


def mail(m: Demo, cid: str) -> None:
    from app.mail import links
    from app.mail.models import MailRecipient

    m.as_(m.user("admin@futran.demo")).get("/mail/groups?owner=futran")
    m.as_(m.user(f"sam.okafor@{ABC}"))
    groups = {g["system_key"]: g for g in m.get("/mail/groups")["groups"] if g["system_key"]}
    for email, name in ((f"maria.lopez@{ABC}", "Maria Lopez"), (f"daniel.kim@{ABC}", "Daniel Kim"), (f"priya.shah@{ABC}", "Priya Shah"), (f"sam.okafor@{ABC}", "Sam Okafor")):
        m.post(f"/mail/groups/{groups['ai_compliance_team']['id']}/members", {"email": email, "name": name})
    cohort = m.post("/mail/groups", {"name": "AI literacy cohort, autumn", "source": "manual", "purpose": "Staff who use AI tools in their work",
                                     "used_by": "AI literacy training"})
    lines = ["email,name"] + [f"{_email(n)},{n}" for n, _ in ABC_STAFF] + [f"{BOUNCED},Javier Morales"]
    m.post(f"/mail/groups/{cohort['id']}/import", {"csv": "\n".join(lines)})
    m.post(f"/mail/groups/{cohort['id']}/members", {"nested_group_id": groups["ai_compliance_team"]["id"]})
    m.as_(m.user(f"maria.lopez@{ABC}"))
    sent = m.post("/mail/send", {"group_ids": [cohort["id"]], "template_key": "training_ai_literacy", "mode": "personal", "reminder_days": [3, 7], "link_days": 14,
                                 "sender": "organization"})
    rows = list(m.db.scalars(select(MailRecipient).where(MailRecipient.send_id == sent["id"]).order_by(MailRecipient.email)))
    for i, r in enumerate(rows):
        if r.email == BOUNCED:
            # No service: in test mode nothing is delivered, so the mailbox's bounce report cannot arrive. Recorded as reply sync would record it.
            r.status, r.error = "bounced", "Bounced: 550 5.1.1 The email account that you tried to reach does not exist."
        elif i % 3 != 2:
            links.mark_completed(m.db, r)
        elif i % 2:
            links.mark_opened(m.db, r)
    m.db.commit()


# ---------------------------------------------------------------- law refresh (M3) and Chief Auditor alert (M6)
def _quote(m: Demo, code: str) -> tuple[str, str]:
    """The source quote and URL already recorded on a requirement of the approved law (checked by WS-A)."""
    from app.regmaster.models import Requirement

    from app.laws.models import Regulation

    current = select(Regulation.current_version_id).where(Regulation.current_version_id.is_not(None))
    req = m.db.scalar(select(Requirement).where(Requirement.code == code, Requirement.law_version_id.in_(current)).limit(1))
    if req is None or not req.source_quote or not req.source_url:
        raise DemoError(f"Requirement {code} has no recorded source quote")
    return req.source_quote, req.source_url


def _reply_items(m: Demo) -> dict:
    """What the in-process refresh client 'found'. Every change restates what the approved records already say (the
    requirements and their quoted sources), so nothing here asserts a new fact about the law."""
    from app.laws.publish import current_regulations
    from app.regmaster.models import LawVersion

    def reg(prefix):
        r = next(x for x in current_regulations(m.db) if (x.short_name or "").startswith(prefix))
        return r, m.db.get(LawVersion, r.current_version_id)

    nyc, nyc_v = reg("NYC Local Law 144")
    il, il_v = reg("HB 3773")
    co, co_v = reg("SB 26-189")
    certin, certin_v = reg("CERT-In Directions")
    dpdp, _ = reg("Digital Personal Data Protection Act")
    q_ll3, u_ll3 = _quote(m, "LL144-03")
    q_il4, _ = _quote(m, "IL-04")
    q_co8, u_co8 = _quote(m, "CO-08")
    q_c1, u_c1 = _quote(m, "CERTIN-01")
    q_d6, u_d6 = _quote(m, "DPDP-06")
    from app.regmaster.changes import current_value

    dpo_req = current_value(m.db, dpdp, "requirement.DPDP-06")
    dpo_req = {k: dpo_req[k] for k in ("code", "text", "applies_to", "needed_by_stage", "evidence_text", "role", "ai_types", "citation", "source_quote", "source_url")} | {"needed_by_stage": "program_setup"}

    def item(change_type, r, field, old, new, summary, url, quote, conf):
        return {"change_type": change_type, "regulation_id": r.id, "field_path": field, "old_value": old, "new_value": new if isinstance(new, str) else json.dumps(new),
                "summary": summary, "source_url": url, "source_quote": quote, "confidence": conf}

    return {
        "US-NYC": {"changes": [item("guidance", nyc, "law.main_duty", nyc_v.main_duty,
                                    "Yearly independent bias audit; publish the summary before use; notice 10 business days before use, with an alternative process or accommodation on request",
                                    "Main duty: add that the notice must let candidates ask for an alternative selection process or accommodation", u_ll3, q_ll3, "high")]},
        "US-IL": {"changes": [item("new_rule", il, "law.effective_text", il_v.effective_text,
                                   "In force 1 Jan 2026; the Department's rules on notice are still to be adopted",
                                   "Effective date note: the notice requirement depends on Department rules that are not yet adopted",
                                   "https://www.ilga.gov/Legislation/publicacts/view/103-0804", q_il4, "medium")]},
        "US-CO": {"changes": [item("new_rule", co, "law.main_duty", co_v.main_duty,
                                   f"{co_v.main_duty}; follow the Attorney General's rules once adopted (due by 1 Jan 2027)",
                                   "Main duty: add the Attorney General rules due by 1 Jan 2027", u_co8, q_co8, "high")]},
        "IN": {"changes": [
            item("guidance", certin, "law.main_duty", certin_v.main_duty,
                 "Report listed cyber incidents to CERT-In within 6 hours of noticing them; name a point of contact; keep ICT logs for 180 days in India; synchronise clocks",
                 "Main duty: list all four directions that apply to AI systems", u_c1, q_c1, "high"),
            item("role_mapping", dpdp, "requirement.DPDP-06", None, dpo_req,
                 "Data Protection Officer for significant data fiduciaries: needed at programme set-up rather than at each system's go-live", u_d6, q_d6, "medium"),
        ]},
    }


def law_refresh(m: Demo) -> dict:
    """One completed run over four geographies, then the Chief Auditor's decisions: two approved, one held, one sent to legal
    review, one left pending. The run's alert stays open for the Chief Auditor while changes wait."""
    from app.refresh.claude import FakeRefreshClient
    from app.refresh.models import RefreshProposalMeta
    from app.regmaster.models import ProposedChange

    client = FakeRefreshClient(replies=_reply_items(m), model="claude-demo (test client, no network)", tokens=(18500, 2100), searches=4)
    app_state = m.c.app.state
    before = getattr(app_state, "refresh_client_factory", None)
    app_state.refresh_client_factory = lambda _settings: client
    try:
        chief = m.user("chief@futran.demo")
        run = m.as_(chief).post("/admin/laws/refresh", {"kind": "law", "scope_mode": "chosen", "jurisdiction_codes": ["US-NYC", "US-IL", "US-CO", "IN"],
                                                       "source_set": "official"})
    finally:
        app_state.refresh_client_factory = before
    m.db.expire_all()
    changes = {c.field_path + "|" + (c.regulation_id or ""): c for c in m.db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run["id"]))}

    def find(field, prefix):
        reg_id = _law(m, prefix)
        c = changes.get(f"{field}|{reg_id}")
        if c is None:
            raise DemoError(f"The refresh did not propose {field} for {prefix}: {m.get('/admin/laws/refresh/' + run['id'])['warnings']}")
        return c.id

    nyc, il, co = find("law.main_duty", "NYC Local Law 144"), find("law.effective_text", "HB 3773"), find("law.main_duty", "SB 26-189")
    certin, dpdp = find("law.main_duty", "CERT-In Directions"), find("requirement.DPDP-06", "Digital Personal Data Protection Act")
    m.post(f"/reg/changes/{nyc}/decide", {"action": "approve", "note": "Matches §20-871(b)(1). The alternative process is already in each client's notice checklist."})
    m.post(f"/reg/changes/{certin}/decide", {"action": "approve", "note": "Restates the four directions already recorded as requirements."})
    m.post(f"/reg/changes/{co}/decide", {"action": "hold", "note": "Hold until the Attorney General adopts the rules; then add their duties as requirements."})
    m.post(f"/reg/changes/{dpdp}/decide", {"action": "legal_review", "note": "Whether the DPO must be in place before the first system goes live is a legal reading. Please advise."})
    legal = m.user(LEGAL[1])
    m.post(f"/reg/changes/{dpdp}/assign", {"user_id": legal.id})
    meta = m.db.get(RefreshProposalMeta, il)
    if meta is None:
        raise DemoError("No proposal bookkeeping for the Illinois change")
    return {"run_id": run["id"], "pending": il}


# ---------------------------------------------------------------- client alerts (A1)
def client_alerts(m: Demo, abc_id: str) -> None:
    from app.clientalerts.models import AlertSend

    m.as_(m.user("chief@futran.demo"))
    waiting = list(m.db.scalars(select(AlertSend).where(AlertSend.status == "waiting_approval").order_by(AlertSend.created_at)))
    nyc = next((s for s in waiting if s.organization_id == abc_id and "Local Law 144" in s.headline), None)
    if nyc is None:
        raise DemoError(f"No waiting client alert for ABC Corp on NYC Local Law 144: {[s.headline for s in waiting]}")
    m.patch(f"/alerts/sends/{nyc.id}", {"intro": "Futran has updated its record of NYC Local Law 144. Please check that your candidate notice offers an alternative "
                                                 "selection process or accommodation."})
    m.post("/alerts/sends/approve", {"ids": [nyc.id]})


# ---------------------------------------------------------------- opportunities (S1)
def opportunities(m: Demo, ids: dict) -> None:
    """Sales works the opportunities. Northwind and Meridian are current audit clients, so each offer waits for or has the
    Chief Auditor's approval; nothing offers ABC Corp remediation."""
    from app.sales.models import Opportunity

    sales, chief = m.user("sales@futran.demo"), m.user("chief@futran.demo")
    m.as_(sales)
    nw = m.post("/opportunities", {"organization_id": ids["northwind"], "service": "AI acceptable use policy and staff briefing", "service_kind": "training", "value": 18000,
                                   "why_now": "Route optimisation and driver scheduling now use AI; the board asked for an independent review.",
                                   "next_step": "Wait for the Chief Auditor, then send the proposal"})
    m.post(f"/opportunities/{nw['id']}/activities", {"kind": "call", "summary": "Call with Hannah Ortiz. Staff use ChatGPT for route notes; no policy yet."})
    m.post(f"/opportunities/{nw['id']}/request-approval", {"note": "Northwind's engagement is waiting for approval. Policy and training only, no remediation of findings."})
    eu = m.post("/opportunities", {"organization_id": ids["meridian"], "service": "EU AI Act readiness review: credit risk scoring model", "service_kind": "readiness", "value": 42000,
                                   "why_now": "Creditworthiness scoring is an Annex III high-risk use; the duties apply from 2 Dec 2027.",
                                   "next_step": "Proposal sent; follow up with Katrin Vogel"})
    m.post(f"/opportunities/{eu['id']}/request-approval", {"note": "Readiness work on a system that is not yet assessed. No findings raised yet."})
    lit = m.post("/opportunities", {"organization_id": ids["meridian"], "service": "AI literacy training for Berlin and Bangalore staff", "service_kind": "training", "value": 12500,
                                    "why_now": "EU AI Act Art. 4 AI literacy duty applies from 2 Feb 2025."})
    m.post(f"/opportunities/{lit['id']}/request-approval", {"note": "Training only."})
    m.as_(chief)
    m.post(f"/opportunities/{eu['id']}/approve", {"decision": "approve", "note": "Approved: readiness advice, separate team from the audit fieldwork."})
    m.post(f"/opportunities/{lit['id']}/approve", {"decision": "approve", "note": "Approved."})
    m.as_(sales)
    m.post(f"/opportunities/{eu['id']}/send-proposal", {"summary": "Proposal v1 sent: 6-week readiness review, fixed fee."})
    m.post(f"/opportunities/{lit['id']}/send-proposal", {"summary": "Proposal sent: two half-day sessions per site."})
    m.patch(f"/opportunities/{lit['id']}", {"stage": "won", "next_step": "Schedule the Berlin session"})
    for o in m.db.scalars(select(Opportunity).where(Opportunity.owner_id.is_(None))):
        m.patch(f"/opportunities/{o.id}", {"owner_id": sales.id})
    # the tracing add-on the client's sponsor approved: Sales records the order
    for o in m.db.scalars(select(Opportunity).where(Opportunity.organization_id == ids["abc"], Opportunity.trigger == "unlock_request")):
        from app.tracing.models import AddonSubscription

        sub = m.db.get(AddonSubscription, o.trigger_ref)
        if sub is not None and sub.status == "active":
            m.patch(f"/opportunities/{o.id}", {"value": 9600, "next_step": "Order confirmed; review usage at the first quarterly check-in"})
            m.post(f"/opportunities/{o.id}/send-proposal", {"summary": "Order form for the tracing add-on, per system, one system, annual."})
            m.patch(f"/opportunities/{o.id}", {"stage": "won"})
    abc_change = m.db.scalar(select(Opportunity).where(Opportunity.organization_id == ids["abc"], Opportunity.trigger == "law_change").limit(1))
    if abc_change is not None and abc_change.service_kind != "remediation":
        m.post(f"/opportunities/{abc_change.id}/activities", {"kind": "email", "summary": "Sent Maria Lopez the change summary and offered a notice review."})


# ---------------------------------------------------------------- entry point
def seed(m: Demo, ids: dict) -> dict:
    """Everything after the four demo clients exist. `ids`: abc, northwind, meridian, internal."""
    out = abc_after_audit(m, ids["abc"])
    from app.auth.passwords import hash_password
    from app.demo.seed_demo import DEMO_PASSWORD
    from app.demo.wsd import seed_wsd

    lit = seed_wsd(m.db, hash_password(DEMO_PASSWORD))  # litigation cases match the register built above
    m.db.commit()
    abc_tracing(m, ids["abc"], out)
    meridian_after(m, ids["meridian"])
    mail(m, ids["abc"])
    refresh = law_refresh(m)
    client_alerts(m, ids["abc"])
    opportunities(m, ids)
    m.db.commit()
    return {"litigation": lit, "refresh_run": refresh["run_id"]}
