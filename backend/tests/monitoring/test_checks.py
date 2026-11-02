"""WS-J's monitoring checks: new undeclared AI tool, commitment overdue, vendor SOC 2 report expiring, policy older than
12 months."""
from datetime import datetime, timedelta

import pytest

from app.connectors import service as csvc
from app.core.errors import AppError
from app.monitoring import registry


@pytest.fixture(autouse=True)
def _loaded():
    registry.load_checks()


def _run(w, code):
    return registry.CHECKS[code].fn(w.db, w.org)


def test_builtin_check_modules_are_discovered():
    assert {"undeclared_ai_tool", "commitment_overdue", "vendor_soc2_expiring", "policy_older_than_12_months"} <= set(registry.CHECKS)


# ---- new undeclared AI tool
def test_undeclared_tool_check_is_not_started_without_any_discovery_source(w):
    (o,) = _run(w, "undeclared_ai_tool")
    assert o.status == "not_started" and "connect" in o.detail.lower()


def test_undeclared_new_tool_fails_and_decided_ones_are_healthy(w, settings):
    csvc.upload(w.db, settings, w.admin, w.org, "expense_csv", "a.csv", b"Employee,Department,Description\nA,HR,OPENAI *CHATGPT\nB,Finance,OTTER.AI\n")
    from app.connectors.models import DiscoveredTool

    chat = w.db.query(DiscoveredTool).filter_by(vendor_key="openai_chatgpt").one()
    csvc.dismiss(w.db, w.admin, w.org, chat.id, "Refunded personal subscription; not used for work")
    out = {o.object_label.split(" · ")[0]: o for o in _run(w, "undeclared_ai_tool")}
    assert out["Otter.ai"].status == "failed" and out["Otter.ai"].action == "review" and "Finance" in out["Otter.ai"].object_label
    assert "Expense data" in out["Otter.ai"].detail and out["Otter.ai"].action_link.startswith("/integrations")
    assert out["ChatGPT"].status == "healthy"


# ---- commitments
def _commitment(w, days, status="open"):
    from app.governance.models import Commitment

    c = Commitment(organization_id=w.org.id, engagement_id=w.engagement.id, source="governance_role", source_id="x", description=f"Commitment {days}",
                   target_date=w.today + timedelta(days=days), owner="Maria Lopez", status=status)
    w.db.add(c)
    w.db.flush()
    return c


def test_commitments_overdue_fail_and_due_within_14_days_need_attention(w):
    _commitment(w, -3)
    _commitment(w, 10)
    _commitment(w, 60)
    _commitment(w, -30, status="closed")
    out = {o.object_label: o for o in _run(w, "commitment_overdue")}
    assert out["Commitment -3"].status == "failed" and "overdue" in out["Commitment -3"].detail.lower()
    assert out["Commitment 10"].status == "attention" and "10 days" in out["Commitment 10"].detail
    assert out["Commitment 60"].status == "healthy" and out["Commitment -30"].status == "healthy"
    assert out["Commitment -3"].action == "open"


# ---- vendor SOC 2 report
def _soc2(w, expires_in, status="received"):
    from app.docrequests.models import DocumentRequest
    from app.reference.models import DocumentCatalogItem

    item = w.db.query(DocumentCatalogItem).filter_by(code="DR-603").one_or_none()
    if item is None:
        item = DocumentCatalogItem(category=6, category_title="Vendor and contract documents", code="DR-603", title="Vendor SOC 2 Type II or ISO 27001 certificates")
        w.db.add(item)
        w.db.flush()
    from app.systems.models import AISystem

    n = w.db.query(AISystem).count() + 1
    s = AISystem(organization_id=w.org.id, engagement_id=w.engagement.id, name=f"System {n}", reference_id=f"SYS-{n:03d}")
    w.db.add(s)
    w.db.flush()
    r = DocumentRequest(organization_id=w.org.id, engagement_id=w.engagement.id, catalog_item_id=item.id, ai_system_id=s.id, requested_at=datetime(2026, 1, 1), status=status,
                        expires_on=(w.today + timedelta(days=expires_in)) if expires_in is not None else None)
    w.db.add(r)
    w.db.flush()
    return r


def test_soc2_report_expired_fails_and_expiring_within_30_days_needs_attention(w):
    a, b, c = _soc2(w, -1), _soc2(w, 25), _soc2(w, 200)
    d = _soc2(w, None)
    out = {o.object_id: o for o in _run(w, "vendor_soc2_expiring")}
    assert out[a.id].status == "failed" and out[b.id].status == "attention" and "25 days" in out[b.id].detail
    assert out[c.id].status == "healthy" and out[d.id].status == "not_started"
    assert out[b.id].action == "request_report"


def test_request_new_report_creates_a_document_request(w, settings):
    from app.docrequests.models import DocumentRequest
    from app.monitoring import service as mon

    mon.set_plan(w.db, w.fadmin, w.org, "monitor")
    b = _soc2(w, 20)
    run = mon.run(w.db, settings, w.org, "manual", "manual:1")
    from app.monitoring.models import MonitorResult

    res = w.db.query(MonitorResult).filter_by(run_id=run.id, object_id=b.id).one()
    out = mon.act(w.db, settings, w.caico, w.org, res.id)
    assert "requested" in out["message"].lower()
    # one request per engagement, item and system: the same engagement's row asks again, keeping the earlier report's files
    assert w.db.query(DocumentRequest).count() == 1
    w.db.refresh(b)
    assert b.status == "pending" and b.due_at == w.today + timedelta(days=30) and b.expires_on is None
    with pytest.raises(AppError):
        mon.act(w.db, settings, w.caico, w.org, res.id)  # once only


def test_request_new_report_goes_to_the_current_engagement_when_there_is_a_newer_one(w, settings):
    from app.docrequests.models import DocumentRequest
    from app.engagements.models import Engagement
    from app.monitoring.monitor_checks import request_new_report
    from app.monitoring.models import MonitorResult

    b = _soc2(w, 20)
    w.engagement.status = "completed"
    newer = Engagement(organization_id=w.org.id, client_id=w.org.id, name="Annual review", status="fieldwork", created_at=datetime(2030, 1, 1))
    w.db.add(newer)
    w.db.flush()
    request_new_report(w.db, settings, w.caico, w.org, MonitorResult(object_id=b.id))
    new = w.db.query(DocumentRequest).filter_by(engagement_id=newer.id).one()
    assert new.status == "pending" and new.catalog_item_id == b.catalog_item_id and new.ai_system_id is None  # the newer engagement has no such system yet
    w.db.refresh(b)
    assert b.status == "received"


# ---- policy older than 12 months
def _policy(w, title, days_old, status="in_place"):
    from app.files.models import FileObject
    from app.governance.models import GovernanceItem, GovernanceRequest

    req = w.db.query(GovernanceRequest).filter_by(engagement_id=w.engagement.id).one_or_none()
    if req is None:
        req = GovernanceRequest(organization_id=w.org.id, engagement_id=w.engagement.id)
        w.db.add(req)
        w.db.flush()
    f = FileObject(organization_id=w.org.id, engagement_id=w.engagement.id, storage_key=f"k-{title}-{days_old}", filename=f"{title}.pdf", content_type="application/pdf",
                   size=1, sha256="0" * 64, created_at=datetime.combine(w.today - timedelta(days=days_old), datetime.min.time()))
    w.db.add(f)
    w.db.flush()
    gi = GovernanceItem(organization_id=w.org.id, request_id=req.id, engagement_id=w.engagement.id, catalog_code=title[:10], kind="document", title=title, status=status,
                        file_ids=[f.id])
    w.db.add(gi)
    w.db.flush()
    return gi


def test_policies_older_than_12_months_fail(w):
    old = _policy(w, "AI acceptable use policy", 400)
    soon = _policy(w, "Information security policy", 350)
    fresh = _policy(w, "Data governance and classification policy", 30)
    charter = _policy(w, "AI compliance department charter (constitution)", 900)  # not a policy
    out = {o.object_id: o for o in _run(w, "policy_older_than_12_months")}
    assert out[old.id].status == "failed" and out[soon.id].status == "attention" and out[fresh.id].status == "healthy"
    assert charter.id not in out and out[old.id].action == "open"
