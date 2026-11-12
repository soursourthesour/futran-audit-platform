"""Release 2 R2 review fixes: the Chief Auditor approval follows the independence flag on logged opportunities, the flag
is computed on read for v0.6 rows, only the owner or a Sales Manager works someone else's opportunity, the lost-prospect
clean-up removes every trace of the prospect's people, and the stale digest goes only to sales roles."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.engagements.models import Engagement
from app.notifications.models import Notification
from app.sales.models import Opportunity
from app.sales.service import open_from_trigger
from app.tenancy.models import Organization
from tests.factories import login_as, make_user
from tests.wsd_world import lit  # noqa: F401

API = "/api/v1"


def _recent_client(db, org_id):
    """Flagged (an engagement completed in the last 24 months) but not a current audit client."""
    db.add(Engagement(organization_id=org_id, client_id=org_id, name="Audit 2025", status="completed", stage=9, completed_at=datetime.utcnow() - timedelta(days=60)))
    db.commit()


def _log(client, **kw):
    body = {"prospect": {"name": "Acme Staffing LLC", "website": "acmestaffing.com"}, "contacts": [{"name": "Jo Champion", "email": "jo@acmestaffing.com", "contact_role": "champion"}],
            "products_of_interest": ["ll144"], "est_value": 42000}
    body.update(kw)
    return client.post(f"{API}/sales/opportunities", json=body)


# ---- 1. the independence flag keeps Chief Auditor approval on logged opportunities
def test_changing_the_service_keeps_approval_needed_for_a_flagged_logged_opportunity(client, db, lit):
    _recent_client(db, lit["abc"].id)
    login_as(client, db, lit["sales"])
    o = _log(client, prospect=None, organization_id=lit["abc"].id, contacts=[]).json()
    assert o["needs_ca_approval"] is True
    r = client.patch(f"{API}/opportunities/{o['id']}", json={"service": "A different offer"})
    assert r.status_code == 200 and r.json()["needs_ca_approval"] is True
    assert client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "proposal"}).status_code == 409


def test_a_save_that_newly_flags_a_logged_opportunity_needs_approval_before_an_offer(client, db, lit):
    login_as(client, db, lit["sales"])
    o = _log(client, prospect=None, organization_id=lit["abc"].id, contacts=[]).json()
    assert o["needs_ca_approval"] is False
    _recent_client(db, lit["abc"].id)
    r = client.patch(f"{API}/opportunities/{o['id']}", json={"next_step": "Call back"})
    assert r.json()["independence_flag"] is True and r.json()["needs_ca_approval"] is True
    assert client.patch(f"{API}/opportunities/{o['id']}", json={"stage": "proposal"}).status_code == 409
    # once approved, a later save keeps the approval
    login_as(client, db, lit["chief"])
    client.post(f"{API}/opportunities/{o['id']}/approve", json={"decision": "approve", "note": "Separate team"})
    login_as(client, db, lit["sales"])
    r = client.patch(f"{API}/opportunities/{o['id']}", json={"next_step": "Send proposal"})
    assert r.json()["ca_decision"] == "approved" and r.json()["can_send_offer"] is True


def test_v06_add_opportunity_needs_approval_for_a_flagged_client(client, db, lit):
    _recent_client(db, lit["abc"].id)
    login_as(client, db, lit["sales"])
    r = client.post(f"{API}/opportunities", json={"organization_id": lit["abc"].id, "service": "Readiness review", "service_kind": "readiness"})
    assert r.status_code == 200 and r.json()["needs_ca_approval"] is True and r.json()["independence_flag"] is True


# ---- 2. v0.6 rows: the flag is computed on read when it was never stored
def test_v06_row_on_a_current_audit_client_reads_as_flagged(client, db, lit):
    db.add(Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC audit", status="in_progress", stage=5))
    db.execute(text("INSERT INTO opportunities (id, organization_id, trigger, service, service_kind, stage, system_ids, system_types, needs_ca_approval, created_at, updated_at) "
                    "VALUES ('old-1', :org, 'case', 'Bias audit', 'bias_audit', 'new', '[]', '[]', 1, :at, :at)"), {"org": lit["abc"].id, "at": datetime(2026, 9, 1)})
    db.commit()
    login_as(client, db, lit["sales"])
    x = client.get(f"{API}/opportunities/old-1").json()
    assert x["independence_flag"] is True and "current audit client" in x["independence_reason"]
    assert [i["id"] for i in client.get(f"{API}/opportunities", params={"flag": True}).json()["items"]] == ["old-1"]
    assert ",Yes," in client.get(f"{API}/opportunities/export.csv").text
    assert db.scalar(text("SELECT independence_flag FROM opportunities WHERE id='old-1'")) is None  # nothing stored on read


# ---- 3. only the owner or a Sales Manager works someone else's opportunity
@pytest.fixture
def other(db, lit):
    rep2 = make_user(db, db.get(Organization, lit["sales"].organization_id), roles=["sales_team"], name="Rae Rep", email="rae@futran.test")
    o = open_from_trigger(db, lit["nw"].id, "case", "c1", service="Bias audit", why_now="Case", owner_id=rep2.id)
    db.commit()
    return o


def test_an_officer_only_reads_another_reps_opportunity(client, db, lit, other):
    login_as(client, db, lit["sales"])
    oid = other.id
    assert client.get(f"{API}/opportunities/{oid}").json()["can_work"] is False
    assert client.patch(f"{API}/opportunities/{oid}", json={"stage": "lost", "lost_reason": "price"}).status_code == 403
    assert client.patch(f"{API}/opportunities/{oid}", json={"next_step": "x"}).status_code == 403
    assert client.post(f"{API}/opportunities/{oid}/contacts", json={"name": "X"}).status_code == 403
    assert client.post(f"{API}/opportunities/{oid}/activities", json={"kind": "note", "summary": "Hello"}).status_code == 403
    r = client.post(f"{API}/opportunities/bulk", json={"ids": [oid], "stage": "qualified"})
    assert r.json()["changed"] == 0 and r.json()["skipped"] == 1
    db.expire_all()
    assert db.get(Opportunity, oid).stage == "new"
    items = {i["id"]: i for i in client.get(f"{API}/opportunities").json()["items"]}
    assert items[oid]["can_edit"] is False


def test_the_owner_and_a_sales_manager_work_it_and_an_unowned_one_can_be_taken(client, db, lit, other):
    mgr = make_user(db, db.get(Organization, lit["sales"].organization_id), roles=["sales_manager"], name="Mia Manager", email="mia@futran.test")
    free = open_from_trigger(db, lit["nw"].id, "case", "c2", service="Readiness", why_now="Case")
    db.commit()
    login_as(client, db, mgr)
    assert client.post(f"{API}/opportunities/{other.id}/activities", json={"kind": "note", "summary": "Manager note"}).status_code == 200
    login_as(client, db, lit["sales"])
    assert client.post(f"{API}/opportunities/{free.id}/activities", json={"kind": "call", "summary": "Called them"}).status_code == 200
    assert client.patch(f"{API}/opportunities/{free.id}", json={"owner_id": lit["sales"].id}).status_code == 200


# ---- 4. the lost-prospect clean-up leaves no personal data
def test_purge_removes_mail_files_referrals_and_notifications_of_the_prospect(client, db, lit, settings, monkeypatch):
    from app.core.config import get_settings
    from app.files.models import FileObject
    from app.files.service import upload
    from app.files.storage import get_storage
    from app.mail import delivery
    from app.mail.models import MailRecipient, MailReply, MailSend, MailThread, OutboxMessage, UserMailConnection
    from app.partners.models import Partner, Referral
    from app.proposals.models import Proposal, ProposalLink
    from app.sales.desk import run_lost_prospect_purge
    from app.scoping.models import QuestionnaireSend, ScopingQuestionnaire

    futran_id = lit["sales"].organization_id
    db.add(UserMailConnection(organization_id=futran_id, user_id=lit["sales"].id, provider="google", mailbox="sam@futran.test", status="connected"))
    db.commit()
    monkeypatch.setattr(delivery, "resolve_sender", lambda db, settings, org_id, prefer="organization", user_id=None: delivery.Sender(
        channel="google", from_name="Sam", from_address="sam@futran.test", user_connection=db.scalar(select(UserMailConnection))))
    monkeypatch.setattr(delivery, "deliver", lambda db, settings, sender, env, msg: delivery.Result(ok=True, provider_message_id="m1", provider_thread_id="t1"))
    login_as(client, db, lit["sales"])
    o = _log(client).json()
    assert client.post(f"{API}/opportunities/{o['id']}/email", json={"to": ["jo@acmestaffing.com"], "subject": "Hello Jo", "body": "Private note"}).status_code == 200
    thread = db.scalar(select(MailThread))
    db.add(MailReply(organization_id=futran_id, thread_id=thread.id, from_address="jo@acmestaffing.com", received_at=datetime(2026, 1, 2), snippet="Thanks", kind="reply"))
    # R4: a sent proposal with its files and the acceptance link email; R3: a questionnaire sent to the contact
    p = Proposal(thread_id="t", opportunity_id=o["id"], organization_id=o["organization_id"], version=1, status="sent")
    db.add(p)
    db.flush()
    f = upload(db, settings, lit["sales"], data=b"%PDF-1.4 proposal for Acme", filename="Acme proposal.pdf", content_type="application/pdf", organization_id=futran_id,
               linked_type="Proposal", linked_id=p.id)
    p.file_ids = {"pdf": f.id}
    link = ProposalLink(proposal_id=p.id, name="Jo Champion", email="jo@acmestaffing.com", token_hash="h" * 64, expires_at=datetime(2026, 2, 1))
    db.add(link)
    q = ScopingQuestionnaire(prospect_id=o["organization_id"], opportunity_id=o["id"], bank_version=1)
    db.add(q)
    db.flush()
    qs = QuestionnaireSend(questionnaire_id=q.id, contact_name="Jo Champion", contact_email="jo@acmestaffing.com")
    db.add(qs)
    db.flush()
    for related_type, rid in (("ProposalLink", link.id), ("QuestionnaireSend", qs.id)):
        ms = MailSend(organization_id=futran_id, kind="system", mode="direct", subject="For Acme", related_type=related_type, related_id=rid)
        db.add(ms)
        db.flush()
        db.add(MailRecipient(organization_id=futran_id, send_id=ms.id, email="jo@acmestaffing.com"))
        db.add(OutboxMessage(organization_id=futran_id, to=["jo@acmestaffing.com"], subject="For Acme", body_html="x", body_text="x", template_key="t", mail_send_id=ms.id,
                             related_type=related_type, related_id=rid, attachments=[]))
    partner = Partner(organization_id=futran_id, name="Harbor Law LLP", type="law_firm", status="active")
    db.add(partner)
    db.flush()
    db.add(Referral(organization_id=o["organization_id"], partner_id=partner.id, direction="in", opportunity_id=o["id"], note="Jo at Acme", at=datetime(2024, 1, 1)))
    db.add(Notification(organization_id=futran_id, user_id=lit["sales"].id, kind="opportunity_assigned", title="Acme", link=f"/sales/opportunities/{o['id']}"))
    opp = db.get(Opportunity, o["id"])
    opp.stage, opp.lost_reason, opp.closed_at = "lost", "price", datetime(2024, 1, 1)
    db.commit()
    key = f.storage_key

    assert run_lost_prospect_purge(db, settings, datetime(2026, 11, 11, 10)) == 1
    db.expire_all()
    email = "jo@acmestaffing.com"
    assert db.scalar(select(MailRecipient).where(MailRecipient.email == email)) is None
    assert db.scalar(select(MailReply).where(MailReply.from_address == email)) is None
    assert not [m for m in db.scalars(select(OutboxMessage)) if email in (m.to or [])]
    assert db.scalar(select(MailSend).where(MailSend.related_id.in_([o["id"], link.id, qs.id]))) is None
    assert db.get(FileObject, f.id) is None
    with pytest.raises(Exception):
        get_storage(settings).get(key)
    ref = db.scalar(select(Referral))
    assert ref is not None and ref.opportunity_id is None and ref.organization_id != o["organization_id"] and ref.note is None  # the partner keeps the count
    assert db.scalar(select(Notification).where(Notification.link.contains(o["id"]))) is None
    assert db.get(Organization, o["organization_id"]) is None


# ---- 5. the stale digest goes only to people who still hold a sales role
def test_stale_digest_skips_owners_without_a_sales_role(db, lit, settings):
    from app.sales.desk import run_stale_digest
    from app.tenancy.models import RoleAssignment

    o = open_from_trigger(db, lit["nw"].id, "case", "c", service="Bias audit", why_now="Case", owner_id=lit["sales"].id)
    o.created_at = datetime(2026, 10, 1)
    for ra in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == lit["sales"].id)):
        ra.role = "auditor"  # moved off the sales team
    db.commit()
    run_stale_digest(db, settings, datetime(2026, 11, 16, 10))
    assert db.scalar(select(Notification).where(Notification.user_id == lit["sales"].id, Notification.kind == "sales_stale_digest")) is None
