"""11-10 U1/U3: one client list of AI systems. Register systems, inventory tools and agents, use cases and the systems in
the current audit come from one endpoint, scoped server-side exactly as the three screens it replaces were scoped."""
from sqlalchemy import func, select

from app.engagements.models import Engagement
from app.inventory.models import AITool, UseCase
from app.register.models import RegisterSystem
from app.systems.models import AISystem
from tests.factories import make_org, make_user
from tests.register.conftest import new_system


def _world(db, reg, client):
    """HR and Finance register systems, a company-wide one, inventory tools from each source, use cases in both departments
    and two systems in the current audit (one taken from the register)."""
    e = Engagement(organization_id=reg.org.id, client_id=reg.org.id, name="AI audit 2026", audit_ref="AUD-1", stage=3, status="active")
    db.add(e)
    db.flush()
    manual = AITool(organization_id=reg.org.id, vendor="TalentRank Inc.", product="TalentRank", account_type="enterprise")
    attested = AITool(organization_id=reg.org.id, vendor="Anthropic", product="Claude", account_type="personal_free", source="attestation", declared_count=3)
    found = AITool(organization_id=reg.org.id, vendor="Otter", product="Otter.ai", account_type="unknown", source="discovery")
    agent = AITool(organization_id=reg.org.id, vendor="HireBot Co.", product="Scheduler", account_type="enterprise", kind="agent")
    db.add_all([manual, attested, found, agent])
    db.flush()
    hr_uc = UseCase(organization_id=reg.org.id, engagement_id=e.id, name="Résumé ranking", department_id=reg.hr.id, tool_ids=[manual.id], data_categories=["pii"],
                    decision_impact="consequential", proposed_tier=3, status="submitted")
    fin_uc = UseCase(organization_id=reg.org.id, engagement_id=e.id, name="Invoice summaries", department_id=reg.fin.id, tool_ids=[attested.id], data_categories=["none"],
                     decision_impact="none", proposed_tier=2, status="draft")
    linked_uc = UseCase(organization_id=reg.org.id, engagement_id=e.id, name="Interview scheduling", department_id=reg.hr.id, tool_ids=[agent.id], data_categories=["none"],
                        decision_impact="none", proposed_tier=1, status="dept_approved")
    db.add_all([hr_uc, fin_uc, linked_uc])
    db.commit()
    reg.as_(reg.caico)
    hr_sys = new_system(client, name="Payroll anomaly model", type="in_house_model", sourcing="in_house", department_id=reg.hr.id)
    fin_sys = new_system(client, name="Invoice OCR", department_id=reg.fin.id)
    cw_sys = new_system(client, name="Company chatbot", company_wide=True)
    # the Scheduler agent was imported into the register: its system names the tool and the use case it came from
    sched = db.get(RegisterSystem, new_system(client, name="Scheduler", type="agent", sourcing="vendor", department_id=reg.hr.id)["id"])
    sched.origin, sched.source_refs = "inventory", [f"tool:{agent.id}", f"use_case:{linked_uc.id}"]
    a1 = AISystem(organization_id=reg.org.id, engagement_id=e.id, name="Payroll anomaly model", reference_id="SYS-001", department_id=reg.hr.id, register_system_id=hr_sys["id"])
    a2 = AISystem(organization_id=reg.org.id, engagement_id=e.id, name="Credit scoring", reference_id="SYS-002", department_id=reg.fin.id, tool_ids=[attested.id])
    db.add_all([a1, a2])
    db.commit()
    return dict(e=e, manual=manual, attested=attested, found=found, agent=agent, hr_uc=hr_uc, fin_uc=fin_uc, linked_uc=linked_uc,
                hr_sys=hr_sys, fin_sys=fin_sys, cw_sys=cw_sys, sched=sched, a1=a1, a2=a2)


def _rows(client):
    r = client.get("/api/v1/ai-systems")
    assert r.status_code == 200, r.text
    return r.json(), {x["key"]: x for x in r.json()["rows"]}


def test_caico_sees_one_list_of_everything(client, db, reg):
    w = _world(db, reg, client)
    reg.as_(reg.caico)
    body, rows = _rows(client)
    # register systems, inventory tools and agents, use cases and the audit-only system, each with a type and a source
    assert rows[f"system:{w['hr_sys']['id']}"]["type_label"] == "System" and rows[f"system:{w['hr_sys']['id']}"]["sources"] == ["register"]
    assert rows[f"tool:{w['manual'].id}"]["type_label"] == "Tool or agent" and rows[f"tool:{w['manual'].id}"]["sources"] == ["inventory"]
    assert rows[f"tool:{w['attested'].id}"]["sources"] == ["attestation"]
    assert rows[f"tool:{w['found'].id}"]["sources"] == ["discovery"]  # U3: confirmed discovered tools show as Discovery
    assert rows[f"use_case:{w['hr_uc'].id}"]["type_label"] == "Use case" and rows[f"use_case:{w['hr_uc'].id}"]["tier"] == 3
    assert rows[f"audit:{w['a2'].id}"]["sources"] == ["audit"] and rows[f"audit:{w['a2'].id}"]["registered"] is False
    # an imported system says where it came from; the tool and use case it came from fold into it
    assert rows[f"system:{w['sched'].id}"]["sources"] == ["inventory"]
    assert rows[f"tool:{w['agent'].id}"]["in_register_as"] == {"id": w["sched"].id, "name": "Scheduler"}
    assert rows[f"use_case:{w['linked_uc'].id}"]["in_register_as"] == {"id": w["sched"].id, "name": "Scheduler"}
    assert rows[f"tool:{w['manual'].id}"]["in_register_as"] is None and rows[f"tool:{w['manual'].id}"]["registered"] is False
    # the audit system taken from the register is on the register row, not a second row
    assert f"audit:{w['a1'].id}" not in rows
    hr = rows[f"system:{w['hr_sys']['id']}"]
    assert hr["in_audit"] is True and hr["audit"]["system_id"] == w["a1"].id and hr["audit"]["can_answer"] is True
    assert rows[f"system:{w['fin_sys']['id']}"]["in_audit"] is False
    assert rows[f"tool:{w['attested'].id}"]["in_audit"] is True  # Credit scoring in the audit uses it
    # the register's own grid data rides along for the register rows, and the screen's capabilities come with it
    assert hr["system"]["id"] == w["hr_sys"]["id"] and "roles" in hr["system"]
    assert body["register"]["can"]["import_inventory"] is True and body["inventory"]["can_add_tool"] is True and body["inventory"]["can_add_use_case"] is True
    assert body["audit"]["audit_ref"] == "AUD-1" and body["audit"]["can_answer_governance_questions"] is True
    assert rows[f"tool:{w['manual'].id}"]["can"]["approve_tool"] is True
    assert rows[f"tool:{w['attested'].id}"]["tool"]["declared_count"] == 3


def test_department_lead_sees_only_what_the_three_screens_showed(client, db, reg):
    w = _world(db, reg, client)
    reg.as_(reg.hr_lead)
    body, rows = _rows(client)
    keys = set(rows)
    # register: own department and company-wide (read-only); inventory: own department's use cases, every tool
    assert f"system:{w['hr_sys']['id']}" in keys and f"system:{w['cw_sys']['id']}" in keys and f"system:{w['fin_sys']['id']}" not in keys
    assert f"use_case:{w['hr_uc'].id}" in keys and f"use_case:{w['fin_uc'].id}" not in keys
    assert {f"tool:{w[k].id}" for k in ("manual", "attested", "found", "agent")} <= keys
    # audit: only the systems of their department
    assert f"audit:{w['a2'].id}" not in keys
    assert rows[f"use_case:{w['hr_uc'].id}"]["can"]["review_use_case"] is True
    assert rows[f"tool:{w['manual'].id}"]["can"]["approve_tool"] is False  # only the CAICO approves tools
    assert rows[f"tool:{w['attested'].id}"]["tool"]["declared_count"] is None  # declared counts are individual attestation data
    assert body["register"]["can"]["import_inventory"] is False
    reg.as_(reg.fin_lead)
    _, rows = _rows(client)
    assert f"audit:{w['a2'].id}" in rows and rows[f"audit:{w['a2'].id}"]["audit"]["can_answer"] is True


def test_roles_without_the_register_see_no_register_rows(client, db, reg):
    w = _world(db, reg, client)
    sponsor = make_user(db, reg.org, roles=["exec_sponsor"], name="Eve Sponsor", email="eve@abc.test")
    db.commit()
    for who in (reg.contrib, sponsor):
        reg.as_(who)
        body, rows = _rows(client)
        assert not any(k.startswith("system:") for k in rows), who.name
        assert body["register"] is None
        # with no register to compare against, nothing claims to be registered or folded away
        assert rows[f"tool:{w['agent'].id}"]["registered"] is None and rows[f"tool:{w['agent'].id}"]["in_register_as"] is None
    assert body["inventory"]["can_add_tool"] is False and body["inventory"]["can_add_use_case"] is False  # the sponsor only reads
    reg.as_(reg.contrib)
    _, rows = _rows(client)
    assert f"use_case:{w['hr_uc'].id}" in rows and f"use_case:{w['fin_uc'].id}" not in rows
    # the HR contributor answers the HR system's audit questions: it shows as an audit row, since they cannot see the register
    assert rows[f"audit:{w['a1'].id}"]["audit"]["can_answer"] is True and f"audit:{w['a2'].id}" not in rows


def test_client_admin_sees_the_register_but_no_inventory(client, db, reg):
    w = _world(db, reg, client)
    reg.as_(reg.admin)
    body, rows = _rows(client)
    assert f"system:{w['fin_sys']['id']}" in rows
    assert not any(k.startswith(("tool:", "use_case:", "audit:")) for k in rows)
    assert body["inventory"] is None
    # the audit's systems were only ever shown to those who pre-fill them: the list says nothing about the audit to the Client Admin
    assert rows[f"system:{w['hr_sys']['id']}"]["audit"] is None and rows[f"system:{w['hr_sys']['id']}"]["in_audit"] is None


def test_no_access_and_futran_and_other_tenants(client, db, reg):
    w = _world(db, reg, client)
    reg.as_(reg.hr_user)
    assert client.get("/api/v1/ai-systems").status_code == 403
    futran = make_org(db, type="futran", name="Futran")
    aud = make_user(db, futran, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    other = make_org(db, name="Other Co")
    olga = make_user(db, other, roles=["caico"], name="Olga", email="olga@other.test")
    db.commit()
    reg.as_(aud)
    assert client.get("/api/v1/ai-systems").status_code == 404
    reg.as_(olga)
    r = client.get("/api/v1/ai-systems")
    assert r.status_code == 200 and r.json()["rows"] == []
    assert w["hr_sys"]["id"] not in r.text


def test_reading_the_list_converts_nothing(client, db, reg):
    _world(db, reg, client)
    counts = lambda: tuple(db.scalar(select(func.count()).select_from(m)) for m in (RegisterSystem, AITool, UseCase, AISystem))  # noqa: E731
    before = counts()
    reg.as_(reg.caico)
    _rows(client)
    db.expire_all()
    assert counts() == before


def test_a_confirmed_discovered_tool_is_in_the_list_as_discovery(client, db, reg, settings):
    """U3: confirming a discovered tool adds it to the AI inventory (source discovery); it is not put in the register."""
    from app.connectors import service as cs
    from app.connectors.models import Connector, DiscoveredTool
    from app.core.clock import utcnow

    e = Engagement(organization_id=reg.org.id, client_id=reg.org.id, name="AI audit 2026", audit_ref="AUD-1", stage=3, status="active")
    c = Connector(organization_id=reg.org.id, type="google_workspace", status="connected")
    db.add_all([e, c])
    db.flush()
    t = DiscoveredTool(organization_id=reg.org.id, connector_id=c.id, vendor_key="perplexity", vendor="Perplexity", product="Perplexity", signal="sso_app",
                       department_id=reg.hr.id, department_key=reg.hr.id, user_count=4, first_seen=utcnow(), last_seen=utcnow())
    db.add(t)
    db.commit()
    cs.confirm(db, settings, reg.caico, reg.org, t.id)
    db.commit()
    tool = db.scalar(select(AITool).where(AITool.product == "Perplexity"))
    assert (tool.source, tool.approval_status, tool.account_type) == ("discovery", "unreviewed", "enterprise")
    assert db.scalar(select(func.count()).select_from(RegisterSystem)) == 0
    reg.as_(reg.caico)
    _, rows = _rows(client)
    row = rows[f"tool:{tool.id}"]
    assert row["sources"] == ["discovery"] and row["registered"] is False and row["stage_label"] == "Unreviewed"


def test_the_system_record_opens_its_audit_questions(client, db, reg):
    """The audit's questions for a register system in the current audit open from its record, for those who answer them."""
    w = _world(db, reg, client)
    reg.as_(reg.hr_lead)
    r = client.get(f"/api/v1/register/{w['hr_sys']['id']}").json()
    assert r["audit"] == {"system_id": w["a1"].id, "reference_id": "SYS-001", "can_answer": True}
    assert client.get(f"/api/v1/register/{w['fin_sys']['id']}").status_code == 404
    reg.as_(reg.caico)
    assert client.get(f"/api/v1/register/{w['fin_sys']['id']}").json()["audit"] is None
    reg.as_(reg.admin)
    assert client.get(f"/api/v1/register/{w['hr_sys']['id']}").json()["audit"] is None
