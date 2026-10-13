"""API helpers that walk the new-client wizard (shared by engagement and initiation tests)."""


def _new(client):
    r = client.post("/api/v1/clients", json={})
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, cid, step, payload):
    r = client.put(f"/api/v1/clients/{cid}/wizard/{step}", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def complete(client, cid, p, caico=True, admin_same=True):
    _put(client, cid, "company", {
        "legal_name": "ABC Corp Inc.", "trading_name": "ABC Corp", "industry": "staffing", "employee_band": "250-999",
        "hq_street": "1 Main St", "hq_city": "New York", "hq_state": "US-NY", "hq_postal_code": "10001", "hq_country": "US",
        "primary_jurisdictions": ["US"], "ai_systems_in_scope_count": 2, "engagement_reason": "AI screening of job applicants",
    })
    _put(client, cid, "locations", {"locations": [
        {"site_name": "Headquarters", "street": "1 Main St", "city": "New York", "subdivision_code": "US-NY", "country_code": "US", "in_scope": True},
        {"site_name": "Chicago office", "city": "Chicago", "subdivision_code": "US-IL", "country_code": "US", "in_scope": True},
    ]})
    sugg = client.get(f"/api/v1/clients/{cid}/suggestions").json()
    _put(client, cid, "requirements", {"requirements": [
        {"regulation_id": s["regulation_id"], "label": s["label"], "source": s["source"], "reason_text": s["reason"]} for s in sugg if s["prechecked"]
    ]})
    _put(client, cid, "scope", {
        "type": "initial_assessment", "period_start": "2026-01-01", "period_end": "2026-12-31", "fieldwork_start": "2026-11-02",
        "draft_report_target": "2027-01-15", "final_report_target": "2027-02-15", "letter_due": "2026-10-30",
        "frameworks": ["nist_ai_rmf"], "business_processes": "Candidate screening and ranking", "data_environments": ["production"],
        "geographic_scope": "United States (New York, Illinois)", "planned_systems": ["HireScore", "Resume parser"],
        "departments": ["HR and recruiting", "Engineering and IT"],
        "team": [
            {"user_id": p["chief"].id, "role": "chief_auditor", "conflict_confirmed": True},
            {"user_id": p["em"].id, "role": "engagement_manager", "conflict_confirmed": True},
            {"user_id": p["aud"].id, "role": "auditor", "conflict_confirmed": True},
        ],
    })
    contacts = {"client_admin": {"same_as_caico": True} if admin_same else {"same_as_caico": False, "name": "Sam Admin", "title": "IT manager", "email": "sam@abc.test"}, "dpo": {"not_appointed": True}, "project_lead": {"same_as_caico": True}}
    if caico:
        contacts["caico"] = {"name": "Maria Lopez", "title": "Chief AI Compliance Officer", "email": "maria@abc.test"}
    _put(client, cid, "contacts", contacts)
