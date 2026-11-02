"""Demo data for wave 3 WS-L (spec §21 F18, F17, F14, F19): comments and mentions, the public API and webhooks, agent
oversight and platform trust.

Everything goes through the platform's API as the person who would do it. Two steps are not API calls and are marked
"no service": the start-up seed of the SOC 2 starter list and Futran's own AI systems (it runs when the platform starts),
and one webhook tick (the scheduler runs it every minute). Webhooks are in fake mode in the demo: nothing leaves the
laptop, and the reserved name grc.abccorp.example is accepted without a DNS lookup.
"""
from __future__ import annotations

import base64
from datetime import timedelta

from sqlalchemy import select

from app.demo.seed_demo import ABC, Demo, DemoError

AUD, CHIEF, ADMIN = "auditor1@futran.demo", "chief@futran.demo", "admin@futran.demo"
PUB = "/api/public/v1"


def _comment(m: Demo, email: str, object_type: str, object_id: str, body: str, *, visibility: str | None = None, parent: str | None = None, mention: list[str] = ()) -> dict:
    ids = [m.user(e).id for e in mention]
    return m.as_(m.user(email)).post("/comments", {"object_type": object_type, "object_id": object_id, "body": body, "visibility": visibility, "parent_id": parent, "mention_ids": ids})


def comments(m: Demo, cid: str) -> dict:
    from app.engagements.models import Engagement
    from app.findings.models import Finding
    from app.questionnaire.models import Question, Response
    from app.systems.models import AISystem

    # ABC's current engagement: the newest that is not a draft (WS-K leaves an annual review draft after the completed audit)
    e = m.db.scalar(select(Engagement).where(Engagement.client_id == cid, Engagement.deleted_at.is_(None), Engagement.status.not_in(["draft", "pending_approval"])).order_by(Engagement.created_at.desc()).limit(1))
    f = m.db.scalar(select(Finding).where(Finding.engagement_id == e.id, Finding.title == "Recruiters use personal ChatGPT accounts with applicant data"))
    if f is None:
        raise DemoError("ABC Corp's ChatGPT finding is missing")
    # internal: the audit team discusses the finding
    t1 = _comment(m, AUD, "finding", f.id, "@Dana Whitfield the attestation shows two recruiters on free accounts. I have rated it medium because no "
                  "special-category data was entered. Do you agree, or should it be high given the applicant volumes?", mention=[CHIEF])
    _comment(m, CHIEF, "finding", f.id, "Medium is right on the evidence we have. Note in the working papers that we asked whether any CVs were pasted in "
             "and the answer was no.", parent=t1["id"])
    # shared: the auditor asks the client, the client answers
    t2 = _comment(m, AUD, "finding", f.id, "@Maria Lopez please confirm the date personal accounts will be blocked on company laptops, so we can record "
                  "it against the remediation item.", visibility="shared", mention=[f"maria.lopez@{ABC}"])
    _comment(m, f"maria.lopez@{ABC}", "finding", f.id, "@Alex Moreno IT blocks chatgpt.com sign-ins on company devices from the 1st of next month. Both "
             "recruiters already use the company Copilot licence.", parent=t2["id"], mention=[AUD])
    # a question response on the résumé screening system (SYS-001, HR)
    s = m.db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-001"))
    q = m.db.scalar(select(Question).join(Response, Response.question_id == Question.id).where(Response.engagement_id == e.id, Response.ai_system_id == s.id,
                                                                                               Question.code == "6.2.01"))
    r = m.db.scalar(select(Response).where(Response.engagement_id == e.id, Response.ai_system_id == s.id, Response.question_id == q.id)) if q else None
    if r is None:
        r = m.db.scalar(select(Response).where(Response.engagement_id == e.id, Response.ai_system_id == s.id, Response.status == "answered"))
    t3 = _comment(m, f"priya.shah@{ABC}", "response", r.id, "@Alex Moreno the vendor sent its 2026 bias test summary last week. Should we upload it here "
                  "or to the document request?", mention=[AUD])
    _comment(m, AUD, "response", r.id, "Upload it to the document request for bias test results, please, so it is linked to every system it covers.", parent=t3["id"])
    _comment(m, AUD, "response", r.id, "Vendor summary covers sex and race only; age is not tested. Raise at the closing meeting.")
    return {"comment_finding": f.id, "comment_response": r.id}


def _token(m: Demo, creds: dict, scope: str | None = None) -> str:
    basic = base64.b64encode(f"{creds['client']['client_id']}:{creds['client_secret']}".encode()).decode()
    data = {"grant_type": "client_credentials"} | ({"scope": scope} if scope else {})
    r = m.c.post(f"{PUB}/oauth/token", data=data, headers={"Authorization": f"Basic {basic}"})
    if r.status_code != 200:
        raise DemoError(f"Token request → {r.status_code}: {r.text[:300]}")
    return r.json()["access_token"]


def _pub(m: Demo, method: str, path: str, token: str, body=None) -> dict:
    r = m.c.request(method, f"{PUB}{path}", json=body, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise DemoError(f"{method} {PUB}{path} → {r.status_code}: {r.text[:500]}")
    m.db.expire_all()
    return r.json()


def public_api(m: Demo, cid: str, agent_id: str | None) -> dict:
    from app.core.clock import utcnow
    from app.publicapi.webhooks import run_tick

    m.as_(m.user(f"sam.okafor@{ABC}"))
    creds = m.post("/admin/api/clients", {"name": "ServiceNow GRC sync", "rate_limit_per_minute": 120,
                                          "scopes": ["inventory:read", "findings:read", "remediation:read", "attestation:read", "updates:read", "agent_logs:write"]})
    hook = m.post("/admin/api/webhooks", {"url": "https://grc.abccorp.example/futran/events", "description": "ServiceNow integration hub (IRM)",
                                          "events": ["signoff.completed", "remediation.overdue", "regulatory_update.published"]})["webhook"]
    m.post(f"/admin/api/webhooks/{hook['id']}/test")
    token = _token(m, creds)
    _pub(m, "GET", "/inventory/systems", token)
    _pub(m, "GET", "/findings", token)
    _pub(m, "GET", "/remediation", token)
    if agent_id:  # the agent's console sends its latest decisions through the API (tracing add-on is active on AIS-007)
        now = utcnow()
        events = [
            {"time": (now.replace(microsecond=0) - timedelta(minutes=40 - i * 7)).isoformat(), "action": a, "tool": t, "decision": d, "policy": p,
             "agent": "hireloop-agent@abccorp.example", "session": "S-4310", "event_id": f"HL-API-{i + 1}"}
            for i, (a, t, d, p) in enumerate([
                ("Read candidate profile from the ATS", "ats.read_profile", "allowed", "HL-POL-07"),
                ("Sent outreach email to a shortlisted candidate", "email.send", "allowed", "HL-POL-07"),
                ("Booked a first-round interview in a recruiter's calendar", "calendar.create_event", "allowed", "HL-POL-07"),
                ("Moved an interview after the candidate asked", "calendar.update_event", "allowed", "HL-POL-07"),
            ])]
        _pub(m, "POST", f"/agents/{agent_id}/decisions", token, {"events": events})
    run_tick(m.db, m.settings, utcnow())  # no service: the scheduler's webhook tick
    m.db.commit()
    return {"api_client": creds["client"]["id"], "webhook": hook["id"]}


REGISTRATION = {
    "tools": [
        {"name": "ats.read_profile", "description": "Reads a shortlisted candidate's profile in the ATS", "access": "read", "needs_approval": False},
        {"name": "email.send", "description": "Sends outreach email from the recruiting mailbox", "access": "act", "needs_approval": True},
        {"name": "chat.reply", "description": "Answers candidate questions about the role", "access": "act", "needs_approval": False},
        {"name": "calendar.create_event", "description": "Books interviews in recruiters' calendars, working hours only", "access": "act", "needs_approval": False},
        {"name": "handoff.recruiter", "description": "Hands a conversation to a recruiter", "access": "write", "needs_approval": False},
    ],
    "permissions": ["Read profiles of candidates on a shortlist for an open role", "Send email from careers@abccorp.example", "Book and move interviews in recruiters' calendars"],
    "approval_points": ["A recruiter approves each outreach email for the first 30 days", "Pay, visa and disability questions go to a recruiter"],
    "autonomy_level": "acts_with_approval",
    "kill_switch": "Lee Park (HR Systems Lead) pauses the agent in the HireLoop console.",
    "rate_limits": "200 emails a day; 50 calendar changes an hour",
}


def agent(m: Demo, cid: str) -> dict:
    from app.register.models import RegisterSystem

    s = m.db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == cid, RegisterSystem.reference == "AIS-007"))
    if s is None:
        raise DemoError("ABC Corp's recruiting agent AIS-007 is missing")
    m.as_(m.user(f"priya.shah@{ABC}")).put(f"/register/{s.id}/agent", REGISTRATION | {"kill_switch_tested_on": m.d(-41)})
    # HireLoop added rescheduling: Lee's team registers the new tool, which alerts the compliance officer
    more = dict(REGISTRATION)
    more["tools"] = REGISTRATION["tools"] + [{"name": "calendar.update_event", "description": "Moves an interview when the candidate asks", "access": "act", "needs_approval": False}]
    m.put(f"/register/{s.id}/agent", more | {"kill_switch_tested_on": m.d(-41)})
    # the auditor samples the agent's decisions and records a verdict on each
    m.as_(m.user(AUD))
    smp = m.post(f"/clients/{cid}/agents/{s.id}/samples", {"size": 8, "period_days": 30, "seed": 20261102})
    for d in smp["decisions"]:
        if d.get("decision") == "blocked" and "attach" in (d.get("action") or "").lower():
            v, note = "needs_follow_up", "Blocked as the policy requires. Confirm HireLoop removed the attachment template after INC-001."
        elif d.get("decision") == "escalated":
            v, note = "appropriate", "Pay question handed to a recruiter as HL-POL-07 §5 requires."
        else:
            v, note = "appropriate", "Within the registered tools and HL-POL-07."
        m.post(f"/agent-samples/{smp['id']}/reviews", {"trace_id": d["id"], "verdict": v, "note": note})
    m.post(f"/agent-samples/{smp['id']}/complete", {"conclusion": "Decisions in the sample stay within the agent's registration and policy. One follow-up on the "
                                                                  "attachment control, linked to INC-001. No evidence of rubber-stamping: hand-offs to recruiters occur each month."})
    return {"agent_sample": smp["id"]}


def platform_trust(m: Demo) -> dict:
    from app.platformtrust.seed import seed_controls, seed_platform_ai

    seed_controls(m.db)  # no service: the start-up seed (app.platformtrust.startup)
    seed_platform_ai(m.db, m.settings)
    m.db.commit()
    m.as_(m.user(ADMIN))
    page = m.get("/staff/admin/trust")
    by = {c["code"]: c for c in page["controls"]}
    people = {p["name"]: p["id"] for p in page["people"]}
    owner = people.get("Ada Brennan")
    chief = people.get("Dana Whitfield")
    updates = {
        "CC1.1": {"status": "implemented", "owner_id": chief, "evidence_link": "https://futran.sharepoint.example/policies/code-of-conduct-2026.pdf", "last_reviewed_on": m.d(-20),
                  "notes": "All 14 staff signed in October."},
        "CC6.1": {"status": "implemented", "owner_id": owner, "evidence_link": "Tenancy tests in the release pipeline; MFA enforced for all Futran accounts", "last_reviewed_on": m.d(-12)},
        "CC6.7": {"status": "implemented", "owner_id": owner, "evidence_link": "Architecture note: encryption at rest and token sealing", "last_reviewed_on": m.d(-12)},
        "CC7.2": {"status": "in_progress", "owner_id": owner, "notes": "Audit log is append-only; alert routing to the on-call mailbox still to set up."},
        "CC8.1": {"status": "implemented", "owner_id": owner, "evidence_link": "Pull request reviews and the test suite on every change", "last_reviewed_on": m.d(-30)},
        "CC9.2": {"status": "in_progress", "owner_id": chief, "notes": "Anthropic and hosting SOC 2 reports received; email provider pending."},
        "PI1.3": {"status": "implemented", "owner_id": chief, "evidence_link": "AI interaction log and acceptance records", "last_reviewed_on": m.d(-7)},
        "A1.2": {"status": "in_progress", "owner_id": owner, "notes": "Nightly backups run; first restore test booked."},
    }
    for code, body in updates.items():
        if code in by:
            m.patch(f"/staff/admin/trust/controls/{by[code]['id']}", {k: v for k, v in body.items() if v is not None})
    return {}


def seed(m: Demo, ids: dict) -> dict:
    from app.register.models import RegisterSystem

    cid = ids["abc"]
    out = comments(m, cid)
    out |= agent(m, cid)
    s = m.db.scalar(select(RegisterSystem).where(RegisterSystem.organization_id == cid, RegisterSystem.reference == "AIS-007"))
    out |= public_api(m, cid, s.id if s else None)
    out |= platform_trust(m)
    return out
