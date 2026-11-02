"""Demo data for WS-K (spec §21 F11, F13, F6, F15, F16; screens 29, 34, 35).

- A bias calculator run on ABC Corp's résumé screening system (SYS-001) on the January-to-June applicant data. The figures
  are the ones in ABC's published bias audit summary: Female 0.41 (impact ratio 0.91), Male 0.45 (1.00), Hispanic or
  Latino 0.38 (0.84, the lowest in every table), White 0.45 (1.00) and 112 people in the unknown category (18% of 622).
  Three Asian female applicants are under 2% of the data, so they are excluded from the impact ratios and reported.
- A GenAI guardrail test on the customer support chatbot (SYS-004) through the sandbox adapter, awaiting review.
- ABC's benchmarking consent, and seven demo peers for the comparison. Peers are organizations of type "demo_peer" named
  "Demo peer NN (demo data)": they never sign in, are not clients and appear in no client list. Their snapshots are
  written directly (no service: a peer exists only as the aggregate a signed audit would leave).
- ABC's own pre-fill on its completed engagement (the client's answers to the client questions, which the auditor's
  answers of record matched; the base demo records only the auditor's side), then the annual review started from that
  engagement, with its systems, the client's answers and evidence links carried forward. It stays a draft (the Chief
  Auditor reviews it in the wizard), so ABC's current engagement does not change.
- The heat map and lineage need nothing extra: they read ABC's scores, findings and remediation.
"""
from __future__ import annotations

from sqlalchemy import select

from app.demo.seed_demo import ABC, Demo, DemoError

# (sex, race/ethnicity as the client's file writes it) -> (applicants, selected)
APPLICANTS = {("Male", "White"): (374, 170), ("Female", "White"): (33, 15), ("Male", "Hispanic or Latino"): (50, 19), ("Female", "Hispanic or Latino"): (50, 19),
              ("Female", "Asian"): (3, 1)}
UNKNOWN = (112, 46)  # no sex or race/ethnicity recorded
DATA_SOURCE = "Historical applicant data from ScreenRank for New York roles, January to June."
PEERS = [  # bias is the domain the mockup highlights; ABC sits at 1.0 against a peer median of 2.5
    {"governance": 2.5, "data": 2.5, "model": 2.0, "bias": 2.5, "oversight": 3.0, "security": 2.0, "incident": 2.0, "vendor_risk": 2.0},
    {"governance": 2.0, "data": 3.0, "model": 2.5, "bias": 2.0, "oversight": 3.5, "security": 2.5, "incident": 1.5, "vendor_risk": 2.5},
    {"governance": 3.0, "data": 2.0, "model": 2.0, "bias": 3.0, "oversight": 2.5, "security": 1.5, "incident": 2.5, "vendor_risk": 1.5},
    {"governance": 2.5, "data": 2.5, "model": 3.0, "bias": 2.5, "oversight": 3.0, "security": 2.0, "incident": 2.0, "vendor_risk": 2.0},
    {"governance": 1.5, "data": 2.0, "model": 1.5, "bias": 1.5, "oversight": 2.5, "security": 2.0, "incident": 1.5, "vendor_risk": 2.5},
    {"governance": 3.5, "data": 3.0, "model": 2.5, "bias": 3.5, "oversight": 3.0, "security": 3.0, "incident": 2.5, "vendor_risk": 2.0},
    {"governance": 2.5, "data": 2.0, "model": 2.0, "bias": 2.0, "oversight": 3.5, "security": 2.0, "incident": 2.0, "vendor_risk": 2.0},
]
PEER_THEMES = [("no_ai_policy", "personal_ai_accounts", "no_incident_procedure"), ("no_ai_policy", "no_bias_audit"), ("personal_ai_accounts", "no_incident_procedure", "vendor_due_diligence"),
               ("no_ai_policy", "personal_ai_accounts", "no_bias_audit"), ("no_ai_policy", "no_incident_procedure", "no_human_oversight"), ("personal_ai_accounts", "no_monitoring"),
               ("no_ai_policy", "personal_ai_accounts", "no_incident_procedure", "no_bias_audit")]


def applicant_csv() -> bytes:
    lines, n = ["applicant_id,selected,sex,race_ethnicity"], 0
    for (sex, race), (total, sel) in APPLICANTS.items():
        for i in range(total):
            n += 1
            lines.append(f"NY-{n:05d},{'yes' if i < sel else 'no'},{sex},{race}")
    for i in range(UNKNOWN[0]):
        n += 1
        lines.append(f"NY-{n:05d},{'yes' if i < UNKNOWN[1] else 'no'},,")
    return ("\n".join(lines) + "\n").encode()


def _abc_engagement(m: Demo, cid: str):
    from app.engagements.models import Engagement

    e = m.db.scalar(select(Engagement).where(Engagement.client_id == cid, Engagement.status == "completed").order_by(Engagement.created_at.desc()).limit(1))
    if e is None:
        raise DemoError("ABC Corp has no completed engagement for the WS-K demo.")
    return e


def _system(m: Demo, e, ref: str):
    from app.systems.models import AISystem

    return m.db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == ref))


def bias_run(m: Demo, e) -> str:
    s = _system(m, e, "SYS-001")
    m.as_(m.user("auditor1@futran.demo"))
    r = m.c.post(f"/api/v1/systems/{s.id}/bias-tests", files={"file": ("screenrank-ny-applicants-jan-jun.csv", applicant_csv(), "text/csv")},
                 data={"method": "selection_rate", "data_source": DATA_SOURCE, "exclude_small": "true"})
    if r.status_code != 200:
        raise DemoError(f"Bias run → {r.status_code}: {r.text[:800]}")
    m.db.expire_all()
    run = r.json()
    if round(run["lowest"]["impact_ratio"], 2) != 0.84 or run["unknown_count"] != 112:
        raise DemoError(f"The bias run does not match the published summary: {run['lowest']}, {run['unknown_count']}")
    chatbot = _system(m, e, "SYS-004")
    if chatbot is not None:
        m.post(f"/systems/{chatbot.id}/guardrail-tests", {"endpoint_label": "Customer support chatbot (vendor sandbox)"})
    return run["id"]


def peers(m: Demo, abc_id: str) -> list[str]:
    """Seven anonymous demo peers in ABC's industry and size band (no service: see the module note)."""
    from app.insights.models import BenchmarkSnapshot
    from app.tenancy.models import Organization
    from app.core.ids import new_id

    abc = m.db.get(Organization, abc_id)
    ids = []
    for i, (scores, themes) in enumerate(zip(PEERS, PEER_THEMES), start=1):
        name = f"Demo peer {i:02d} (demo data)"
        org = m.db.scalar(select(Organization).where(Organization.name == name, Organization.type == "demo_peer"))
        if org is None:
            oid = new_id()  # as tenancy.service.create_organization, which only makes futran and client organizations
            org = Organization(id=oid, organization_id=oid, name=name, legal_name=name, type="demo_peer", status="archived", industry=abc.industry, employee_band=abc.employee_band,
                               benchmark_consent=True)
            m.db.add(org)
            m.db.flush()
            maturity = round(sum(scores.values()) / len(scores), 2)
            m.db.add(BenchmarkSnapshot(organization_id=org.id, industry=abc.industry, size_band=abc.employee_band, consent=True, domain_scores=scores, overall_maturity=maturity,
                                       overall_rating="high" if maturity < 2.5 else "medium", finding_themes=list(themes)))
        ids.append(org.id)
    m.db.commit()
    return ids


def client_prefill(m: Demo, e) -> None:
    """ABC's pre-fill: the client answered its own questions as the auditor later recorded them. Only the client's answers
    carry into an annual review, so the demo needs them; written directly, as the engagement is closed to the client."""
    from app.questionnaire.models import Question, Response

    maria = m.user(f"maria.lopez@{ABC}")
    rows = m.db.execute(select(Response).join(Question, Question.id == Response.question_id).where(Response.engagement_id == e.id, Response.deleted_at.is_(None),
                                                                                                     Response.status != "unanswered", Response.client_status.is_(None),
                                                                                                     Question.default_respondent == "client")).scalars()
    for r in rows:
        r.client_value, r.client_detail, r.client_status, r.client_na_reason, r.client_evidence_ids = r.value, r.detail, r.status, r.na_reason, []
        r.client_answered_by, r.client_answered_at = maria.id, r.answered_at
    m.db.commit()


def seed(m: Demo, ids: dict) -> dict:
    cid = ids["abc"]
    e = _abc_engagement(m, cid)
    run_id = bias_run(m, e)
    m.as_(m.user("chief@futran.demo"))
    m.put(f"/insights/clients/{cid}/consent", {"consent": True, "note": "Benchmarking clause in the signed engagement letter."})
    from app.insights.benchmark import record_snapshot
    from app.insights.models import BenchmarkSnapshot

    if m.db.scalar(select(BenchmarkSnapshot).where(BenchmarkSnapshot.engagement_id == e.id)) is None:  # taken at sign-off 7; kept here for older demo databases
        record_snapshot(m.db, e)
        m.db.commit()
    peer_ids = peers(m, cid)
    client_prefill(m, e)
    annual = m.post(f"/engagements/{e.id}/annual-review")
    return {"bias_run": run_id, "annual_review": annual["engagement_id"], "demo_peers": peer_ids}
