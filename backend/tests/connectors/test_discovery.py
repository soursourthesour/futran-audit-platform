"""Discovery: syncs and uploads become DiscoveredTool rows aggregated to tool × department; the client confirms (adds
an AITool and asks the department lead for the use case), maps, or dismisses with a reason; undeclared means not in the
latest attestation."""
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.attestation.models import Attestation, AttestationCampaign
from app.connectors import service as svc
from app.connectors.adapters.fake import FAKE, people
from app.connectors.models import ConnectorRun, DiscoveredTool, DiscoveredToolUser
from app.connectors.signals import Signal
from app.core.errors import AppError
from app.inventory.models import AITool, UseCase
from app.notifications.models import Notification


def _connect(w, settings, ctype="google_workspace"):
    url = svc.start_consent(w.db, settings, w.admin, "s1", w.org, ctype)
    st = parse_qs(urlparse(url).query)["state"][0]
    return svc.complete_consent(w.db, settings, "google" if ctype == "google_workspace" else "microsoft", {"state": st, "domain": "abccorp.example", "code": "c"},
                                session_id="s1", user_id=w.admin.id)


def _attest(w, tools, days_ago=10):
    now = datetime.now()
    c = AttestationCampaign(organization_id=w.org.id, engagement_id=w.engagement.id, policy_version="v1", launched_at=now - timedelta(days=days_ago),
                            closes_at=now + timedelta(days=5), link_token=f"tok-{days_ago}-{len(tools)}")
    w.db.add(c)
    w.db.flush()
    w.db.add(Attestation(organization_id=w.org.id, campaign_id=c.id, engagement_id=w.engagement.id, respondent_name="Ana", department_id=w.sales.id, uses_ai=True,
                         tools_declared=tools, submitted_at=now))
    w.db.flush()
    return c


def test_a_sync_aggregates_people_to_tool_and_department(w, settings):
    conn = _connect(w, settings)
    FAKE.signals[("google_workspace", conn.tenant_id)] = [Signal("otter", "oauth_grant", "HR", e, n, detail="calendar") for e, n in people("abccorp.example", 0, 3)] + \
        [Signal("otter", "oauth_grant", "Human Resources", "x@abccorp.example", "X", detail="drive"), Signal("otter", "oauth_grant", "Warehouse", "y@abccorp.example", "Y")]
    run = svc.sync(w.db, settings, conn, w.admin)
    assert run.status == "completed" and run.tools_found == 2
    rows = {r.department_key: r for r in w.db.query(DiscoveredTool).all()}
    hr = rows[w.hr.id]
    assert hr.user_count == 4 and hr.product == "Otter.ai" and hr.detail == "calendar, drive" and hr.status == "new"
    assert rows["name:warehouse"].department_id is None and rows["name:warehouse"].department_name == "Warehouse"
    assert w.db.query(DiscoveredToolUser).filter_by(discovered_tool_id=hr.id).count() == 4


def test_a_second_sync_updates_the_same_rows_and_keeps_decisions(w, settings):
    conn = _connect(w, settings)
    svc.sync(w.db, settings, conn, w.admin)
    t = w.db.query(DiscoveredTool).filter_by(vendor_key="otter").one()
    svc.dismiss(w.db, w.admin, w.org, t.id, "Trial account for a vendor demo, already cancelled")
    svc.sync(w.db, settings, conn, w.admin)
    t2 = w.db.query(DiscoveredTool).filter_by(vendor_key="otter").one()
    assert t2.id == t.id and t2.status == "dismissed"


def test_a_failed_sync_is_logged_and_keeps_the_connection(w, settings):
    conn = _connect(w, settings)
    FAKE.fail_next = 1
    run = svc.sync(w.db, settings, conn, w.admin)
    assert run.status == "failed" and "503" in run.error and conn.status == "connected" and conn.error


def test_an_expense_upload_keeps_aggregates_and_cardholders_but_not_the_file(w, settings):
    from app.files.models import FileObject

    data = b"Employee,Email,Department,Description\nAna Ruiz,ana@abccorp.example,Sales & Marketing,OPENAI *CHATGPT\nBen Ok,ben@abccorp.example,Sales and Marketing,OPENAI *CHATGPT\n"
    run = svc.upload(w.db, settings, w.admin, w.org, "expense_csv", "oct.csv", data)
    assert (run.rows_read, run.rows_matched, run.tools_found) == (2, 2, 1)
    t = w.db.query(DiscoveredTool).one()
    assert t.department_id == w.sales.id and t.user_count == 2 and t.detail == "2 paid subscriptions"
    assert w.db.query(FileObject).count() == 0


def test_a_network_log_upload_stores_no_person(w, settings):
    data = b"user,department,host\nu1,Finance,claude.ai\nu2,Finance,claude.ai\n"
    svc.upload(w.db, settings, w.admin, w.org, "casb_csv", "proxy.csv", data)
    t = w.db.query(DiscoveredTool).one()
    assert t.signal == "traffic" and t.user_count == 2
    assert w.db.query(DiscoveredToolUser).count() == 0


def test_undeclared_means_not_in_the_latest_attestation(w, settings):
    conn = _connect(w, settings)
    FAKE.signals[("google_workspace", conn.tenant_id)] = [Signal("otter", "oauth_grant", "HR", "a@abccorp.example"), Signal("openai_chatgpt", "oauth_grant", "HR", "b@abccorp.example")]
    svc.sync(w.db, settings, conn, w.admin)
    _attest(w, [{"tool": "other", "account_type": "personal_free", "name": "Otter"}], days_ago=40)  # an older campaign
    _attest(w, [{"tool": "chatgpt", "account_type": "personal_paid"}], days_ago=5)
    by = {t["vendor"]: t for t in svc.tools(w.db, w.org)}
    assert by["OpenAI"]["declared"] is True and by["Otter.ai"]["declared"] is False and by["Otter.ai"]["attestation_exists"] is True


def test_confirm_adds_the_tool_to_the_inventory_and_asks_the_department_lead(w, settings):
    conn = _connect(w, settings)
    FAKE.signals[("google_workspace", conn.tenant_id)] = [Signal("otter", "oauth_grant", "HR", "a@abccorp.example")]
    svc.sync(w.db, settings, conn, w.admin)
    t = w.db.query(DiscoveredTool).one()
    svc.confirm(w.db, settings, w.admin, w.org, t.id)
    tool = w.db.get(AITool, t.matched_tool_id)
    assert t.status == "confirmed" and tool.vendor == "Otter.ai" and tool.source == "discovery" and tool.account_type == "unknown"
    n = w.db.query(Notification).filter_by(user_id=w.hr_lead.id).one()
    assert "use case" in n.title.lower() and n.link == "/inventory/new"
    with pytest.raises(AppError):
        svc.confirm(w.db, settings, w.admin, w.org, t.id)


def test_confirm_links_an_inventory_tool_that_already_exists(w, settings):
    existing = AITool(organization_id=w.org.id, vendor="otter.ai", product="OTTER.AI", account_type="team")
    w.db.add(existing)
    w.db.flush()
    svc.upload(w.db, settings, w.admin, w.org, "expense_csv", "x.csv", b"Description,Department\nOTTER.AI PRO,HR\n")
    t = w.db.query(DiscoveredTool).one()
    svc.confirm(w.db, settings, w.admin, w.org, t.id)
    assert t.matched_tool_id == existing.id and w.db.query(AITool).count() == 1


def test_map_needs_a_tool_of_the_same_organisation(w, settings):
    svc.upload(w.db, settings, w.admin, w.org, "expense_csv", "x.csv", b"Description,Department\nOPENAI *CHATGPT,HR\n")
    t = w.db.query(DiscoveredTool).one()
    foreign = AITool(organization_id=w.other.id, vendor="OpenAI", product="ChatGPT")
    mine = AITool(organization_id=w.org.id, vendor="OpenAI", product="ChatGPT Enterprise", account_type="enterprise")
    w.db.add_all([foreign, mine])
    w.db.flush()
    with pytest.raises(AppError):
        svc.map_to_tool(w.db, w.admin, w.org, t.id, foreign.id)
    svc.map_to_tool(w.db, w.admin, w.org, t.id, mine.id)
    assert t.status == "mapped" and t.matched_tool_id == mine.id


def test_dismiss_needs_a_reason(w, settings):
    svc.upload(w.db, settings, w.admin, w.org, "expense_csv", "x.csv", b"Description,Department\nOPENAI *CHATGPT,HR\n")
    t = w.db.query(DiscoveredTool).one()
    with pytest.raises(AppError):
        svc.dismiss(w.db, w.admin, w.org, t.id, "no")
    svc.dismiss(w.db, w.admin, w.org, t.id, "Personal subscription refunded; not used for work")
    assert t.status == "dismissed" and "refunded" in t.dismiss_reason


def _tier(w, tool_id, tier):
    uc = UseCase(organization_id=w.org.id, engagement_id=w.engagement.id, name="Sales emails", department_id=w.sales.id, tool_ids=[tool_id], final_tier=tier)
    w.db.add(uc)
    w.db.flush()


def test_auditor_sees_names_only_for_tier_2_or_3_tools(w, settings):
    from app.auth.deps import Actor

    svc.upload(w.db, settings, w.admin, w.org, "expense_csv", "x.csv", b"Employee,Email,Department,Description\nAna Ruiz,ana@abccorp.example,HR,OPENAI *CHATGPT\n")
    t = w.db.query(DiscoveredTool).one()
    actor = Actor(user=w.auditor, organization=w.db.get(type(w.org), w.auditor.organization_id))
    with pytest.raises(AppError):
        svc.people_for_auditor(w.db, actor, w.org, t.id)  # not mapped to any tool
    svc.confirm(w.db, settings, w.admin, w.org, t.id)
    _tier(w, t.matched_tool_id, 1)
    with pytest.raises(AppError):
        svc.people_for_auditor(w.db, actor, w.org, t.id)
    _tier(w, t.matched_tool_id, 2)
    assert svc.people_for_auditor(w.db, actor, w.org, t.id) == [{"name": "Ana Ruiz", "email": "ana@abccorp.example"}]
