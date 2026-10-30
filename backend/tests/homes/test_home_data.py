"""WS-F home data (spec §13.1), against the browser-test world: ABC Corp at stage 6 (every client role filled) and
Meridian GmbH at stage 3, whose CAICO is also its Client Admin. Tests that write data come last in each group and only
add rows the earlier assertions do not count."""
from datetime import date, timedelta

from sqlalchemy import select

ABC = "abccorp.example"


def _get(c, path):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == 200, (path, r.status_code, r.text)
    return r.json()


# ---- Futran Admin console
def test_admin_console_counts_users_clients_laws_and_templates(as_user):
    d = _get(as_user("admin@futran.demo"), "/home/admin")
    assert d["users"]["total"] >= 6 and d["users"]["by_role"]["auditor"] == 2 and d["users"]["by_role"]["chief_auditor"] == 1
    assert d["clients"]["total"] == 2 and d["clients"]["in_progress"] == 2
    assert d["law_matrix"]["laws"] > 0 and d["law_matrix"]["published_at"]
    assert d["templates"] > 0
    assert "pending_proposals" in d


# ---- Auditor: My work
def test_my_work_lists_only_assigned_engagements(as_user):
    d = _get(as_user("auditor1@futran.demo"), "/home/my-work")
    refs = {e["client"]: e for e in d["engagements"]}
    assert set(refs) == {"ABC Corp", "Meridian GmbH"}
    abc = refs["ABC Corp"]
    assert abc["stage"] == 6 and abc["systems"] == 4 and abc["systems_assessed"] == 4 and abc["link"] == f"/clients/{abc['client_id']}"
    d2 = _get(as_user("auditor2@futran.demo"), "/home/my-work")
    assert {e["client"] for e in d2["engagements"]} == {"Meridian GmbH"}  # not on the ABC team


def test_my_work_tasks_include_a_returned_finding_and_an_overdue_evidence_request(world, as_user):
    from app.engagements.models import Engagement
    from app.findings.models import Finding
    from app.docrequests.models import EvidenceRequest
    from app.tenancy.models import User

    db = world["db"]
    aud = db.scalar(select(User).where(User.email == "auditor1@futran.demo"))
    e = db.scalar(select(Engagement).where(Engagement.client_id == world["ids"]["abc"]))
    f = Finding(organization_id=e.client_id, engagement_id=e.id, ref="F-090", title="Vendor contract silent on bias audits", severity="medium", author_id=aud.id,
                status="returned", review_comment="Add the regulatory reference and owner", review_role="chief_auditor")
    er = EvidenceRequest(organization_id=e.client_id, engagement_id=e.id, ref="ER-090", description="Model card for the résumé screener", requested_by=aud.id,
                         due_date=date.today() - timedelta(days=3), status="outstanding")
    db.add_all([f, er])
    db.commit()
    d = _get(as_user("auditor1@futran.demo"), "/home/my-work")
    kinds = {t["kind"]: t for t in d["tasks"]}
    assert kinds["finding_returned"]["title"] == "Finding F-090 returned" and "Add the regulatory reference" in kinds["finding_returned"]["detail"]
    assert kinds["evidence_overdue"]["link"].startswith(f"/clients/{e.client_id}/")
    assert d["tasks"][0]["overdue"] is True  # overdue items first
    other = _get(as_user("auditor2@futran.demo"), "/home/my-work")
    assert all("F-090" not in t["title"] for t in other["tasks"])  # another auditor's task is not shown
    f.deleted_at = er.deleted_at = e.created_at
    db.commit()


# ---- QA Reviewer queue
def _abc(world):
    from app.engagements.models import Engagement

    return world["db"].scalar(select(Engagement).where(Engagement.client_id == world["ids"]["abc"]))


def test_qa_queue_shows_chief_authored_findings_and_overrides_and_reviews_them(world, as_user):
    from app.findings.models import Finding
    from app.notifications.models import Notification
    from app.systems.models import AISystem
    from app.tenancy.models import User

    db = world["db"]
    e = _abc(world)
    chief = db.scalar(select(User).where(User.email == "chief@futran.demo"))
    f = Finding(organization_id=e.client_id, engagement_id=e.id, ref="F-091", title="Null-compliance risk: no demographic data", severity="high", author_id=chief.id,
                status="submitted", review_role="qa_reviewer", submitted_by=chief.id)
    db.add(f)
    db.commit()
    sys1 = db.scalar(select(AISystem).where(AISystem.engagement_id == e.id, AISystem.reference_id == "SYS-002"))
    cc = as_user("chief@futran.demo")
    r = cc.put(f"/api/v1/systems/{sys1.id}/score/override", json={"rating": "high", "rationale": "Customer data enters a vendor model with no contract terms."})
    assert r.status_code == 200, r.text

    qa = as_user("qa@futran.demo")
    d = _get(qa, "/home/qa")
    assert [x["ref"] for x in d["findings"]] == ["F-091"] and d["findings"][0]["author"] == chief.name and d["findings"][0]["client"] == "ABC Corp"
    assert d["findings"][0]["link"] == f"/clients/{e.client_id}/findings"
    ov = d["overrides"]
    assert len(ov) == 1 and ov[0]["system_id"] == sys1.id and ov[0]["rating"] == "high" and ov[0]["by"] == chief.name and ov[0]["rationale"].startswith("Customer data")

    # the Chief Auditor cannot review their own override, and an auditor not on the team cannot see it
    assert cc.post(f"/api/v1/systems/{sys1.id}/score/override/review", json={"decision": "approve"}).status_code == 403
    assert as_user("auditor2@futran.demo").post(f"/api/v1/systems/{sys1.id}/score/override/review", json={"decision": "approve"}).status_code in (403, 404)
    # return needs a comment, then goes back to the Chief Auditor
    assert qa.post(f"/api/v1/systems/{sys1.id}/score/override/review", json={"decision": "return"}).status_code == 422
    r = qa.post(f"/api/v1/systems/{sys1.id}/score/override/review", json={"decision": "return", "comment": "Cite the contract clause you relied on."})
    assert r.status_code == 200, r.text
    d = _get(qa, "/home/qa")
    assert d["overrides"] == [] and d["reviewed"][0]["kind"] == "override" and d["reviewed"][0]["decision"] == "returned"
    assert db.scalar(select(Notification).where(Notification.user_id == chief.id, Notification.kind == "override_returned")) is not None
    # the Chief Auditor changes the rationale: it comes back for review; approving clears it
    cc.put(f"/api/v1/systems/{sys1.id}/score/override", json={"rating": "high", "rationale": "Clause 7.2 lets the vendor train on customer data."})
    assert len(_get(qa, "/home/qa")["overrides"]) == 1
    assert qa.post(f"/api/v1/systems/{sys1.id}/score/override/review", json={"decision": "approve"}).status_code == 200
    assert qa.post(f"/api/v1/systems/{sys1.id}/score/override/review", json={"decision": "approve"}).status_code == 409  # nothing left to review
    assert _get(qa, "/home/qa")["overrides"] == []
    from app.audit_log.models import AuditLog

    assert db.scalar(select(AuditLog).where(AuditLog.action == "score.override_approve", AuditLog.object_id == sys1.id)) is not None
    # the finding is approved through the existing findings endpoint and leaves the queue
    assert qa.post(f"/api/v1/findings/{f.id}/approve", json={"comment": None}).status_code == 200
    assert _get(qa, "/home/qa")["findings"] == []
    cc.put(f"/api/v1/systems/{sys1.id}/score/override", json={"rating": None, "rationale": None})


# ---- Client Admin home
def test_client_admin_home_users_connectors_and_role_changes(world, as_user):
    d = _get(as_user(f"sam.okafor@{ABC}"), "/home/client-admin")
    assert d["users"]["active"] >= 10 and d["departments"]["total"] == 3 and d["departments"]["without_lead"] == []
    assert d["email"]["link"] == "/admin/email" and d["email"]["status"]
    assert d["sso"]["available"] is False
    changes = d["role_changes"]
    assert any("Department Compliance Lead" in c["summary"] and "Priya Shah" in c["summary"] for c in changes)
    assert any(c["sign_off_role"] for c in changes) or all(not c["sign_off_role"] for c in changes)


def test_client_admin_home_is_tenant_scoped_for_the_caico_with_admin_powers(world, as_user):
    d = _get(as_user("katrin.vogel@meridian.example"), "/home/client-admin")
    assert d["organization"] == "Meridian GmbH"
    assert all("Priya" not in c["summary"] for c in d["role_changes"])
    assert {x["name"] for x in d["departments"]["items"]} == {"Data Science", "Engineering"}


def test_client_admin_home_lists_a_department_without_a_lead(world, as_user):
    from app.tenancy.models import Organization
    from app.tenancy.service import create_department

    db = world["db"]
    org = db.get(Organization, world["ids"]["meridian"])
    dept = create_department(db, org, name="Legal")
    db.commit()
    d = _get(as_user("katrin.vogel@meridian.example"), "/home/client-admin")
    assert [x["name"] for x in d["departments"]["without_lead"]] == ["Legal"]
    assert any(t["kind"] == "assign_lead" and t["link"] == "/people/departments" for t in d["todos"])
    dept.deleted_at = org.created_at
    db.commit()


# ---- Executive Sponsor
def test_sponsor_home_summary_and_signatures(world, as_user):
    d = _get(as_user(f"robert.chen@{ABC}"), "/home/sponsor")
    assert d["engagement"]["stage"] == 6
    so4 = d["signoffs"]["4"]
    assert so4["sign_off"]["status"] == "approved" and so4["link"] == "/review"
    assert d["signoffs"]["6"]["sign_off"] is None and d["signoffs"]["6"]["link"] == "/responses"
    assert d["waiting"] == []
    assert d["findings"] is None  # findings are shared with the draft report (stage 7)
    assert d["systems"] == 4 and d["use_cases"] == 6


# ---- DPO
def test_dpo_home_lists_tier_2_and_3_use_cases_and_sign_off_3(world, as_user):
    d = _get(as_user(f"daniel.kim@{ABC}"), "/home/dpo")
    assert d["signoff3"]["sign_off"]["status"] == "approved"
    names = {u["name"]: u for u in d["use_cases"]}
    assert "Meeting notes with Copilot" not in names  # tier 1
    assert names["Résumé screening for NYC roles"]["tier"] == 3 and names["Résumé screening for NYC roles"]["data_labels"]
    assert len(names) == 5
    assert d["privacy"]["min_group"] == 3 and d["privacy"]["individuals_visible_to"]


# ---- Department Compliance Lead
def test_department_home_is_limited_to_the_leads_department(world, as_user):
    priya = as_user(f"priya.shah@{ABC}")
    d = _get(priya, "/home/department")
    assert [x["name"] for x in d["departments"]] == ["HR"]
    hr = d["departments"][0]
    assert {u["name"] for u in hr["use_cases"]} == {"Résumé screening for NYC roles", "Drafting job adverts with ChatGPT"}
    assert hr["signoff2"]["sign_off"]["status"] == "approved" and hr["awaiting_approval"] == 0
    assert hr["findings"] is None  # shared with the draft report
    assert "responses" in hr["attestation"] and "register" in hr
    from app.tenancy.models import Department

    fin = world["db"].scalar(select(Department).where(Department.organization_id == world["ids"]["abc"], Department.name == "Finance"))
    assert priya.get(f"/api/v1/home/department?department_id={fin.id}").status_code == 403


# ---- Contributor
def test_my_tasks_shows_own_entries_and_returned_items(world, as_user):
    from app.inventory.models import UseCase

    tom = as_user(f"tom.reyes@{ABC}")
    d = _get(tom, "/home/my-tasks")
    assert {x["name"] for x in d["entries"]} == {"Résumé screening for NYC roles", "Drafting job adverts with ChatGPT"}
    assert d["returned"] == []
    db = world["db"]
    uc = db.scalar(select(UseCase).where(UseCase.name == "Drafting job adverts with ChatGPT"))
    before = (uc.status, uc.returned_comment)
    uc.status, uc.returned_comment = "returned", "Which account do recruiters use? Add the named users."
    db.commit()
    d = _get(tom, "/home/my-tasks")
    assert d["returned"][0]["name"] == "Drafting job adverts with ChatGPT" and d["returned"][0]["link"] == f"/inventory/{uc.id}"
    assert "named users" in d["returned"][0]["comment"]
    nina = _get(as_user(f"nina.patel@{ABC}"), "/home/my-tasks")
    assert nina["returned"] == []  # another department's contributor
    uc.status, uc.returned_comment = before
    db.commit()


def test_my_tasks_says_whether_the_inventory_is_open(world, as_user):
    """The Contributor's 'Add a use case' is offered only while the inventory takes changes (inventory/service.py)."""
    from app.engagements.models import Engagement
    from app.signoffs.service import CORRECTABLE_UNTIL, current

    db = world["db"]
    tom = as_user(f"tom.reyes@{ABC}")
    d = _get(tom, "/home/my-tasks")
    e = db.get(Engagement, d["engagement"]["id"])
    so = current(db, e, 4)
    before = (e.stage, so.status if so else None)
    try:
        e.stage = CORRECTABLE_UNTIL[4] + 1  # fieldwork complete: locked
        db.commit()
        assert _get(tom, "/home/my-tasks")["inventory_open"] is False
        e.stage = 2  # discovery, sign-off 4 not approved: open
        if so:
            so.status = "pending"
        db.commit()
        assert _get(tom, "/home/my-tasks")["inventory_open"] is True
    finally:
        e.stage = before[0]
        if so:
            so.status = before[1]
        db.commit()
