"""Demo data for WS-H (spec §21 F4, F8; screens 26 and 28). Everything goes through the API as the person who would do it.

Screen 26 (regulatory change alerts). Facts were checked on 2 November 2026 against the sources linked on each update:
- NYC Local Law 144 enforcement: Office of the New York State Comptroller, "Enforcement of Local Law 144 – Automated
  Employment Decision Tools", report 2024-N-6, released 2 December 2025 (audit period July 2023 to June 2025): DCWP
  surveyed 32 companies and found 1 issue of non-compliance; the auditors found at least 17 potential instances in the
  same companies; DCWP received 2 complaints in the period. Published, matched to ABC Corp, sent to A1 for approval.
- Colorado SB 26-189: signed 14 May 2026, deployer obligations from 1 January 2027 (notice before or at use, explanation
  within 30 days of an adverse decision, correction, human review, three-year records). The source is a law-firm summary
  (Eckert Seamans); the enrolled act on leg.colorado.gov could not be opened when this was written, so the update says so.
- California SB 947 "No Robo Bosses Act": passed 31 August 2026 (Senate 28-10, Assembly 53-14, Senator McNerney's press
  release), signed 30 September 2026 (law-firm summary). The operative date is not confirmed, so the update waits for a
  second reviewer with that note.
- Great American AI Act: a discussion draft released by Representatives Obernolte and Trahan on 4 June 2026, not
  introduced; it would preempt state laws specifically regulating the development of AI models for three years. A watch
  item with no client action.

Screen 28 (new AI projects) at ABC Corp: a website sales assistant approved with two conditions (one marked met), an
interview screening module in review (Tier 3, the department review done, the DPO's pending, an independent opinion
requested from Futran), and a draft. A reassessment trigger on an existing register system: Finance retrains the invoice
anomaly model (version 2.3 to 2.4), which the register edit detects.
"""
from __future__ import annotations

from sqlalchemy import select

from app.demo.seed_demo import ABC, Demo, DemoError

LEGAL = "legal@futran.demo"
CHIEF = "chief@futran.demo"

OSC_URL = "https://www.osc.ny.gov/state-agencies/audits/2025/12/02/enforcement-local-law-144-automated-employment-decision-tools"
CO_URL = "https://www.eckertseamans.com/legal-updates/colorado-repeals-and-replaces-its-landmark-ai-statute-what-businesses-need-to-know"
CA_URL = "https://sd05.senate.ca.gov/news/legislature-approves-no-robo-bosses-act-2026-ensure-human-oversight-ai-workplace"
GAAIA_URL = "https://obernolte.house.gov/media/press-releases/obernolte-trahan-release-discussion-draft-great-american-ai-act"


def _jur(m: Demo, code: str) -> str:
    from app.reference.models import Jurisdiction

    j = m.db.scalar(select(Jurisdiction).where(Jurisdiction.code == code))
    if j is None:
        raise DemoError(f"No jurisdiction {code}")
    return j.id


def _law_id(m: Demo, prefix: str) -> str | None:
    from app.laws.publish import current_regulations

    hits = [r for r in current_regulations(m.db) if (r.short_name or "").startswith(prefix)]
    return hits[0].id if hits else None


def _depts(m: Demo, cid: str) -> dict[str, str]:
    from app.tenancy.models import Department

    return {d.name: d.id for d in m.db.scalars(select(Department).where(Department.organization_id == cid, Department.deleted_at.is_(None)))}


def _publish(m: Demo, body: dict) -> dict:
    m.as_(m.user(LEGAL))
    u = m.post("/reg/updates", body)
    m.post(f"/reg/updates/{u['id']}/submit")
    m.as_(m.user(CHIEF))
    return m.post(f"/reg/updates/{u['id']}/review", {"approve": True, "note": "Checked against the source."})


def updates(m: Demo, cid: str) -> dict:
    ll144, co, ca = _law_id(m, "NYC Local Law 144"), _law_id(m, "SB 26-189"), _law_id(m, "SB 947")
    nyc = _publish(m, {
        "change_type": "enforcement_action", "jurisdiction_id": _jur(m, "US-NYC"), "regulation_id": ll144, "law_name": "NYC Local Law 144",
        "title": "State Comptroller audit finds DCWP's enforcement of the AI hiring law weak",
        "summary": "The New York State Comptroller's audit of DCWP (report 2024-N-6, 2 December 2025) found that DCWP surveyed 32 companies and identified one "
                   "issue of non-compliance, while the auditors found at least 17 potential instances in the same companies. DCWP received two complaints "
                   "between July 2023 and June 2025. The audit recommends that DCWP find non-compliance through its own research, not only complaints.",
        "todo_text": "Confirm the bias audit of each tool used for New York City roles is less than 12 months old\n"
                     "Check the published summary of results and the distribution date on the careers site\n"
                     "Check candidates receive the notice at least 10 business days before the tool is used",
        "source_url": OSC_URL, "source_name": "Office of the New York State Comptroller",
        "source_quote": "We reviewed the same companies and identified at least 17 instances of potential non-compliance under LL144.",
        "affected_features": ["employment_hiring"]})
    co_u = _publish(m, {
        "change_type": "effective_date", "jurisdiction_id": _jur(m, "US-CO"), "regulation_id": co, "law_name": "Colorado SB 26-189",
        "title": "Deployer obligations begin 1 January 2027", "effective_on": "2027-01-01",
        "summary": "SB 26-189, signed on 14 May 2026, repeals and replaces the Colorado AI Act. From 1 January 2027 deployers of automated decision-making "
                   "technology in consequential decisions must give notice before or at the time of use, explain an adverse decision within 30 days, let "
                   "people correct their data and ask for human review, and keep records for three years.",
        "todo_text": "List the systems that make or substantially assist consequential decisions about Colorado residents\n"
                     "Prepare the notice and the 30-day explanation process\nSet up human review and data correction requests",
        "source_url": CO_URL, "source_name": "Eckert Seamans (law-firm summary)",
        "verify_note": "Link the enrolled act on leg.colorado.gov; enforcement depends on Attorney General rulemaking.",
        "affected_features": ["consequential_decisions_admt", "employment_hiring"]})
    m.as_(m.user(LEGAL))
    ca_u = m.post("/reg/updates", {
        "change_type": "new_law", "jurisdiction_id": _jur(m, "US-CA"), "regulation_id": ca, "law_name": "California SB 947 \"No Robo Bosses Act\"",
        "title": "Employers may not rely solely on an automated decision system to discipline or dismiss workers",
        "summary": "The legislature passed SB 947 on 31 August 2026 (Senate 28-10, Assembly 53-14) and the Governor signed it on 30 September 2026. Employers "
                   "may not rely only on an automated decision system for discipline or termination; when one assists, a person must review and verify the "
                   "decision, and workers must be told it was used. Enforcement is by the Labor Commissioner, the Attorney General and local prosecutors.",
        "source_url": CA_URL, "source_name": "Senator McNerney, press release",
        "verify_note": "Operative date to confirm against the chaptered text; the signing date is from a law-firm summary.",
        "affected_features": ["employment_hiring"]})
    m.post(f"/reg/updates/{ca_u['id']}/submit")
    watch = _publish(m, {
        "change_type": "pending_bill", "jurisdiction_id": _jur(m, "US"), "law_name": "Great American AI Act (discussion draft)", "watch": True,
        "title": "Federal discussion draft would preempt state laws on AI model development for three years",
        "summary": "Representatives Obernolte and Trahan released a discussion draft on 4 June 2026. It has not been introduced. Title I would preempt state "
                   "laws specifically regulating the development of AI models for three years; laws of general applicability and deployment duties are not "
                   "covered. Watch item; no client action.",
        "source_url": GAAIA_URL, "source_name": "Office of Representative Jay Obernolte", "affected_features": []})
    # Send the NYC alert to ABC Corp: it waits for the Chief Auditor's approval in Client alerts (A1)
    m.as_(m.user(CHIEF))
    m.post(f"/reg/updates/{nyc['id']}/alerts", {"organization_ids": [cid]})
    m.put(f"/reg/updates/digest/{cid}", {"enabled": True})
    return {"reg_update_nyc": nyc["id"], "reg_update_co": co_u["id"], "reg_update_ca": ca_u["id"], "reg_update_watch": watch["id"]}


def projects(m: Demo, cid: str) -> dict:
    d = _depts(m, cid)
    ny, il, ca, nyc = _jur(m, "US-NY"), _jur(m, "US-IL"), _jur(m, "US-CA"), _jur(m, "US-NYC")
    marco, daniel, maria, priya = (m.user(f"{x}@{ABC}") for x in ("marco.diaz", "daniel.kim", "maria.lopez", "priya.shah"))
    # 1. Approved with conditions: a public sales assistant (Tier 2)
    m.as_(marco)
    p1 = m.post("/projects", {
        "project_name": "Website sales assistant", "department_id": d["Sales & Marketing"], "tool_or_vendor": "Intercom Fin AI agent", "system_type": "genai_chat_tool",
        "sourcing": "vendor", "planned_go_live": m.d(75), "jurisdiction_ids": [ny, il, ca],
        "purpose": "Answers visitors' questions about products and pricing on the website and passes qualified leads to the sales team. A person takes over on request.",
        "data_categories": ["personal"], "data_subjects": ["customers", "public"], "decision_impact": "informs", "public_facing": True})
    m.post(f"/projects/{p1['id']}/submit")
    m.post(f"/projects/{p1['id']}/reviews", {"step": "department", "recommendation": "approve", "comment": "Hand-off to a sales representative on request is configured; answers come from the product catalogue only."})
    m.as_(daniel)
    m.post(f"/projects/{p1['id']}/reviews", {"step": "dpo", "recommendation": "approve_with_conditions",
                                             "comment": "Chat transcripts hold personal data: a DPIA and a notice at the start of each chat are needed before launch."})
    m.as_(maria)
    p1 = m.post(f"/projects/{p1['id']}/decide", {
        "decision": "approved_with_conditions", "note": "Approved on the DPO's two conditions. Go-live waits until both are closed.",
        "conditions": [{"text": "Show a notice at the start of every chat that the visitor is talking to an AI system", "owner_user_id": marco.id, "due_on": m.d(30)},
                       {"text": "Complete a data protection impact assessment covering chat transcripts and retention", "owner_user_id": daniel.id, "due_on": m.d(45)}]})
    m.as_(marco)
    m.post(f"/projects/{p1['id']}/conditions/{p1['conditions'][0]['id']}/met", {"note": "Notice text approved by Legal on 28 October; shown on the staging site before the first message."})
    # 2. In review: a Tier 3 interview screening module for New York City and Chicago roles
    m.as_(priya)
    p2 = m.post("/projects", {
        "project_name": "Interview screening module", "department_id": d["HR"], "tool_or_vendor": "ScreenRank Interview", "system_type": "vendor_app", "sourcing": "vendor",
        "planned_go_live": m.d(120), "jurisdiction_ids": [nyc, il],
        "purpose": "Scores recorded first-round interview answers and ranks candidates for recruiter review for New York City and Chicago roles.",
        "data_categories": ["personal", "sensitive"], "data_subjects": ["candidates"], "decision_impact": "consequential", "public_facing": False})
    m.post(f"/projects/{p2['id']}/submit")
    m.post(f"/projects/{p2['id']}/reviews", {"step": "department", "recommendation": "approve_with_conditions",
                                             "comment": "Only with an independent bias audit before it is used for New York City roles, and candidate notices ten business days before use."})
    m.as_(maria)
    m.post(f"/projects/{p2['id']}/opinion")
    # 3. A draft in Sales & Marketing
    m.as_(m.user(f"owen.hart@{ABC}"))
    p3 = m.post("/projects", {"project_name": "Meeting notes summariser", "department_id": d["Sales & Marketing"], "tool_or_vendor": "Otter.ai", "system_type": "embedded_feature",
                              "sourcing": "vendor", "jurisdiction_ids": [ny], "purpose": "Summarises internal sales meetings."})
    return {"project_approved": p1["id"], "project_in_review": p2["id"], "project_draft": p3["id"]}


def reassessment(m: Demo, cid: str) -> dict:
    """Finance retrains the invoice anomaly model: the register edit raises a version-change trigger."""
    from app.register.models import RegisterSystem

    s = m.db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == cid, RegisterSystem.name == "Invoice anomaly detection"))
    if s is None:
        raise DemoError("ABC Corp has no invoice anomaly detection system in the register.")
    m.as_(m.user(f"grace.liu@{ABC}"))
    m.patch(f"/register/{s.id}", {"model_version": "2.4", "reason": "Retrained on 2026 supplier invoices; new threshold for duplicate payments."})
    return {"trigger_system": s.id}


def seed(m: Demo, ids: dict) -> dict:
    cid = ids.get("abc")
    if not cid:
        raise DemoError("wave3_h needs ABC Corp from the earlier demo steps.")
    out = updates(m, cid)
    out |= projects(m, cid)
    out |= reassessment(m, cid)
    m.db.commit()
    return out
