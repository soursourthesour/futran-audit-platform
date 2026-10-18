"""Demo tenants for walkthroughs and the hand-over (plan Task 32).

Everything is created through the platform's own API and services, signing in as each role in turn, so the demo data
obeys the same rules as real use. Only allowed in test mode (MFA off or email to the outbox).

- Futran: six staff users, password Demo-Password-2026, MFA off.
- ABC Corp: New York, Chicago and remote; HR, Finance, Sales & Marketing; one engagement taken from draft to completed,
  with SYS-001 to SYS-004 (SYS-001 reproduces the scoring worked example).
- Northwind Logistics: a new client drafted by the auditor, waiting for the Chief Auditor's approval.
- Meridian GmbH: Berlin and Bangalore, at stage 3 (discovery).
- Futran Solutions (internal): an internal client at stage 2 (setup).
"""
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

DEMO_PASSWORD = "Demo-Password-2026"
FUTRAN_STAFF = [
    ("Ada Brennan", "admin@futran.demo", "admin", "Platform administrator"),
    ("Dana Whitfield", "chief@futran.demo", "chief_auditor", "Chief Auditor"),
    ("Alex Moreno", "auditor1@futran.demo", "auditor", "Senior Auditor"),
    ("Priyanka Rao", "auditor2@futran.demo", "auditor", "Auditor"),
    ("Quinn Taylor", "qa@futran.demo", "qa_reviewer", "QA Reviewer"),
    ("Elena Brooks", "em@futran.demo", "engagement_manager", "Engagement Manager"),
]
APPROVAL = {"client_message": "Thank you for choosing Futran. Your engagement letter and getting-started pack are attached.",
            "checklist": {"scope_ok": True, "no_conflict": True, "letter_previewed": True}}
# Worked example (spec §19): ATS résumé screening → inherent 76, maturity 2.25, residual 58.2, final High
ATS_ANSWERS = {"3.3.02": "human_assisted", "3.3.05s": "4", "3.3.07": "yes", "5.1.02": "no", "5.1.03": "yes", "5.1.04": "no", "3.3.06": "yes", "3.3.04": 2000,
               "3.2.01": ["ml"], "3.1.10": "client_facing_decision", "6.2.01": "no", "5.1a.05": "high"}
ATS_DOMAINS = {"governance": 3, "data": 2, "model": 2, "bias": 1, "oversight": 3, "security": 3, "incident": 2, "vendor_risk": 2}
SYSTEM_ANSWERS = {
    "SYS-001": ATS_ANSWERS,
    "SYS-002": {"3.3.02": "alert_only", "3.3.05s": "2", "3.3.07": "no", "5.1.02": "no", "5.1.03": "no", "5.1.04": "no", "3.3.06": "yes", "3.3.04": 4000, "3.2.01": ["ml"],
                "3.1.10": "internal_only", "6.2.01": "yes"},
    "SYS-003": {"3.3.02": "human_assisted", "3.3.05s": "2", "3.3.07": "no", "5.1.02": "no", "5.1.03": "yes", "5.1.04": "no", "3.3.06": "no", "3.3.04": 600, "3.2.01": ["genai_llm"],
                "3.1.10": "internal_and_external"},
    "SYS-004": {"3.3.02": "fully_automated", "3.3.05s": "2", "3.3.07": "no", "5.1.02": "no", "5.1.03": "yes", "5.1.04": "no", "3.3.06": "no", "3.3.04": 9000, "3.2.01": ["genai_llm", "nlp"],
                "3.1.10": "internal_and_external"},
}
SYSTEM_DOMAINS = {
    "SYS-001": ATS_DOMAINS,
    "SYS-002": {"governance": 3, "data": 3, "model": 4, "bias": 3, "oversight": 3, "security": 3, "incident": 2, "vendor_risk": 3},
    "SYS-003": {"governance": 3, "data": 2, "model": 2, "bias": 2, "oversight": 3, "security": 3, "incident": 2, "vendor_risk": 2},
    "SYS-004": {"governance": 3, "data": 2, "model": 2, "bias": 2, "oversight": 2, "security": 3, "incident": 2, "vendor_risk": 2},
}


class DemoError(RuntimeError):
    pass


class Demo:
    def __init__(self, db: Session, settings, client: TestClient):
        self.db, self.settings, self.c = db, settings, client
        self.today = date.today()

    # ---- plumbing
    def d(self, days: int) -> str:
        return (self.today + timedelta(days=days)).isoformat()

    def as_(self, user):
        from app.auth.sessions import COOKIE_NAME, create_session
        from app.core.clock import utcnow

        if user.terms_accepted_at is None:
            user.terms_accepted_at = utcnow()
        s, raw = create_session(self.db, user, self.settings, mfa_passed=True)
        self.db.commit()
        self.c.cookies.set(COOKIE_NAME, raw)
        self.c.headers["X-CSRF-Token"] = s.csrf_token
        return self

    def call(self, method: str, path: str, body=None, ok=(200,)):
        r = self.c.request(method, f"/api/v1{path}", json=body)
        if r.status_code not in ok:
            raise DemoError(f"{method} {path} → {r.status_code}: {r.text[:800]}")
        self.db.expire_all()
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None, ok=(200,)):
        return self.call("POST", path, body if body is not None else {}, ok)

    def put(self, path, body, ok=(200,)):
        return self.call("PUT", path, body, ok)

    def patch(self, path, body):
        return self.call("PATCH", path, body)

    def user(self, email: str):
        from app.tenancy.models import User

        u = self.db.scalar(select(User).where(User.email == email.lower()))
        if u is None:
            raise DemoError(f"No user {email}")
        return u

    def activate(self, org_id: str) -> None:
        """Demo users skip the invitation e-mail: active, with the demo password."""
        from app.auth.passwords import hash_password
        from app.core.clock import utcnow
        from app.tenancy.models import User

        pw = hash_password(DEMO_PASSWORD)
        for u in self.db.scalars(select(User).where(User.organization_id == org_id, User.deleted_at.is_(None))):
            if u.status == "invited":
                u.status, u.password_hash = "active", pw
            if u.terms_accepted_at is None:
                u.terms_accepted_at = utcnow()
        self.db.commit()

    def engagement(self, cid: str):
        from app.engagements.models import Engagement
        from app.tenancy.models import Organization
        from app.tenancy.people import current_engagement

        e = current_engagement(self.db, self.db.get(Organization, cid))
        return self.db.get(Engagement, e.id) if e else None

    def stage(self, cid: str) -> int:
        self.db.expire_all()
        return self.engagement(cid).stage

    def expect_stage(self, cid: str, n: int) -> None:
        if self.stage(cid) < n:
            from app.engagements.gates import gate_status

            raise DemoError(f"Expected stage {n}, still at {self.stage(cid)}: {gate_status(self.db, self.engagement(cid)).unmet}")

    def advance(self, cid: str, actor_email: str = "auditor1@futran.demo") -> None:
        """Move on if the gate is met (most gates advance on their own; a few stages are advanced by the team)."""
        from app.engagements.gates import gate_status

        e = self.engagement(cid)
        if e.status in ("initiated", "in_progress") and gate_status(self.db, e).ready:
            self.as_(self.user(actor_email)).post(f"/engagements/{e.id}/advance")

    # ---- Futran
    def futran_staff(self):
        from app.auth.passwords import hash_password
        from app.cli import _futran_org
        from app.tenancy.models import User
        from app.tenancy.service import assign_role, create_user

        org = _futran_org(self.db)
        pw = hash_password(DEMO_PASSWORD)
        for name, email, role, title in FUTRAN_STAFF:
            u = self.db.scalar(select(User).where(User.email == email)) or create_user(self.db, org, name=name, email=email, job_title=title)
            u.password_hash, u.status, u.mfa_enabled = pw, "active", False
            assign_role(self.db, u, role)
        self.db.commit()

    # ---- the wizard (screens 3–8)
    def new_client(self, company: dict, locations: list[dict], scope: dict, contacts: dict, team: list[tuple[str, str]], keep=None) -> str:
        self.as_(self.user("auditor1@futran.demo"))
        cid = self.post("/clients")["client_id"]
        self.put(f"/clients/{cid}/wizard/company", company)
        self.put(f"/clients/{cid}/wizard/locations", {"locations": locations})
        sugg = self.get(f"/clients/{cid}/suggestions")
        reqs = [s for s in sugg if s["prechecked"] or (keep and keep(s))]
        self.put(f"/clients/{cid}/wizard/requirements", {"requirements": [{"regulation_id": s["regulation_id"], "label": s["label"], "source": s["source"], "reason_text": s["reason"]} for s in reqs]})
        scope = scope | {"team": [{"user_id": self.user(email).id, "role": role, "conflict_confirmed": True} for email, role in team]}
        self.put(f"/clients/{cid}/wizard/scope", scope)
        self.put(f"/clients/{cid}/wizard/contacts", contacts)
        return cid

    def approve_and_sign_letter(self, cid: str, caico_email: str) -> None:
        from app.signoffs.models import SignOff

        self.as_(self.user("auditor1@futran.demo")).post(f"/clients/{cid}/submit")
        self.as_(self.user("chief@futran.demo"))
        self.get(f"/clients/{cid}/package")
        self.post(f"/clients/{cid}/approve", APPROVAL)
        self.activate(cid)
        e = self.engagement(cid)
        so = self.db.scalar(select(SignOff).where(SignOff.engagement_id == e.id, SignOff.number == 1))
        caico = self.user(caico_email)
        self.as_(caico).post(f"/signoffs/{so.id}/sign", {"typed_name": caico.name})
        chief = self.user("chief@futran.demo")
        self.as_(chief).post(f"/signoffs/{so.id}/sign", {"typed_name": chief.name})
        self.expect_stage(cid, 2)

    def setup_people(self, cid: str, admin_email: str, depts: list[str], users: list[tuple[str, str, str, str, str | None]]) -> None:
        """users: (first, last, email, role, department)."""
        self.as_(self.user(admin_email))
        from app.tenancy.models import Department

        have = {d.name for d in self.db.scalars(select(Department).where(Department.organization_id == cid, Department.deleted_at.is_(None)))}
        for d in depts:
            if d not in have:
                self.post(f"/clients/{cid}/departments", {"name": d})
        for first, last, email, role, dept in users:
            self.post(f"/clients/{cid}/users", {"first_name": first, "last_name": last, "email": email, "job_title": "", "department": dept, "role": role})
        self.activate(cid)
        self.post(f"/clients/{cid}/departments/confirm")
        self.advance(cid)
        self.expect_stage(cid, 3)


def _people_titles(db: Session, titles: dict[str, str]) -> None:
    from app.tenancy.models import User

    for email, title in titles.items():
        u = db.scalar(select(User).where(User.email == email))
        if u is not None:
            u.job_title = title
    db.commit()


# ---- ABC Corp
ABC = "abccorp.example"


def abc(demo: Demo, until_stage6: bool = False) -> str:
    """ABC Corp from draft to completed; with until_stage6, stop when every finding is approved (sign-off 5 not sent)."""
    m = demo
    cid = m.new_client(
        company={"legal_name": "ABC Corp Inc.", "trading_name": "ABC Corp", "industry": "staffing", "employee_band": "250-999", "hq_street": "350 Fifth Avenue", "hq_city": "New York",
                 "hq_state": "US-NY", "hq_postal_code": "10118", "hq_country": "US", "primary_jurisdictions": ["US"], "ai_systems_in_scope_count": 4,
                 "engagement_reason": "AI screening of job applicants and growing use of generative AI across sales and finance"},
        locations=[{"site_name": "Headquarters", "street": "350 Fifth Avenue", "city": "New York", "subdivision_code": "US-NY", "country_code": "US", "employees_at_site": 420, "in_scope": True},
                   {"site_name": "Chicago office", "street": "233 South Wacker Drive", "city": "Chicago", "subdivision_code": "US-IL", "country_code": "US", "employees_at_site": 160, "in_scope": True},
                   {"site_name": "Remote staff", "country_code": "US", "employees_at_site": 75, "in_scope": True}],
        scope={"type": "initial_assessment", "period_start": f"{m.today.year}-01-01", "period_end": f"{m.today.year}-12-31", "fieldwork_start": m.d(14), "letter_due": m.d(7),
               "draft_report_target": m.d(60), "final_report_target": m.d(90), "frameworks": ["nist_ai_rmf", "iso_42001"], "business_processes": "Candidate screening and ranking; invoice review; sales proposals; customer support",
               "data_environments": ["production"], "geographic_scope": "United States (New York, Illinois, remote staff)",
               "planned_systems": ["ATS résumé screening", "Invoice anomaly detection", "Sales proposal assistant", "Customer support chatbot"], "departments": ["HR", "Finance", "Sales & Marketing"]},
        contacts={"caico": {"name": "Maria Lopez", "title": "Chief AI Compliance Officer", "email": f"maria.lopez@{ABC}"},
                  "client_admin": {"same_as_caico": False, "name": "Sam Okafor", "title": "IT Manager", "email": f"sam.okafor@{ABC}"},
                  "exec_sponsor": {"name": "Robert Chen", "title": "Chief Operating Officer", "email": f"robert.chen@{ABC}"},
                  "dpo": {"name": "Daniel Kim", "title": "Data Protection Officer", "email": f"daniel.kim@{ABC}"}, "project_lead": {"same_as_caico": True}},
        team=[("chief@futran.demo", "chief_auditor"), ("em@futran.demo", "engagement_manager"), ("auditor1@futran.demo", "auditor"), ("qa@futran.demo", "qa_reviewer")])
    m.approve_and_sign_letter(cid, f"maria.lopez@{ABC}")
    m.setup_people(cid, f"sam.okafor@{ABC}", ["HR", "Finance", "Sales & Marketing"], [
        ("Priya", "Shah", f"priya.shah@{ABC}", "dept_compliance_lead", "HR"),
        ("Grace", "Liu", f"grace.liu@{ABC}", "dept_compliance_lead", "Finance"),
        ("Marco", "Diaz", f"marco.diaz@{ABC}", "dept_compliance_lead", "Sales & Marketing"),
        ("Tom", "Reyes", f"tom.reyes@{ABC}", "contributor", "HR"),
        ("Lee", "Park", f"lee.park@{ABC}", "contributor", "HR"),
        ("Nina", "Patel", f"nina.patel@{ABC}", "contributor", "Finance"),
        ("Owen", "Hart", f"owen.hart@{ABC}", "contributor", "Sales & Marketing"),
        ("Daniel", "Kim", f"daniel.kim@{ABC}", "dpo", None),
        ("Robert", "Chen", f"robert.chen@{ABC}", "exec_sponsor", None),
    ])
    _people_titles(m.db, {f"priya.shah@{ABC}": "Head of HR", f"grace.liu@{ABC}": "Finance Director", f"marco.diaz@{ABC}": "VP Sales and Marketing", f"tom.reyes@{ABC}": "Recruiter",
                          f"lee.park@{ABC}": "HR Systems Lead", f"nina.patel@{ABC}": "Accounts Payable Lead", f"owen.hart@{ABC}": "Sales Operations Manager",
                          f"daniel.kim@{ABC}": "Data Protection Officer", f"robert.chen@{ABC}": "Chief Operating Officer"})
    depts = _abc_discovery(m, cid)
    _abc_client_review(m, cid, depts)
    _abc_fieldwork(m, cid, depts)
    if not until_stage6:
        _abc_report_and_close(m, cid)
    return cid


def _abc_discovery(m: Demo, cid: str) -> dict:
    from app.tenancy.models import Department

    maria = m.user(f"maria.lopez@{ABC}")
    m.as_(maria)
    # governance structure: a committee in place, the AI use policy promised (a commitment), the rest not applicable
    gov = m.get(f"/clients/{cid}/governance")
    for item in gov["items"]:
        if item["status"] != "unanswered":
            continue
        label = (item.get("name") or item.get("title") or "").lower()
        if "governance committee" in label:
            m.put(f"/governance/items/{item['id']}", {"status": "in_place", "names": [{"name": "Maria Lopez", "title": "Chair"}, {"name": "Robert Chen", "title": "Member"}], "chair": "Maria Lopez"})
        elif "acceptable use" in label or "use policy" in label:
            m.put(f"/governance/items/{item['id']}", {"status": "planned", "target_date": m.d(45), "interim_owner": "Maria Lopez"})
        else:
            m.put(f"/governance/items/{item['id']}", {"status": "not_applicable", "na_reason": "Covered by the AI governance committee for now."})
    m.post(f"/clients/{cid}/governance/submit", {"accuracy_confirmed": True})
    # attestation campaign: staff say what they use
    depts = {d.name: d.id for d in m.db.scalars(select(Department).where(Department.organization_id == cid, Department.deleted_at.is_(None)))}
    m.post("/me/initiation/items/notice/done")
    link = m.post(f"/clients/{cid}/attestation/campaigns", {"department_ids": list(depts.values()), "closes_at": m.d(10) + "T17:00:00", "policy_version": "1.0"})["link"]
    token = link.rsplit("/", 1)[1]
    staff = [("Sam Lee", "HR", "chatgpt", "personal_free", ["writing"], ["client"]), ("Ana Diaz", "HR", "chatgpt", "personal_free", ["writing"], ["client"]),
             ("Ben Ortiz", "Finance", "copilot", "company", ["analysis"], ["confidential"]), ("Carla Gomez", "Sales & Marketing", "copilot", "company", ["writing"], ["client"]),
             ("Dev Shah", "Sales & Marketing", "chatgpt", "personal_paid", ["writing"], ["none"])]
    for name, dept, tool, acct, purposes, data in staff:
        m.c.cookies.clear()
        m.post(f"/public/attest/{token}", {"respondent_name": name, "respondent_email": None, "department_id": depts[dept], "uses_ai": True,
                                            "tools_declared": [{"tool": tool, "account_type": acct}], "purposes": purposes, "data_entered": data, "policy_acknowledged": True})
    m.as_(maria).post(f"/clients/{cid}/attestation/close")
    # AI tools and use cases, submitted by contributors and approved by their Department Leads
    def tool(vendor, product, account_type, training="no"):
        from app.inventory.service import _find_tool

        found = _find_tool(m.db, cid, vendor, product, account_type)
        if found is not None:
            return found.id
        return m.post(f"/clients/{cid}/tools", {"vendor": vendor, "product": product, "account_type": account_type, "training_on_inputs": training})["id"]

    tools = {"screenrank": tool("ScreenRank", "ScreenRank ATS", "enterprise"), "copilot": tool("Microsoft", "Copilot", "enterprise"), "chatgpt": tool("OpenAI", "ChatGPT", "personal_free", "unknown"),
             "anomaly": tool("ABC Corp", "Invoice anomaly model", "enterprise"), "zendesk": tool("Zendesk", "Answer Bot", "enterprise")}
    cases = [
        (f"tom.reyes@{ABC}", f"priya.shah@{ABC}", {"name": "Résumé screening for NYC roles", "department_id": depts["HR"], "tool_ids": [tools["screenrank"]], "purpose": "Ranks applicants for New York roles before recruiter review.",
         "data_categories": ["pii"], "decision_impact": "consequential", "usage": [{"role_name": "Recruiter", "headcount": 6, "frequency": "daily"}],
         "named_users": [{"person_name": "Lee Park", "email": f"lee.park@{ABC}", "role_name": "HR Systems Lead", "oversight_role": "Reviews the ranked list before interviews"}]}),
        (f"tom.reyes@{ABC}", f"priya.shah@{ABC}", {"name": "Drafting job adverts with ChatGPT", "department_id": depts["HR"], "tool_ids": [tools["chatgpt"]], "purpose": "Recruiters draft job adverts and outreach messages.",
         "data_categories": ["client"], "decision_impact": "none", "usage": [{"role_name": "Recruiter", "headcount": 4, "frequency": "weekly"}],
         "named_users": [{"person_name": "Tom Reyes", "email": f"tom.reyes@{ABC}", "role_name": "Recruiter"}]}),
        (f"nina.patel@{ABC}", f"grace.liu@{ABC}", {"name": "Invoice anomaly detection", "department_id": depts["Finance"], "tool_ids": [tools["anomaly"]], "purpose": "Flags unusual supplier invoices for review before payment.",
         "data_categories": ["confidential"], "decision_impact": "informs", "usage": [{"role_name": "Accounts payable clerk", "headcount": 5, "frequency": "daily"}],
         "named_users": [{"person_name": "Nina Patel", "email": f"nina.patel@{ABC}", "role_name": "Accounts Payable Lead"}]}),
        (f"owen.hart@{ABC}", f"marco.diaz@{ABC}", {"name": "Sales proposal drafting", "department_id": depts["Sales & Marketing"], "tool_ids": [tools["copilot"]], "purpose": "Drafts client proposals from CRM notes.",
         "data_categories": ["client"], "decision_impact": "none", "usage": [{"role_name": "Account executive", "headcount": 12, "frequency": "daily"}],
         "named_users": [{"person_name": "Owen Hart", "email": f"owen.hart@{ABC}", "role_name": "Sales Operations Manager"}]}),
        (f"owen.hart@{ABC}", f"marco.diaz@{ABC}", {"name": "Customer support chatbot", "department_id": depts["Sales & Marketing"], "tool_ids": [tools["zendesk"]], "purpose": "Answers customer questions on the website and hands off to agents.",
         "data_categories": ["pii"], "decision_impact": "informs", "usage": [{"role_name": "Support agent", "headcount": 8, "frequency": "daily"}],
         "named_users": [{"person_name": "Owen Hart", "email": f"owen.hart@{ABC}", "role_name": "Sales Operations Manager"}]}),
        (f"nina.patel@{ABC}", f"grace.liu@{ABC}", {"name": "Meeting notes with Copilot", "department_id": depts["Finance"], "tool_ids": [tools["copilot"]], "purpose": "Summarises internal meetings.",
         "data_categories": ["none"], "decision_impact": "none", "usage": [{"role_name": "Finance team", "headcount": 10, "frequency": "weekly"}], "named_users": []}),
    ]
    for author, lead, body in cases:
        uc = m.as_(m.user(author)).post(f"/clients/{cid}/use-cases", body)
        m.post(f"/use-cases/{uc['id']}/submit")
        m.as_(m.user(lead)).post(f"/use-cases/{uc['id']}/review", {"approve": True})
    m.advance(cid)
    m.expect_stage(cid, 4)
    return depts


def _abc_client_review(m: Demo, cid: str, depts: dict) -> None:
    maria, dpo, sponsor = m.user(f"maria.lopez@{ABC}"), m.user(f"daniel.kim@{ABC}"), m.user(f"robert.chen@{ABC}")
    leads = {"HR": f"priya.shah@{ABC}", "Finance": f"grace.liu@{ABC}", "Sales & Marketing": f"marco.diaz@{ABC}"}
    for name, dept_id in depts.items():
        so = m.as_(maria).post(f"/clients/{cid}/signoffs/2/submit", {"scope_ref": dept_id})
        lead = m.user(leads[name])
        m.as_(lead).post(f"/signoffs/{so['id']}/sign", {"typed_name": lead.name})
    priya = m.user(leads["HR"])
    so3 = m.as_(priya).post(f"/clients/{cid}/signoffs/3/submit")
    m.as_(dpo).post(f"/signoffs/{so3['id']}/sign", {"typed_name": dpo.name})
    m.as_(maria).post(f"/signoffs/{so3['id']}/sign", {"typed_name": maria.name})
    so4 = m.as_(maria).post(f"/clients/{cid}/signoffs/4/submit")
    m.as_(dpo).post(f"/signoffs/{so4['id']}/sign", {"typed_name": dpo.name})
    m.as_(sponsor).post(f"/signoffs/{so4['id']}/sign", {"typed_name": sponsor.name})
    m.expect_stage(cid, 5)


def _default_value(q):
    """A plausible answer for a question the demo does not set on purpose."""
    opts = [str(o["value"] if isinstance(o, dict) else o) for o in (q.options or [])]
    t = q.type
    if t in ("yes_no", "yes_no_unknown", "single"):
        for pref in ("yes", "in_place", "documented", "annually", "quarterly"):
            if pref in opts:
                return pref
        return opts[0] if opts else None
    if t == "multi":
        return opts[:1]
    if t == "date":
        return (date.today() - timedelta(days=120)).isoformat()
    if t in ("number", "percent"):
        return 90 if t == "percent" else 12
    if t == "person":
        return {"name": "Maria Lopez", "title": "Chief AI Compliance Officer"}
    return "Documented in the client's AI governance procedures; evidence reviewed during fieldwork."


def _answer_all(m: Demo, e, s, fixed: dict) -> None:
    from app.questionnaire.service import Target, _responses, questions_for, save_response

    aud = m.user("auditor1@futran.demo")
    t = Target(e, s)
    src = {"status": "answered", "source_person_name": "Lee Park", "source_person_title": "HR Systems Lead"}
    for code, v in fixed.items():
        save_response(m.db, aud, t, code, {"value": v, **src}, futran=True)
    for _ in range(6):  # answers open new questions; repeat until every required one is answered
        rs = _responses(m.db, t)
        todo = [q for q in questions_for(m.db, t, True) if q.required and (q.id not in rs or rs[q.id].status == "unanswered")]
        if not todo:
            break
        for q in todo:
            v = _default_value(q)
            body = {"value": v, **src} if v not in (None, [], "") else {"status": "na", "na_reason": "Not relevant to this system."}
            save_response(m.db, aud, t, q.code, body, futran=True)
    m.db.commit()


def _abc_fieldwork(m: Demo, cid: str, depts: dict) -> None:
    from app.findings.models import DraftFindingLink, Finding
    from app.inventory.models import UseCase
    from app.scoring import service as scoring
    from app.systems.service import systems_for

    e = m.engagement(cid)
    ucs = {u.name: u for u in m.db.scalars(select(UseCase).where(UseCase.engagement_id == e.id, UseCase.deleted_at.is_(None)))}
    aud = m.user("auditor1@futran.demo")
    m.as_(aud)
    m.post(f"/use-cases/{ucs['Résumé screening for NYC roles'].id}/final-tier", {"tier": 3, "rationale": "Ranks applicants for New York roles: an AEDT under Local Law 144.", "aedt_determination": "in_scope"})
    systems = {s.reference_id: s for s in systems_for(m.db, e)}
    plan = {
        "SYS-001": {"name": "ATS résumé screening", "built_by": "vendor", "department_id": depts["HR"], "use_case_ids": [ucs["Résumé screening for NYC roles"].id]},
        "SYS-002": {"name": "Invoice anomaly detection", "built_by": "in_house", "department_id": depts["Finance"], "use_case_ids": [ucs["Invoice anomaly detection"].id]},
        "SYS-003": {"name": "Sales proposal assistant", "built_by": "vendor", "department_id": depts["Sales & Marketing"], "use_case_ids": [ucs["Sales proposal drafting"].id]},
        "SYS-004": {"name": "Customer support chatbot", "built_by": "vendor", "department_id": depts["Sales & Marketing"], "use_case_ids": [ucs["Customer support chatbot"].id]},
    }
    for ref, body in plan.items():
        m.patch(f"/systems/{systems[ref].id}", body)
    e = m.engagement(cid)
    for ref in plan:
        s = m.db.get(type(systems[ref]), systems[ref].id)
        _answer_all(m, e, s, SYSTEM_ANSWERS[ref])
    # auto-drafted findings: confirm the ones that stand
    for link in m.db.scalars(select(DraftFindingLink).join(Finding, Finding.id == DraftFindingLink.finding_id).where(Finding.engagement_id == e.id, DraftFindingLink.dismissed_at.is_(None))):
        f = m.db.get(Finding, link.finding_id)
        if f.status == "draft" and f.deleted_at is None and f.confirmed_at is None:
            m.post(f"/draft-findings/{link.id}/confirm", ok=(200, 409))
    manual = [
        {"title": "Recruiters use personal ChatGPT accounts with applicant data", "severity": "medium", "template_section": "4.3", "proposed_owner": "Head of HR",
         "description": "Two of five HR staff who attested use a personal, free ChatGPT account and paste candidate details into it. The company has no contract with OpenAI covering this data.",
         "recommended_remediation": "Move recruiters to the company Copilot licence and block personal AI accounts on company devices."},
        {"title": "No written AI acceptable use policy", "severity": "medium", "template_section": "4.1", "proposed_owner": "Chief AI Compliance Officer",
         "description": "ABC Corp has an AI governance committee but no approved policy telling staff which AI tools they may use and with what data.",
         "recommended_remediation": "Approve and publish an AI acceptable use policy, then ask every employee to acknowledge it."},
        {"title": "Chatbot conversations are not reviewed for quality or bias", "severity": "low", "template_section": "8.2", "proposed_owner": "VP Sales and Marketing",
         "description": "Nobody samples the support chatbot's answers. Errors or unfair treatment of customers would go unnoticed.",
         "recommended_remediation": "Review a monthly sample of chatbot conversations and record the outcome."},
        {"title": "Invoice model has a documented validation process", "severity": "observation", "template_section": "6.3", "proposed_owner": "Finance Director",
         "description": "The in-house invoice model is validated each quarter against confirmed fraud cases. This is good practice worth extending to other systems.",
         "recommended_remediation": "Use the Finance validation approach as the template for other in-house models."},
    ]
    for body in manual:
        m.post(f"/clients/{cid}/findings", body)
    rows = m.get(f"/clients/{cid}/findings")["findings"]
    for f in rows:
        if f["status"] in ("draft", "returned"):
            m.patch(f"/findings/{f['id']}", {"proposed_owner": f.get("proposed_owner") or "Head of HR"})
            m.post(f"/findings/{f['id']}/submit")
    chief = m.user("chief@futran.demo")
    m.as_(chief)
    for f in m.get(f"/clients/{cid}/findings")["findings"]:
        if f["status"] == "submitted":
            m.post(f"/findings/{f['id']}/approve", {"comment": "Clear and supported by the evidence."})
    # the Lead Auditor sets the final domain scores (SYS-001 reproduces the worked example)
    for ref in plan:
        s = systems[ref]
        latest = scoring.latest(m.db, s)
        target = SYSTEM_DOMAINS[ref]
        for d, v in target.items():
            prop = latest.domain_scores_proposed.get(d)
            body = {"score": v} if prop is not None and abs(prop - v) <= 1 else {"score": v, "rationale": "Set from interviews and the evidence reviewed."}
            m.put(f"/systems/{s.id}/score/domains/{d}", body)
    m.advance(cid)
    m.expect_stage(cid, 6)


def _abc_report_and_close(m: Demo, cid: str) -> None:
    from app.reports.models import Report

    aud, chief, em, qa = (m.user(x) for x in ("auditor1@futran.demo", "chief@futran.demo", "em@futran.demo", "qa@futran.demo"))
    maria, sponsor, priya = m.user(f"maria.lopez@{ABC}"), m.user(f"robert.chen@{ABC}"), m.user(f"priya.shah@{ABC}")
    so5 = m.as_(aud).post(f"/clients/{cid}/signoffs/5/submit")
    m.as_(chief).post(f"/signoffs/{so5['id']}/sign", {"typed_name": chief.name})
    findings = m.as_(aud).get(f"/clients/{cid}/findings")["findings"]
    top = next((f for f in findings if f["severity"] in ("critical", "high")), findings[0])
    m.put(f"/clients/{cid}/report/summary", {
        "most_significant_finding_id": top["id"], "most_significant_text": "The résumé screening tool ranks New York applicants without a bias audit in the past year, which Local Law 144 requires before use.",
        "strengths": "An AI governance committee chaired by the Chief AI Compliance Officer meets monthly, and Finance validates its in-house invoice model every quarter.",
        "immediate_actions": "Commission an independent bias audit of the résumé screening tool and publish its summary before further use on New York roles.",
        "narrative": "Governance is defined but not yet measured. The main exposure is in hiring, where one high-risk tool lacks a bias audit."})
    for body in (
        {"action": "Commission an independent bias audit of the résumé screening tool and publish the summary", "owner": "Head of HR", "priority": "high", "target_date": m.d(30), "how_futran_can_help": "Futran runs LL144 bias audits and drafts the public summary."},
        {"action": "Approve and roll out an AI acceptable use policy", "owner": "Chief AI Compliance Officer", "priority": "medium", "target_date": m.d(60), "how_futran_can_help": "Policy template and staff briefing."},
        {"action": "Start monthly quality and bias reviews of chatbot conversations", "owner": "VP Sales and Marketing", "priority": "low", "target_date": m.d(120), "how_futran_can_help": "Review checklist and sampling method."},
    ):
        m.post(f"/clients/{cid}/report/roadmap", body | {"finding_ids": []})
    m.post(f"/clients/{cid}/report/generate", {"version": "v0.1"})
    rid = m.post(f"/clients/{cid}/report/generate", {"version": "v0.2"})["id"]
    for user, kind in ((chief, "lead_auditor"), (em, "engagement_manager"), (qa, "quality_reviewer")):
        m.as_(user).post(f"/reports/{rid}/declarations", {"kind": kind, "typed_name": user.name})
    m.as_(em).post(f"/clients/{cid}/report/release")
    m.expect_stage(cid, 7)
    # management responses: the CAICO answers organization-wide findings, Department Leads their own
    m.as_(maria)
    owners = {"Head of HR": priya, "Chief AI Compliance Officer": maria, "VP Sales and Marketing": m.user(f"marco.diaz@{ABC}"), "Finance Director": m.user(f"grace.liu@{ABC}")}
    for r in m.get(f"/clients/{cid}/responses")["responses"]:
        f = r["finding"]
        owner = owners.get(next((x["proposed_owner"] for x in findings if x["id"] == f["id"]), ""), priya)
        m.put(f"/findings/{f['id']}/response", {"response": "agree", "planned_action": f"{f['recommended_remediation'] or 'Agreed action.'}", "owner_user_id": owner.id, "due_date": m.d(45)})
    m.as_(aud)
    for r in m.get(f"/clients/{cid}/responses")["responses"]:
        m.post(f"/responses/{r['id']}/adequacy", {"adequate": True, "note": "The action addresses the cause."})
    so6 = m.as_(priya).post(f"/clients/{cid}/signoffs/6/submit")
    m.as_(maria).post(f"/signoffs/{so6['id']}/sign", {"typed_name": maria.name})
    m.as_(sponsor).post(f"/signoffs/{so6['id']}/sign", {"typed_name": sponsor.name})
    m.expect_stage(cid, 8)
    # final report (sign-off 7), the client's acknowledgement and the LL144 public summary (sign-off 8)
    so7 = m.as_(aud).post(f"/clients/{cid}/report/final")["sign_off"]
    m.as_(chief).post(f"/signoffs/{so7['id']}/sign", {"typed_name": chief.name})
    m.as_(maria).post(f"/clients/{cid}/report/acknowledge", {"typed_name": maria.name, "commitment": "plan"})
    if m.as_(aud).get(f"/clients/{cid}/report")["public_summary"]["required"]:
        m.put(f"/clients/{cid}/public-summary", {"tool_name": "ScreenRank ATS (résumé screening)", "audit_date": m.d(-3), "distribution_date": m.d(10),
                                                 "data_source": "Historical applicant data from ScreenRank for New York roles, January to June.", "unknown_category_count": 112,
                                                 "impact_ratios": [{"category": "Sex", "group": "Female", "selection_rate": 0.41, "impact_ratio": 0.91},
                                                                   {"category": "Sex", "group": "Male", "selection_rate": 0.45, "impact_ratio": 1.0},
                                                                   {"category": "Race/ethnicity", "group": "Hispanic or Latino", "selection_rate": 0.38, "impact_ratio": 0.84},
                                                                   {"category": "Race/ethnicity", "group": "White", "selection_rate": 0.45, "impact_ratio": 1.0}]})
        so8 = m.post(f"/clients/{cid}/signoffs/8/submit")
        m.as_(maria).post(f"/signoffs/{so8['id']}/sign", {"typed_name": maria.name})
    m.expect_stage(cid, 9)
    # remediation: owners mark done, the auditor verifies, the Chief Auditor closes
    items = m.as_(aud).get(f"/clients/{cid}/remediation")["items"]
    for it in items:
        owner = next((u for u in owners.values() if u.name == it["owner"]), maria)
        m.as_(owner).post(f"/remediation/{it['id']}/done", {"note": "Done; evidence uploaded to Documents."})
    m.as_(aud)
    for it in items:
        m.post(f"/remediation/{it['id']}/verify", {"note": "Evidence reviewed and accepted."})
    m.as_(chief)
    for it in items:
        m.post(f"/remediation/{it['id']}/close")
    from app.engagements.models import Engagement

    done = m.db.scalar(select(Engagement).where(Engagement.client_id == cid, Engagement.status == "completed"))
    if done is None:
        raise DemoError("ABC Corp did not reach completed.")
    assert m.db.scalar(select(Report).where(Report.engagement_id == done.id, Report.version == "v1.1", Report.status == "final")) is not None


def northwind_pending(m: Demo) -> str:
    """A new client drafted by the auditor and waiting for the Chief Auditor, so the approval screen has data."""
    cid = m.new_client(
        company={"legal_name": "Northwind Logistics LLC", "trading_name": "Northwind Logistics", "industry": "other", "employee_band": "1000+", "hq_street": "1 Harbor Way", "hq_city": "Newark",
                 "hq_state": "US-NJ", "hq_postal_code": "07102", "hq_country": "US", "primary_jurisdictions": ["US"], "ai_systems_in_scope_count": 2,
                 "engagement_reason": "Route optimisation and driver scheduling now use AI; the board asked for an independent review"},
        locations=[{"site_name": "Headquarters", "street": "1 Harbor Way", "city": "Newark", "subdivision_code": "US-NJ", "country_code": "US", "employees_at_site": 900, "in_scope": True},
                   {"site_name": "Dallas hub", "city": "Dallas", "subdivision_code": "US-TX", "country_code": "US", "employees_at_site": 400, "in_scope": True}],
        scope={"type": "initial_assessment", "period_start": f"{m.today.year}-01-01", "period_end": f"{m.today.year}-12-31", "fieldwork_start": m.d(30), "letter_due": m.d(10),
               "draft_report_target": m.d(80), "final_report_target": m.d(110), "frameworks": ["nist_ai_rmf"], "business_processes": "Route optimisation; driver scheduling",
               "data_environments": ["production"], "geographic_scope": "United States (New Jersey, Texas)", "planned_systems": ["Route optimiser", "Driver scheduling assistant"],
               "departments": ["Operations", "People"]},
        contacts={"caico": {"name": "Hannah Ortiz", "title": "Chief Risk Officer", "email": "hannah.ortiz@northwind.example"}, "client_admin": {"same_as_caico": True},
                  "dpo": {"not_appointed": True}, "exec_sponsor": {"not_appointed": True}, "project_lead": {"same_as_caico": True}},
        team=[("chief@futran.demo", "chief_auditor"), ("em@futran.demo", "engagement_manager"), ("auditor1@futran.demo", "auditor")])
    m.as_(m.user("auditor1@futran.demo")).post(f"/clients/{cid}/submit")
    return cid


# ---- Meridian GmbH (stage 3) and the internal client (stage 2)
def meridian(m: Demo) -> str:
    keep = lambda s: any(k in (s.get("label") or "") for k in ("EU AI Act", "GDPR", "General Data Protection", "Digital Personal Data Protection", "DPDP"))  # noqa: E731
    cid = m.new_client(
        company={"legal_name": "Meridian Analytics GmbH", "trading_name": "Meridian GmbH", "industry": "bfsi", "employee_band": "250-999", "hq_street": "Friedrichstraße 68", "hq_city": "Berlin",
                 "hq_state": "DE-BE", "hq_postal_code": "10117", "hq_country": "DE", "primary_jurisdictions": ["DE", "IN"], "ai_systems_in_scope_count": 2,
                 "engagement_reason": "Readiness for the EU AI Act and India's DPDP Act across the Berlin and Bangalore teams"},
        locations=[{"site_name": "Berlin headquarters", "street": "Friedrichstraße 68", "city": "Berlin", "subdivision_code": "DE-BE", "country_code": "DE", "employees_at_site": 300, "in_scope": True},
                   {"site_name": "Bangalore engineering centre", "city": "Bengaluru", "subdivision_code": "IN-KA", "country_code": "IN", "employees_at_site": 220, "in_scope": True}],
        scope={"type": "initial_assessment", "period_start": f"{m.today.year}-01-01", "period_end": f"{m.today.year}-12-31", "fieldwork_start": m.d(30), "letter_due": m.d(7),
               "draft_report_target": m.d(75), "final_report_target": m.d(105), "frameworks": ["eu_ai_act", "gdpr", "dpdp"], "business_processes": "Credit risk scoring models; developer copilots",
               "data_environments": ["production"], "geographic_scope": "Germany and India", "planned_systems": ["Credit risk scoring model", "Developer copilot"], "departments": ["Data Science", "Engineering"]},
        contacts={"caico": {"name": "Katrin Vogel", "title": "Head of AI Compliance", "email": "katrin.vogel@meridian.example"}, "client_admin": {"same_as_caico": True},
                  "dpo": {"name": "Jonas Weber", "title": "Data Protection Officer", "email": "jonas.weber@meridian.example"}, "exec_sponsor": {"not_appointed": True}, "project_lead": {"same_as_caico": True}},
        team=[("chief@futran.demo", "chief_auditor"), ("em@futran.demo", "engagement_manager"), ("auditor1@futran.demo", "auditor"), ("auditor2@futran.demo", "auditor")], keep=keep)
    m.approve_and_sign_letter(cid, "katrin.vogel@meridian.example")
    m.setup_people(cid, "katrin.vogel@meridian.example", ["Data Science", "Engineering"], [
        ("Aarav", "Menon", "aarav.menon@meridian.example", "dept_compliance_lead", "Engineering"),
        ("Lena", "Fischer", "lena.fischer@meridian.example", "dept_compliance_lead", "Data Science"),
        ("Jonas", "Weber", "jonas.weber@meridian.example", "dpo", None),
    ])
    return cid


def internal(m: Demo) -> str:
    from app.tenancy.models import Organization

    cid = m.new_client(
        company={"legal_name": "Futran Solutions Inc.", "trading_name": "Futran Solutions (internal)", "industry": "other", "employee_band": "50-249", "hq_street": "100 Wood Avenue South",
                 "hq_city": "Edison", "hq_state": "US-NJ", "hq_postal_code": "08837", "hq_country": "US", "primary_jurisdictions": ["US"], "ai_systems_in_scope_count": 1,
                 "engagement_reason": "Futran audits its own use of AI before offering the service"},
        locations=[{"site_name": "Edison office", "street": "100 Wood Avenue South", "city": "Edison", "subdivision_code": "US-NJ", "country_code": "US", "employees_at_site": 80, "in_scope": True}],
        scope={"type": "initial_assessment", "period_start": f"{m.today.year}-01-01", "period_end": f"{m.today.year}-12-31", "fieldwork_start": m.d(21), "letter_due": m.d(7),
               "draft_report_target": m.d(60), "final_report_target": m.d(80), "frameworks": ["nist_ai_rmf"], "business_processes": "Proposal writing and audit fieldwork support",
               "data_environments": ["production"], "geographic_scope": "United States (New Jersey)", "planned_systems": ["Audit drafting assistant"], "departments": ["Delivery"]},
        contacts={"caico": {"name": "Hannah Cole", "title": "Head of Risk", "email": "hannah.cole@internal.futran.example"}, "client_admin": {"same_as_caico": True},
                  "dpo": {"not_appointed": True}, "exec_sponsor": {"not_appointed": True}, "project_lead": {"same_as_caico": True}},
        team=[("chief@futran.demo", "chief_auditor"), ("em@futran.demo", "engagement_manager"), ("auditor1@futran.demo", "auditor"), ("auditor2@futran.demo", "auditor")])
    org = m.db.get(Organization, cid)
    org.is_internal = True
    m.db.commit()
    m.approve_and_sign_letter(cid, "hannah.cole@internal.futran.example")
    return cid


def e2e_late(db: Session, settings) -> dict:
    """End-to-end test data: ABC Corp at stage 6 for the review-to-close journey, Meridian at stage 3 with an open
    attestation campaign and a named-user confirmation link for the phone checks. Returns the links."""
    import hashlib
    import secrets

    from app.core.clock import utcnow
    from app.inventory.models import NamedUser, NamedUserLink
    from app.main import create_app

    if not settings.test_mode:
        raise PermissionError("Test data can only be loaded while the platform is in test mode.")
    client = TestClient(create_app(settings.model_copy(update={"disable_scheduler": True}), engine=db.get_bind()))
    m = Demo(db, settings, client)
    try:
        m.futran_staff()
        abc_id = abc(m, until_stage6=True)
        mid = meridian(m)
        katrin, aarav = m.user("katrin.vogel@meridian.example"), m.user("aarav.menon@meridian.example")
        m.as_(katrin).post("/me/initiation/items/notice/done")
        from app.tenancy.models import Department

        depts = {d.name: d.id for d in db.scalars(select(Department).where(Department.organization_id == mid, Department.deleted_at.is_(None)))}
        attest = m.post(f"/clients/{mid}/attestation/campaigns", {"department_ids": list(depts.values()), "closes_at": m.d(10) + "T17:00:00", "policy_version": "1.0"})["link"]
        m.as_(aarav)
        tool = m.post(f"/clients/{mid}/tools", {"vendor": "GitHub", "product": "Copilot", "account_type": "personal_paid"})["id"]
        uc = m.post(f"/clients/{mid}/use-cases", {"name": "Code completion", "department_id": depts["Engineering"], "tool_ids": [tool], "purpose": "Suggests code in the IDE.", "data_categories": ["confidential"],
                                                   "decision_impact": "none", "usage": [{"role_name": "Developer", "headcount": 40, "frequency": "daily"}],
                                                   "named_users": [{"person_name": "Ravi Kumar", "email": "ravi.kumar@meridian.example", "role_name": "Developer"}]})
        m.post(f"/use-cases/{uc['id']}/submit")
        n = db.scalar(select(NamedUser).where(NamedUser.use_case_id == uc["id"], NamedUser.deleted_at.is_(None)))
        raw = secrets.token_urlsafe(32)  # a link the test can open; the e-mailed one is redacted in the outbox
        db.add(NamedUserLink(organization_id=mid, named_user_id=n.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), sent_at=utcnow(), expires_at=utcnow() + timedelta(days=14)))
        db.commit()
    finally:
        client.close()
    return {"abc": abc_id, "meridian": mid, "attest_link": attest, "confirm_link": f"/confirm/{raw}"}


def run(db: Session, settings, client: TestClient | None = None) -> dict:
    """Create the demo tenants. Refuses outside test mode. Returns the client ids."""
    from app.main import create_app

    if not settings.test_mode:
        raise PermissionError("Demo data can only be loaded while the platform is in test mode.")
    own = client is None
    if own:
        app_settings = settings.model_copy(update={"disable_scheduler": True})
        client = TestClient(create_app(app_settings, engine=db.get_bind()))
    m = Demo(db, settings, client)
    try:
        m.futran_staff()
        out = {"abc": abc(m)}
        out["northwind"] = northwind_pending(m)
        out["meridian"] = meridian(m)
        out["internal"] = internal(m)
    finally:
        client.cookies.clear()
        if own:
            client.close()
    db.commit()
    return out
