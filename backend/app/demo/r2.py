"""Release 2 R2 demo pipeline: the design's sample prospects (SM-01 to SM-04), logged by the Sales Officer through the
API so the duplicate check, the independence flag and the activity timeline run as they do for a person. Example data
only: every company, contact and value here is clearly a sample and can be edited or marked lost."""
from datetime import date, timedelta

SAMPLES = [
    {"prospect": {"name": "[Example] Acme Staffing LLC", "website": "acmestaffing.example", "industry": "Staffing & recruitment", "size_band": "251–1,000", "hq_state": "NJ",
                  "hq_country": "US"},
     "contacts": [{"name": "[Example] Jordan Pike", "title": "COO", "email": "jordan.pike@acmestaffing.example", "contact_role": "champion"}],
     "source": "outbound_call", "segment": "staffing_hr", "trigger_event": "ll144_due", "products_of_interest": ["ll144", "monitor"], "next_step": "Scoping call",
     "bant": {"budget": "[Stated range]", "authority": "COO signs", "need": "NYC hiring AI with no bias audit on file", "timeline": "Audit summary posted before go-live"},
     "stage": "qualified", "call": "Spoke with the champion; the ATS scores NYC roles. Scoping call booked."},
    {"prospect": {"name": "[Example] Cedar Ridge Credit Union", "website": "cedarridge.example", "industry": "BFSI", "size_band": "1,000+", "hq_state": "CO", "hq_country": "US"},
     "contacts": [], "source": "referral_partner", "segment": "enterprise_bfsi_health_ins", "trigger_event": "new_state_law", "products_of_interest": ["audit", "eu_ai_act"],
     "next_step": "Chase questionnaire", "bant": {"budget": "Approved", "authority": "Chief Risk Officer", "need": "Colorado AI Act duties", "timeline": "Next quarter"},
     "stage": "scoping", "call": "Intro meeting with the risk team; questionnaire to follow."},
    {"prospect": {"name": "[Example] Delta Logistics", "website": "deltalogistics.example", "industry": "Other", "hq_state": "IL", "hq_country": "US"},
     "contacts": [], "source": "linkedin", "segment": "agents_copilot", "trigger_event": "agents_rollout", "products_of_interest": ["agent_assure", "agentwarden"],
     "next_step": "Discovery call", "stage": "new", "call": None},
]


def seed_r2(m) -> dict:
    """Log the samples as the demo Sales Officer. Returns {"r2_opportunities": [ids]}."""
    sales = m.user("sales@futran.demo")
    if sales is None:
        return {}
    api = m.as_(sales)
    ids = []
    for s in SAMPLES:
        body = {k: v for k, v in s.items() if k not in ("stage", "call")} | {"next_step_due": (date.today() + timedelta(days=2)).isoformat()}
        o = api.post("/sales/opportunities", body)
        if s["call"]:
            api.post(f"/opportunities/{o['id']}/activities", {"kind": "call", "summary": s["call"], "outcome": "Interested"})
        for stage in {"qualified": ["qualified"], "scoping": ["qualified", "scoping"]}.get(s["stage"], []):
            api.patch(f"/opportunities/{o['id']}", {"stage": stage})
        ids.append(o["id"])
    return {"r2_opportunities": ids}
