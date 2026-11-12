"""Release 2 R2 sales desk (spec §4.2, §4.3, §4.8, §4.10, §4.11; SM-01 to SM-04)."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.engagements.models import Engagement
from app.notifications.models import Notification
from app.sales.models import Opportunity, OpportunityActivity, OpportunityContact
from app.sales.service import open_from_trigger
from app.tenancy.models import Organization
from tests.factories import login_as, make_user
from tests.wsd_world import lit  # noqa: F401

API = "/api/v1"


def _log(client, **kw):
    body = {"prospect": {"name": "Acme Staffing LLC", "website": "https://www.acmestaffing.com", "industry": "Staffing & recruitment", "size_band": "251–1,000",
                         "hq_state": "NJ", "hq_country": "US"},
            "contacts": [{"name": "Jo Champion", "title": "COO", "email": "jo@acmestaffing.com", "contact_role": "champion"}],
            "source": "outbound_call", "segment": "staffing_hr", "trigger_event": "ll144_due", "products_of_interest": ["ll144", "monitor"], "est_value": 42000,
            "close_date": "2026-12-15", "next_step": "Scoping call", "next_step_due": "2026-11-14"}
    body.update(kw)
    return client.post(f"{API}/sales/opportunities", json=body)


@pytest.fixture
def mgr(db, lit):
    futran = db.get(Organization, lit["sales"].organization_id)
    u = make_user(db, futran, roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    db.commit()
    return u


# ---- prospects and the duplicate check (§4.3 rules 1-2)
def test_logging_a_new_prospect_creates_a_hidden_prospect_organization(client, db, lit):
    login_as(client, db, lit["sales"])
    r = _log(client)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["company"]["kind"] == "prospect" and o["company"]["name"] == "Acme Staffing LLC"
    assert o["owner_id"] == lit["sales"].id and o["stage"] == "new" and o["source"] == "outbound_call" and o["est_value"] == 42000
    assert [c["name"] for c in o["contacts"]] == ["Jo Champion"]
    org = db.get(Organization, o["organization_id"])
    assert org.status == "prospect" and org.type == "prospect"
    # hidden from every client list, and a prospect has no tenant: client endpoints refuse it
    login_as(client, db, lit["chief"])
    assert "Acme Staffing LLC" not in {c["name"] for c in client.get(f"{API}/clients").json()["clients"]}
    assert "Acme Staffing LLC" not in {c["name"] for c in client.get(f"{API}/opportunities").json()["clients"]}
    assert client.get(f"{API}/clients/{org.id}/people").status_code in (403, 404)


def test_duplicate_check_on_name_domain_and_contact_email(client, db, lit):
    login_as(client, db, lit["sales"])
    first = _log(client).json()
    r = client.get(f"{API}/sales/duplicates", params={"name": "ACME Staffing Services", "website": "acmestaffing.com/careers"})
    m = r.json()["matches"]
    assert r.status_code == 200 and len(m) == 1 and m[0]["organization_id"] == first["organization_id"] and m[0]["kind"] == "prospect"
    assert "acmestaffing.com" in m[0]["reason"]
    assert client.get(f"{API}/sales/duplicates", params={"email": "JO@acmestaffing.com"}).json()["matches"][0]["organization_id"] == first["organization_id"]
    assert client.get(f"{API}/sales/duplicates", params={"name": "Northwind Health Inc."}).json()["matches"][0]["kind"] == "client"
    assert client.get(f"{API}/sales/duplicates", params={"name": "Zephyr Logistics"}).json()["matches"] == []
    # saving a possible duplicate is refused until the rep confirms it is a different company
    r = _log(client, prospect={"name": "Acme Staffing Services", "website": "acmestaffing.com"}, contacts=[])
    assert r.status_code == 409 and r.json()["errors"][0]["organization_id"] == first["organization_id"]
    r = _log(client, prospect={"name": "Acme Staffing Services", "website": "acmestaffing.com"}, contacts=[], confirm_different=True)
    assert r.status_code == 200 and r.json()["organization_id"] != first["organization_id"]


def test_logging_on_an_existing_client_and_on_an_existing_prospect(client, db, lit):
    login_as(client, db, lit["sales"])
    r = _log(client, prospect=None, organization_id=lit["nw"].id, contacts=[])
    assert r.status_code == 200 and r.json()["company"]["kind"] == "client" and r.json()["company"]["name"] == "Northwind Health"
    p = _log(client).json()
    r = _log(client, prospect=None, organization_id=p["organization_id"], contacts=[], products_of_interest=["audit"])
    assert r.status_code == 200 and r.json()["organization_id"] == p["organization_id"]
    futran = lit["sales"].organization_id
    assert _log(client, prospect=None, organization_id=futran, contacts=[]).status_code == 422  # not Futran itself


def test_prospect_never_gets_users(client, db, lit):
    login_as(client, db, lit["sales"])
    org_id = _log(client).json()["organization_id"]
    login_as(client, db, lit["admin"])
    r = client.post(f"{API}/clients/{org_id}/people", json={"name": "X", "email": "x@acmestaffing.com", "roles": ["caico"]})
    assert r.status_code in (403, 404, 405, 422)
    from app.tenancy.models import User

    assert db.scalar(select(User).where(User.organization_id == org_id)) is None


# ---- independence (§4.3 rule 3, plan Shared names)
def test_flag_for_current_recent_and_open_remediation(db, lit):
    from app.remediation.models import RemediationItem
    from app.sales.independence import flag_for

    assert flag_for(db, lit["nw"].id) == (False, "")
    e = Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="in_progress", stage=5)
    db.add(e)
    db.flush()
    flag, why = flag_for(db, lit["abc"].id)
    assert flag and "current audit client" in why
    e.status, e.completed_at = "completed", datetime.utcnow() - timedelta(days=300)
    db.flush()
    flag, why = flag_for(db, lit["abc"].id)
    assert flag and "last 24 months" in why
    e.completed_at = datetime.utcnow() - timedelta(days=800)
    db.flush()
    assert flag_for(db, lit["abc"].id)[0] is False
    db.add(RemediationItem(organization_id=lit["abc"].id, engagement_id=e.id, action="Retest the screening model", status="open"))
    db.flush()
    flag, why = flag_for(db, lit["abc"].id)
    assert flag and "open remediation" in why


def test_flag_is_computed_on_save_and_shown_on_the_record(client, db, lit):
    db.add(Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="completed", stage=9, completed_at=datetime.utcnow() - timedelta(days=30)))
    db.commit()
    login_as(client, db, lit["sales"])
    o = _log(client, prospect=None, organization_id=lit["abc"].id, contacts=[]).json()
    assert o["independence_flag"] is True and "last 24 months" in o["independence_reason"]
    assert o["needs_ca_approval"] is True  # the flag drives Chief Auditor approval (§4.7)
    assert client.get(f"{API}/opportunities/{o['id']}").json()["independence_flag"] is True


# ---- stages (§4.2)
def test_stage_gates_qualified_needs_bant_and_lost_needs_a_reason(client, db, lit):
    login_as(client, db, lit["sales"])
    o = _log(client).json()
    r = client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "qualified"})
    assert r.status_code == 422 and "budget" in r.text.lower()
    bant = {"budget": "$40-50k", "authority": "COO signs", "need": "NYC hiring AI with no bias audit", "timeline": "Before 31 Jan"}
    r = client.patch(f"{API}/opportunities/{o['id']}", json={"bant": bant, "stage": "qualified"})
    assert r.status_code == 200 and r.json()["stage"] == "qualified" and r.json()["bant"]["authority"] == "COO signs"
    assert client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "negotiation"}).json()["stage_label"] == "Negotiation"
    assert client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "lost"}).status_code == 422
    r = client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "lost", "lost_reason": "competitor"})
    assert r.status_code == 200 and r.json()["lost_reason_label"] == "Competitor" and r.json()["closed_at"]
    assert client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "on_hold"}).json()["closed_at"] is None  # reopened


def test_existing_contacted_stage_still_reads_and_moves_on(client, db, lit):
    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Case")
    o.stage = "contacted"
    db.commit()
    login_as(client, db, lit["sales"])
    x = client.get(f"{API}/opportunities/{o.id}").json()
    assert x["stage_label"] == "Contacted" and x["company"]["kind"] == "client" and x["name"] == "Bias audit"
    assert client.patch(f"{API}/opportunities/{o.id}", json={"stage": "proposal"}).json()["stage"] == "proposal"


# ---- contacts and activities (§4.3 rule 4)
def test_contacts_add_edit_remove(client, db, lit):
    login_as(client, db, lit["sales"])
    o = _log(client).json()
    r = client.post(f"{API}/opportunities/{o['id']}/contacts", json={"name": "Lee Legal", "email": "lee@acmestaffing.com", "contact_role": "legal"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert client.patch(f"{API}/opportunities/{o['id']}/contacts/{cid}", json={"title": "General counsel"}).json()["title"] == "General counsel"
    assert client.post(f"{API}/opportunities/{o['id']}/contacts", json={"name": "Bad", "contact_role": "boss"}).status_code == 422
    assert client.delete(f"{API}/opportunities/{o['id']}/contacts/{cid}").status_code == 200
    assert [c["name"] for c in client.get(f"{API}/opportunities/{o['id']}").json()["contacts"]] == ["Jo Champion"]


def test_activities_with_outcome_next_step_and_tasks(client, db, lit):
    login_as(client, db, lit["sales"])
    o = _log(client).json()
    r = client.post(f"{API}/opportunities/{o['id']}/activities", json={"kind": "call", "summary": "Spoke with Jo; ATS scores NYC roles", "outcome": "Interested",
                                                                     "next_step": "Scoping call", "next_step_due": "2026-11-20"})
    assert r.status_code == 200, r.text
    x = client.get(f"{API}/opportunities/{o['id']}").json()
    assert x["next_step"] == "Scoping call" and x["next_step_due"] == "2026-11-20" and x["last_activity_at"]
    call = next(a for a in x["activities"] if a["kind"] == "call")
    assert call["outcome"] == "Interested"
    t = client.post(f"{API}/opportunities/{o['id']}/activities", json={"kind": "task", "summary": "Send LL144 one-pager", "due_on": "2026-11-13"}).json()
    assert client.post(f"{API}/opportunities/{o['id']}/activities/{t['id']}/done").status_code == 200
    assert next(a for a in client.get(f"{API}/opportunities/{o['id']}").json()["activities"] if a["id"] == t["id"])["done_at"]


def test_email_goes_from_the_reps_own_mailbox_and_replies_thread_back(client, db, lit, monkeypatch):
    from app.mail import delivery
    from app.mail.models import MailReply, MailSend, MailThread, UserMailConnection

    db.add(UserMailConnection(organization_id=lit["sales"].organization_id, user_id=lit["sales"].id, provider="google", mailbox="sam@futran.test", status="connected"))
    db.commit()
    monkeypatch.setattr(delivery, "resolve_sender", lambda db, settings, org_id, prefer="organization", user_id=None: delivery.Sender(
        channel="google", from_name="Sam Seller", from_address="sam@futran.test", reply_to="sam@futran.test",
        user_connection=db.scalar(select(UserMailConnection))) if prefer == "me" and user_id else delivery.fallback_sender(None))
    monkeypatch.setattr(delivery, "deliver", lambda db, settings, sender, env, msg: delivery.Result(ok=True, provider_message_id="m1", provider_thread_id="t1"))
    login_as(client, db, lit["sales"])
    o = _log(client).json()
    r = client.post(f"{API}/opportunities/{o['id']}/email", json={"to": ["jo@acmestaffing.com"], "subject": "LL144 audit for Acme", "body": "Hi Jo,\n\nAs promised..."})
    assert r.status_code == 200, r.text
    s = db.scalar(select(MailSend).where(MailSend.related_type == "Opportunity"))
    assert s.sender_user_id == lit["sales"].id and s.related_id == o["id"] and s.organization_id == lit["sales"].organization_id
    thread = db.scalar(select(MailThread).where(MailThread.send_id == s.id))
    a = db.scalar(select(OpportunityActivity).where(OpportunityActivity.opportunity_id == o["id"], OpportunityActivity.kind == "email"))
    assert a.mail_thread_id == thread.id and a.to_addresses == ["jo@acmestaffing.com"]
    db.add(MailReply(organization_id=s.organization_id, thread_id=thread.id, from_address="jo@acmestaffing.com", received_at=datetime(2026, 11, 12, 9), subject="Re: LL144",
                     snippet="Thanks, Thursday works", kind="reply"))
    db.commit()
    em = next(x for x in client.get(f"{API}/opportunities/{o['id']}").json()["activities"] if x["kind"] == "email")
    assert em["replies"][0]["snippet"] == "Thanks, Thursday works" and em["replies"][0]["from"] == "jo@acmestaffing.com"


def test_email_needs_a_connected_mailbox(client, db, lit):
    login_as(client, db, lit["sales"])
    o = _log(client).json()
    r = client.post(f"{API}/opportunities/{o['id']}/email", json={"to": ["jo@acmestaffing.com"], "subject": "Hi", "body": "Hello"})
    assert r.status_code == 409 and "mailbox" in r.json()["detail"].lower()


# ---- the list (SM-02) and the Sales home (SM-01)
def test_list_shows_company_kind_source_products_and_flag_and_filters(client, db, lit):
    login_as(client, db, lit["sales"])
    _log(client)
    open_from_trigger(db, lit["nw"].id, "renewal_due", "ord-1", service="LL144 renewal", why_now="Contract ends in 90 days")
    db.commit()
    d = client.get(f"{API}/opportunities").json()
    by = {i["company"]["name"]: i for i in d["items"]}
    assert by["Acme Staffing LLC"]["company"]["kind"] == "prospect" and by["Acme Staffing LLC"]["source_label"] == "Outbound call"
    assert by["Acme Staffing LLC"]["products_labels"] == ["LL144", "Monitor"]
    assert by["Northwind Health"]["trigger_label"] == "Renewal due" and by["Northwind Health"]["is_automatic"] is True
    assert {s["value"] for s in d["stages"]} >= {"new", "qualified", "scoping", "proposal", "negotiation", "won", "lost", "on_hold"}
    assert "contacted" not in {s["value"] for s in d["stages"]}
    assert {i["company"]["name"] for i in client.get(f"{API}/opportunities", params={"source": "auto"}).json()["items"]} == {"Northwind Health"}
    assert {i["company"]["name"] for i in client.get(f"{API}/opportunities", params={"product": "ll144"}).json()["items"]} == {"Acme Staffing LLC"}


def test_new_triggers_are_recognised(db, lit):
    from app.sales.models import TRIGGER_LABELS, TRIGGERS

    for t in ("renewal_due", "change_order", "entitlement_limit", "discovery_finding"):
        assert t in TRIGGERS and TRIGGER_LABELS[t]
        assert open_from_trigger(db, lit["nw"].id, t, f"ref-{t}", service="x", why_now="y").trigger == t


def test_sales_home_mine_and_team(client, db, lit, mgr):
    login_as(client, db, lit["sales"])
    mine = _log(client).json()
    client.post(f"{API}/opportunities/{mine['id']}/activities", json={"kind": "task", "summary": "Send one-pager", "due_on": "2026-11-13"})
    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Case", owner_id=mgr.id, value=10000)
    o.created_at = o.last_activity_at = datetime.utcnow() - timedelta(days=20)
    won = open_from_trigger(db, lit["nw"].id, "case", "w", service="Readiness", why_now="Case", owner_id=lit["sales"].id, value=5000)
    won.stage, won.closed_at = "won", datetime.utcnow()
    db.commit()
    h = client.get(f"{API}/sales/home").json()
    assert h["scope"] == "mine" and h["can_see_team"] is False
    assert h["kpis"]["open_pipeline"] == 42000 and h["kpis"]["open_count"] == 1 and h["kpis"]["weighted"] == 4200
    assert h["kpis"]["won_this_quarter"] == 5000 and h["recent_wins"][0]["name"] == "Readiness"
    assert {s["stage"]: s["count"] for s in h["by_stage"]}["new"] == 1
    assert [t["summary"] for t in h["tasks"]] == ["Send one-pager"] and h["next_steps"][0]["next_step"] == "Scoping call"
    assert h["stale"] == []
    assert client.get(f"{API}/sales/home", params={"scope": "team"}).json()["scope"] == "mine"  # a Sales Officer sees their own
    login_as(client, db, mgr)
    t = client.get(f"{API}/sales/home", params={"scope": "team"}).json()
    assert t["scope"] == "team" and t["kpis"]["open_count"] == 2 and [s["id"] for s in t["stale"]] == [o.id]
    assert any(a["id"] == o.id for a in t["new_automatic"]) is False  # created 20 days ago
    assert any(a["name"] == "Bias audit" for a in client.get(f"{API}/sales/home").json()["stale"])


def test_sales_home_lists_offers_waiting_on_the_chief_auditor(client, db, lit):
    e = Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="in_progress", stage=5)
    db.add(e)
    o = open_from_trigger(db, lit["abc"].id, "case", "c", service="Bias audit", why_now="Case", owner_id=lit["sales"].id)
    db.commit()
    login_as(client, db, lit["sales"])
    client.post(f"{API}/opportunities/{o.id}/request-approval", json={"note": "Quote asked"})
    assert client.get(f"{API}/sales/home").json()["approvals"][0]["kind"] == "waiting"
    login_as(client, db, lit["chief"])
    h = client.get(f"{API}/sales/home").json()
    assert h["approvals"][0]["kind"] == "to_decide" and h["approvals"][0]["opportunity_id"] == o.id


def test_assignment_notifies_the_new_owner(client, db, lit, mgr):
    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Case")
    db.commit()
    login_as(client, db, mgr)
    client.patch(f"{API}/opportunities/{o.id}", json={"owner_id": lit["sales"].id})
    n = db.scalar(select(Notification).where(Notification.user_id == lit["sales"].id, Notification.kind == "opportunity_assigned"))
    assert n is not None and n.link == f"/sales/opportunities/{o.id}"


# ---- stale and the weekly digest (§4.3 rule 5, §4.10)
def test_weekly_stale_digest_to_owner_and_sales_manager_once_a_week(db, lit, mgr):
    from app.core.config import get_settings
    from app.sales.desk import run_stale_digest

    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Case", owner_id=lit["sales"].id)
    o.created_at = datetime(2026, 10, 1)
    fresh = open_from_trigger(db, lit["nw"].id, "case", "f", service="Readiness", why_now="Case", owner_id=lit["sales"].id)
    fresh.created_at = datetime(2026, 11, 10)
    db.commit()
    now = datetime(2026, 11, 16, 10)  # a Monday
    assert run_stale_digest(db, get_settings(), now) == 2
    owner_n = db.scalar(select(Notification).where(Notification.user_id == lit["sales"].id, Notification.kind == "sales_stale_digest"))
    assert "Bias audit" in owner_n.body and "Readiness" not in owner_n.body
    assert db.scalar(select(Notification).where(Notification.user_id == mgr.id, Notification.kind == "sales_stale_digest")) is not None
    assert run_stale_digest(db, get_settings(), now + timedelta(days=2)) == 0  # once a week, catching up later in the week
    assert run_stale_digest(db, get_settings(), now + timedelta(days=7)) == 2


def test_activity_clears_stale(client, db, lit):
    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Case", owner_id=lit["sales"].id)
    o.created_at = datetime.utcnow() - timedelta(days=30)
    db.commit()
    login_as(client, db, lit["sales"])
    assert client.get(f"{API}/opportunities/{o.id}").json()["stale"] is True
    client.post(f"{API}/opportunities/{o.id}/activities", json={"kind": "note", "summary": "Left a voicemail"})
    assert client.get(f"{API}/opportunities/{o.id}").json()["stale"] is False


# ---- lost prospects deleted after 24 months unless reopened (R2-Q10 default)
def test_lost_prospects_are_deleted_after_24_months_and_logged(client, db, lit):
    from app.audit_log.models import AuditLog
    from app.core.config import get_settings
    from app.sales.desk import run_lost_prospect_purge

    login_as(client, db, lit["sales"])
    old = _log(client).json()
    recent = _log(client, prospect={"name": "Beta Corp", "website": "beta.example"}, contacts=[]).json()
    reopened = _log(client, prospect={"name": "Gamma LLC", "website": "gamma.example"}, contacts=[]).json()
    for x in (old, recent, reopened):
        client.patch(f"{API}/opportunities/{x['id']}", json={"stage": "lost", "lost_reason": "no_budget"})
    db.expire_all()
    db.get(Opportunity, old["id"]).closed_at = datetime(2024, 10, 1)
    db.get(Opportunity, recent["id"]).closed_at = datetime(2025, 6, 1)
    g = db.get(Opportunity, reopened["id"])
    g.closed_at = datetime(2024, 9, 1)
    db.add(Opportunity(organization_id=g.organization_id, trigger="manual", service="Second try", stage="new"))  # reopened with a new opportunity
    db.commit()
    assert run_lost_prospect_purge(db, get_settings(), datetime(2026, 11, 11, 10)) == 1
    db.expire_all()
    assert db.get(Organization, old["organization_id"]) is None
    assert db.get(Opportunity, old["id"]) is None and db.scalar(select(OpportunityContact).where(OpportunityContact.opportunity_id == old["id"])) is None
    assert db.get(Organization, recent["organization_id"]) is not None and db.get(Organization, reopened["organization_id"]) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "prospect.deleted")) is not None


def test_purge_respects_a_legal_hold_when_the_vault_has_landed(db, lit, monkeypatch):
    from app.core.config import get_settings
    from app.sales import desk

    from app.sales.prospects import create_prospect

    org = create_prospect(db, name="Held Co")
    db.add(Opportunity(organization_id=org.id, trigger="manual", service="x", stage="lost", closed_at=datetime(2024, 1, 1)))
    db.commit()
    monkeypatch.setattr(desk, "_on_legal_hold", lambda db, org_id: True)
    assert desk.run_lost_prospect_purge(db, get_settings(), datetime(2026, 11, 11, 10)) == 0
    assert db.get(Organization, org.id) is not None


# ---- conversion on win (R5's handoff, §4.8 item 1)
def test_a_prospect_converts_to_a_normal_draft_client(client, db, lit):
    from app.sales.prospects import convert_to_client

    login_as(client, db, lit["sales"])
    o = _log(client).json()
    org = db.get(Organization, o["organization_id"])
    convert_to_client(db, org)
    db.commit()
    assert org.type == "client" and org.status == "draft"
    login_as(client, db, lit["chief"])
    assert client.get(f"{API}/clients/{org.id}/people").status_code == 200  # client endpoints now accept it
    x = client.get(f"{API}/opportunities/{o['id']}").json()
    assert x["company"]["kind"] == "client"


def test_the_r5_handoff_turns_a_logged_prospect_into_a_normal_client(client, db, lit):
    from types import SimpleNamespace

    from app.commercial.handoff import create_from_acceptance

    login_as(client, db, lit["sales"])
    o = _log(client).json()
    db.expire_all()
    proposal = SimpleNamespace(id="prop-1", opportunity_id=o["id"], lines=[], terms={}, version=1, catalog_version=None, discount_recurring_pct=None)
    acceptance = SimpleNamespace(name="Jo Champion", title="COO", email="jo@acmestaffing.com", po_number=None, accepted_at=datetime(2026, 11, 20))
    h = create_from_acceptance(db, proposal, acceptance, db.get(type(lit["sales"]), lit["sales"].id))
    db.commit()
    org = db.get(Organization, o["organization_id"])
    assert org.type == "client" and org.status == "draft" and org.client_ref
    assert next(i for i in h.items if i["kind"] == "client")["status"] == "Created"
    # now a normal client: in the client lists and accepted by client endpoints
    login_as(client, db, lit["chief"])
    assert "Acme Staffing LLC" in {c["name"] for c in client.get(f"{API}/opportunities").json()["clients"]}
    assert client.get(f"{API}/clients/{org.id}/people").status_code == 200
    assert client.get(f"{API}/opportunities/{o['id']}").json()["company"]["kind"] == "client"


def test_independence_preview_for_the_log_dialog(client, db, lit):
    db.add(Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="in_progress", stage=5))
    db.commit()
    login_as(client, db, lit["sales"])
    r = client.get(f"{API}/sales/independence", params={"organization_id": lit["abc"].id}).json()
    assert r["flag"] is True and "current audit client" in r["reason"]
    assert client.get(f"{API}/sales/independence", params={"organization_id": lit["nw"].id}).json() == {"flag": False, "reason": ""}
    login_as(client, db, lit["aud"])
    assert client.get(f"{API}/sales/independence", params={"organization_id": lit["abc"].id}).status_code == 403
