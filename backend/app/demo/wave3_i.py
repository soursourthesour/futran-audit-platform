"""Demo data for WS-I: the policy builder (27), AI literacy training (33) and the Trust Center (32), for ABC Corp.

ABC's audit is complete. Its IT manager builds the AI acceptable use policy from the Futran template, the CAICO approves
it and staff are asked to acknowledge it; the human oversight procedure is waiting for approval with a Futran review
requested. Training modules are assigned by department with realistic completion (HR ahead, Sales and Marketing behind
the 80% target). The Trust Center is live at /trust/abc-corp with items confirmed against the signed report, and one
item waiting in the Chief Auditor's confirmation queue.

Everything goes through the API as the person who would do it. The few direct writes are marked "no service": staff
answering links in their email (nothing is delivered in test mode, so the link cannot be followed), completion dates in
the past, and page views on earlier days.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.demo.seed_demo import ABC, Demo, DemoError

AUP = {
    "approved_tools": ["Microsoft 365 Copilot (company account)", "ScreenRank résumé screening in the applicant tracking system", "Zendesk AI for customer support",
                       "Invoice anomaly detection (Finance, in-house)"],
    "personal_accounts": "not_allowed", "prohibited_data": ["client_data", "personal_data", "source_code", "health"],
    "policy_owner": "Maria Lopez, Chief AI Compliance Officer", "approving_body": "AI governance committee",
    "request_route": "the AI governance committee, through the IT service desk", "incident_contact": "their manager and the AI incident response owner",
    "contractors": True, "people_decisions": True, "nyc_hiring": True, "eu_operations": False, "review_cycle": "annually",
}
# share of each department that finishes each module (HR ahead, Sales and Marketing behind the 80% target)
DONE = {"HR": 0.88, "Finance": 0.8, "Sales & Marketing": 0.55}


def _abc(ids: dict) -> str:
    cid = ids.get("abc")
    if not cid:
        raise DemoError("wave3_i needs ABC Corp from the earlier demo steps.")
    return cid


def _policies(m: Demo, cid: str) -> dict:
    sam, maria, chief = m.user(f"sam.okafor@{ABC}"), m.user(f"maria.lopez@{ABC}"), m.user("chief@futran.demo")
    lib = m.as_(maria).get("/policies")
    commitment = next((c["id"] for c in lib["commitments"] if c["suggested_template"] == "acceptable_use"), None)
    m.as_(sam)
    p = m.post("/policies", {"template_code": "acceptable_use", "commitment_id": commitment})
    m.put(f"/policies/{p['id']}/answers", {"answers": p["answers"] | AUP, "regenerate": True})
    blocks = m.get(f"/policies/{p['id']}")["blocks"]
    # ABC adds its own line on recruiters' messages after the "Using AI output responsibly" list
    at = next(i for i, b in enumerate(blocks) if b["type"] == "heading" and "Using AI output" in b["text"]) + 2
    blocks.insert(at, {"type": "paragraph", "text": "Recruiters may use Copilot to draft candidate messages, but a recruiter reads and edits every message before it is sent."})
    m.put(f"/policies/{p['id']}/text", {"blocks": blocks})
    m.post(f"/policies/{p['id']}/submit")
    m.as_(maria)
    aup = m.post(f"/policies/{p['id']}/approve", {"acknowledgment": {"reminder_days": [3, 7], "link_days": 21}})
    _staff_acknowledge(m, aup["id"], share=0.7)
    # the human oversight procedure: drafted, Futran asked to tailor it, waiting for the CAICO
    m.as_(sam)
    ho = m.post("/policies", {"template_code": "human_oversight"})
    m.put(f"/policies/{ho['id']}/answers", {"answers": ho["answers"] | {"policy_owner": "Maria Lopez, Chief AI Compliance Officer", "oversight_lead": "HR Systems Lead",
                                                                        "systems": "ScreenRank résumé screening and every other Tier 3 AI system"}, "regenerate": True})
    m.as_(maria).post(f"/policies/{ho['id']}/futran-review", {"note": "Please tailor the review steps to ScreenRank and our recruiters' workload."})
    m.as_(sam).post(f"/policies/{ho['id']}/submit")
    m.as_(chief).put(f"/futran/policies/{ho['id']}/team", {"user_ids": [m.user("em@futran.demo").id]})
    # a draft model change procedure, not yet sent
    m.as_(sam)
    mc = m.post("/policies", {"template_code": "model_change_management"})
    m.put(f"/policies/{mc['id']}/answers", {"answers": mc["answers"] | {"policy_owner": "Sam Okafor, IT Manager"}, "regenerate": True})
    return {"aup": aup["id"], "oversight": ho["id"]}


def _staff_acknowledge(m: Demo, policy_id: str, share: float) -> None:
    """No service: in test mode the email is not delivered, so staff cannot follow their links. Recorded as the link would."""
    from app.mail import links
    from app.mail.models import DirectoryPerson, MailRecipient, MailSend
    from app.policies.models import PolicyAcknowledgment, PolicyDocument
    from app.policies.service import record_acknowledgment

    p = m.db.get(PolicyDocument, policy_id)
    rows = list(m.db.scalars(select(MailRecipient).join(MailSend, MailSend.id == MailRecipient.send_id)
                             .where(MailSend.campaign_type == "policy_ack", MailSend.campaign_id == policy_id).order_by(MailRecipient.email)))
    n = round(len(rows) * share)
    for i, r in enumerate(rows[:n]):
        person = m.db.get(DirectoryPerson, r.person_id) if r.person_id else None
        a = record_acknowledgment(m.db, p, r.email, person.name if person else r.name, person=person, recipient_id=r.id)
        a.acknowledged_at = a.acknowledged_at - timedelta(hours=6 + 7 * (n - i))
        links.mark_completed(m.db, r)
    m.db.commit()
    assert m.db.scalar(select(PolicyAcknowledgment.id).where(PolicyAcknowledgment.policy_id == policy_id)) is not None


def _training(m: Demo, cid: str) -> None:
    from app.core.clock import utcnow
    from app.tenancy.models import Department
    from app.training import modules as M
    from app.training import service as svc
    from app.training.models import TrainingAssignment

    maria = m.user(f"maria.lopez@{ABC}")
    m.as_(maria)
    m.put("/training/program", {"target_pct": 80, "target_date": m.d(30)})
    depts = {d.name: d.id for d in m.db.scalars(select(Department).where(Department.organization_id == cid, Department.deleted_at.is_(None)))}
    everyone = [depts[n] for n in DONE if n in depts]
    m.post("/training/assign", {"module_codes": ["acceptable_use", "shadow_ai"], "audience": {"kind": "departments", "ids": everyone}, "due_date": m.d(21), "reminder_days": [3, 7]})
    if "HR" in depts:
        m.post("/training/assign", {"module_codes": ["bias_basics_hr"], "audience": {"kind": "departments", "ids": [depts["HR"]]}, "due_date": m.d(21)})
    m.post("/training/assign", {"module_codes": ["human_oversight"], "audience": {"kind": "role", "role": "dept_compliance_lead"}, "due_date": m.d(14)})
    # No service: staff take the modules through the links in their email, which test mode does not deliver. Each finish goes
    # through the same service the player calls, with the answers a person who read the module would give.
    names = {v: k for k, v in depts.items()}
    rows = sorted(m.db.scalars(select(TrainingAssignment).where(TrainingAssignment.organization_id == cid)), key=lambda a: (a.module_code, a.email))
    by_group: dict[tuple, list] = {}
    for a in rows:
        by_group.setdefault((a.module_code, names.get(a.department_id, "")), []).append(a)
    now = utcnow()
    for (code, dept), group in by_group.items():
        share = DONE.get(dept, 0.5)
        done = round(len(group) * share) if code != "human_oversight" else len(group) - 1
        quiz = M.library()[code]["quiz"]
        for i, a in enumerate(group):
            if i >= done:
                if i % 2 == 0:
                    svc.check(m.db, a, quiz[0]["id"], quiz[0]["answer"], "ABC Corp")  # started, not finished
                continue
            for j, q in enumerate(quiz):
                wrong = next(o["id"] for o in q["options"] if o["id"] != q["answer"])
                svc.check(m.db, a, q["id"], wrong if (i + j) % 7 == 3 and j < len(quiz) - 1 and len(quiz) >= 5 else q["answer"], "ABC Corp")
            svc.finish(m.db, a)
            a.completed_at = now - timedelta(days=(i * 3) % 12 + 1, hours=i % 9)
            a.started_at = a.completed_at - timedelta(minutes=M.library()[code]["minutes"] + i % 6)
    m.db.commit()
    m.post("/training/evidence")


def _trust(m: Demo, cid: str, pol: dict) -> None:
    from app.core.clock import today
    from app.trust.models import TrustCenterView

    maria, chief = m.user(f"maria.lopez@{ABC}"), m.user("chief@futran.demo")
    m.as_(maria)
    m.put("/trust/page", {"slug": "abc-corp", "title": "How ABC Corp governs its use of AI", "live": True, "access": "public", "contact_email": "ai-questions@abccorp.example",
                          "intro": "We use AI to help our recruiting, finance and customer support teams. These are the commitments we make and the independent review behind them."})
    src = m.get("/trust")["sources"]
    items = []
    if src["engagements"]:
        items.append(m.post("/trust/items", {"kind": "badge", "source_id": src["engagements"][0]["id"], "show_rating": False}))
    items.append(m.post("/trust/items", {"kind": "commitment", "title": "AI in hiring",
                                         "body": "Our résumé screening tool helps recruiters; a trained person reviews every recommendation before anyone is rejected. "
                                                 "Candidates for New York City roles are told at least 10 business days before it is used and can ask for an alternative process."}))
    if src["bias_summaries"]:
        items.append(m.post("/trust/items", {"kind": "bias_summary", "source_id": src["bias_summaries"][0]["id"]}))
    items.append(m.post("/trust/items", {"kind": "policy", "source_id": pol["aup"], "body": "The rules every member of staff follows when using AI tools at work."}))
    items.append(m.post("/trust/items", {"kind": "governance", "title": "Governance",
                                         "body": "An AI governance committee chaired by our Chief AI Compliance Officer, with our Chief Operating Officer as a member, approves AI policy and every high-risk use of AI. Named owners are responsible for explainability, human oversight and AI incidents."}))
    rights = m.post("/trust/items", {"kind": "rights_contact", "title": "Your rights", "link_label": "Make a request", "link_url": "mailto:ai-questions@abccorp.example",
                                     "body": "You can ask how an AI-assisted decision about you was made, ask for a person to review it, or ask us to correct your data."})
    for it in items:
        m.as_(maria).post(f"/trust/items/{it['id']}/approve")
        m.as_(chief).post(f"/trust/items/{it['id']}/confirm", {"note": "Matches the signed report (governance, findings and LL144 summary sections)."})
    m.as_(maria).post(f"/trust/items/{rights['id']}/approve")  # waits in the Chief Auditor's confirmation queue
    # No service: page views on earlier days (the counter only records the day a page is opened)
    from app.trust.models import TrustCenterPage

    page = m.db.scalar(select(TrustCenterPage).where(TrustCenterPage.organization_id == cid))
    for back in range(1, 30):
        n = (back * 37) % 23 + (14 if back % 7 in (1, 2) else 4)
        m.db.add(TrustCenterView(organization_id=cid, page_id=page.id, day=today() - timedelta(days=back), views=n))
    m.db.commit()


def seed(m: Demo, ids: dict) -> dict:
    cid = _abc(ids)
    pol = _policies(m, cid)
    _training(m, cid)
    _trust(m, cid, pol)
    return {"abc_aup_policy": pol["aup"], "abc_oversight_policy": pol["oversight"]}
