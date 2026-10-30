"""The demo seed fills every v0.4–v0.6.1 screen (register, regulatory master, refresh, email, litigation, sales, alerts,
tracing and role homes) with data that obeys the platform's own rules. One demo world per module: the seed takes about a minute."""
from collections import Counter
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings

ABC = "abccorp.example"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    settings = Settings(database_url="sqlite://", mfa_required=False, email_mode="outbox", secret_key="test-secret-key-not-for-production-0123456789",
                        disable_scheduler=True, seed_on_start=False, file_store=f"local:{tmp_path_factory.mktemp('files')}", refresh_client="anthropic")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    import app.models_registry  # noqa: F401
    from app.cli import _futran_org
    from app.core.models import Base
    from app.demo.seed_demo import run
    from app.main import create_app
    from app.reference import LOADERS

    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, expire_on_commit=False)()
    _futran_org(db)
    for _name, loader in LOADERS:
        loader(db)
    db.commit()
    ids = run(db, settings)
    app = create_app(settings, engine=eng)
    yield {"db": db, "app": app, "ids": ids}
    db.close()
    eng.dispose()


@pytest.fixture
def as_user(world):
    from app.tenancy.models import User
    from tests.factories import login_as

    clients = []

    def _as(email: str) -> TestClient:
        db = world["db"]
        c = TestClient(world["app"])
        clients.append(c)
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None, email
        return login_as(c, db, u)

    yield _as
    for c in clients:
        c.close()


def _get(c: TestClient, path: str):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    return r.json()


def test_register_has_a_realistic_mix_and_respects_the_go_live_gate(world, as_user):
    reg = _get(as_user(f"maria.lopez@{ABC}"), "/register")
    systems = reg["systems"]
    assert 8 <= len(systems) <= 12
    assert {"proposed", "in_development", "live", "retired"} <= {s["stage"] for s in systems}
    assert {s["department"]["name"] for s in systems if s["department"]} == {"HR", "Finance", "Sales & Marketing"}
    for s in systems:  # §24.3: a live system either passes the gate or shows the finding
        if s["stage"] == "live":
            assert s["gate"]["state"] in ("live_clear", "live_finding"), s["reference"]
            assert s["go_live"]["approved_by"] is not None, s["reference"]
    assert any(s["gate"]["label"] == "Live · finding raised" for s in systems)
    assert any(s["gate"]["state"] == "blocked" for s in systems)
    assert sum(s["roles"]["no_such_person"] for s in systems) >= 1 and sum(s["roles"]["pending_committee"] for s in systems) >= 1  # "Show only gaps"
    assert reg["kpis"]["roles_no_person"] >= 1 and reg["kpis"]["go_live_blocked"] >= 1


def test_register_history_committee_and_requirements(world, as_user):
    maria = as_user(f"maria.lopez@{ABC}")
    systems = {s["reference"]: s for s in _get(maria, "/register")["systems"]}
    committee = _get(maria, "/governance/committee")
    assert committee["committee"]["status"] == "formed" and any(m["committee_role"] == "chair" for m in committee["members"])
    company = _get(maria, "/governance/company-roles")
    assert Counter(r["status"] for r in company["rows"])["assigned"] >= 6
    kinds, statements = set(), []
    for s in systems.values():
        h = _get(maria, f"/register/{s['id']}/history")
        kinds |= {e["type"] for e in h["entries"]}
        if h["statement"] and h["statement"]["signed_at"]:
            statements.append(h["statement"])
    assert {"bias_test", "incident"} <= kinds
    assert len(statements) == 1 and statements[0]["signed_by"] == statements[0]["owner"]
    reqs = _get(maria, f"/register/{systems['AIS-001']['id']}/requirements")
    assert reqs["total"] >= 8 and reqs["met"] >= 8 and reqs["blocking"] == 0
    assert any(r["history_entries"] for r in reqs["rows"])


def test_fieldwork_systems_link_to_the_register(world):
    from app.register.models import RegisterSystem
    from app.systems.models import AISystem

    db = world["db"]
    rows = list(db.scalars(select(AISystem).where(AISystem.organization_id == world["ids"]["abc"])))
    assert {s.reference_id for s in rows if s.register_system_id} == {"SYS-001", "SYS-002", "SYS-003", "SYS-004"}
    for s in rows:
        assert db.get(RegisterSystem, s.register_system_id).organization_id == s.organization_id


def test_applicability_letters_and_geographies(world, as_user):
    chief = as_user("chief@futran.demo")
    abc = _get(chief, f"/clients/{world['ids']['abc']}/applicability")
    assert len(abc["geographies"]) >= 4 and any(g["jurisdiction_code"] == "IN-MH" for g in abc["geographies"])
    assert any("LL144" in law["label"] for law in abc["laws_in"])
    assert abc["letter"]["status"] == "sent" and abc["letter"]["file_id"]
    meridian = _get(chief, f"/clients/{world['ids']['meridian']}/applicability")
    assert meridian["letter"]["status"] == "draft"


def test_refresh_run_queue_and_staff_alert(world, as_user):
    from app.regmaster.models import ProposedChange, Requirement

    chief = as_user("chief@futran.demo")
    runs = _get(chief, "/admin/laws/refresh")
    run = next(r for r in runs if not r["legacy"])
    assert run["status"] == "completed" and run["total"] >= 4 and "no network" in run["model_id"]
    q = _get(chief, "/reg/changes?status=all")
    assert {"pending", "held", "approved", "legal_review"} <= {c["status"] for c in q["items"]}
    alerts = _get(chief, "/staff/alerts")
    assert alerts["needs_action"] >= 1
    # every proposed change quotes a source already recorded on an approved requirement, from the same page: nothing is invented
    db = world["db"]
    known = {(r.source_quote, r.source_url) for r in db.scalars(select(Requirement))}
    known_quotes = {q for q, _ in known}
    for c in db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run["id"])):
        assert c.source_quote in known_quotes, c.summary
    assert _get(as_user("qa@futran.demo"), "/reg/changes")["counts"]["open"] >= 3


def test_email_groups_send_and_log(world, as_user):
    admin = as_user("admin@futran.demo")
    futran = _get(admin, "/mail/groups?owner=futran")
    assert {"AuditTeam", "ChiefAuditors", "QAReviewers"} <= {g["name"] for g in futran["groups"]}
    sam = as_user(f"sam.okafor@{ABC}")
    groups = {g["system_key"]: g for g in _get(sam, "/mail/groups")["groups"] if g["system_key"]}
    assert {"ai_compliance_team", "dept_heads", "all_employees", "committee"} <= set(groups) and groups["ai_compliance_team"]["member_count"] >= 3
    maria = as_user(f"maria.lopez@{ABC}")
    send = next(s for s in _get(maria, "/mail/log/sends")["sends"] if s["template_key"] == "training_ai_literacy")
    detail = _get(maria, f"/mail/log/sends/{send['id']}")
    statuses = Counter(r["status"] for r in detail["recipients"])
    assert statuses["completed"] >= 5 and statuses["bounced"] == 1 and statuses["sent"] + statuses["opened"] >= 3
    assert len(_get(admin, "/mail/log/admin")["entries"]) >= 5
    from app.mail.models import MailConnection

    assert world["db"].scalar(select(MailConnection).where(MailConnection.status == "connected")) is None  # no mailbox connected: test mode only


def test_litigation_and_opportunities(world, as_user):
    from app.sales.models import Opportunity

    sales = as_user("sales@futran.demo")
    cases = _get(sales, "/litigation")["items"]
    assert len(cases) >= 5 and any(c["clients_count"] for c in cases)
    opps = _get(sales, "/opportunities")["items"]
    prospects = [o for o in opps if o["organization_id"] in (world["ids"]["meridian"], world["ids"]["northwind"]) and o["trigger"] == "manual"]
    assert len(prospects) >= 2 and len({o["stage"] for o in prospects}) >= 2
    assert {o["stage"] for o in opps if o["trigger"] == "unlock_request"} == {"won", "new"}  # one add-on approved by the sponsor, one waiting
    db = world["db"]
    assert db.scalar(select(Opportunity).where(Opportunity.organization_id == world["ids"]["abc"], Opportunity.service_kind == "remediation")) is None


def test_client_alerts_one_waiting_one_sent(world, as_user):
    chief = as_user("chief@futran.demo")
    items = [i for g in _get(chief, "/alerts/queue?status=waiting_approval,sent")["groups"] for i in g["items"]]
    st = Counter(i["status"] for i in items)
    assert st["waiting_approval"] >= 1 and st["sent"] >= 1


def test_tracing_addon_traces_and_incidents(world, as_user):
    from app.core.clock import utcnow

    maria = as_user(f"maria.lopez@{ABC}")
    systems = {s["reference"]: s for s in _get(maria, "/register")["systems"]}
    t = _get(maria, f"/register/{systems['AIS-007']['id']}/tracing")
    assert t["state"] == "active" and t["kpis"]["total"] >= 20 and t["traces"]
    by = {i["status"]: i for i in t["incidents"]}
    open_inc = next(i for i in t["incidents"] if i["status"] != "closed")
    due = [d for d in open_inc["deadlines"] if d["status"] == "open"]
    assert due and datetime.fromisoformat(due[0]["due_at"]) > utcnow()
    assert any(d["status"] == "done" for d in by["closed"]["deadlines"])
    requests = _get(as_user(f"robert.chen@{ABC}"), "/addons/tracing")["requests"]
    assert Counter(r["status"] for r in requests) == {"active": 1, "requested": 1}


def test_every_role_has_a_user_and_a_home_with_content(world, as_user):
    from app.policy.roles import CLIENT_ROLES, FUTRAN_ROLES
    from app.tenancy.models import RoleAssignment, User

    db = world["db"]
    held = {r.role for r in db.scalars(select(RoleAssignment).join(User, User.id == RoleAssignment.user_id).where(
        RoleAssignment.deleted_at.is_(None), User.status == "active", User.password_hash.is_not(None)))}
    assert {str(r) for r in FUTRAN_ROLES | CLIENT_ROLES} <= held
    assert db.scalar(select(User).where(User.email == "sales@futran.demo")).status == "active"
    assert len(_get(as_user("qa@futran.demo"), "/home/qa")["findings"]) >= 1
    assert _get(as_user("admin@futran.demo"), "/home/admin")["pending_proposals"] >= 3
    for email in ("auditor1@futran.demo", "em@futran.demo", "legal@futran.demo"):
        assert _get(as_user(email), "/home/my-work")["engagements"], email
    assert _get(as_user("sales@futran.demo"), "/opportunities")["items"]
    dept = _get(as_user(f"priya.shah@{ABC}"), "/home/department")["departments"][0]
    assert dept["register"]["total"] >= 5 and dept["register"]["live"] >= 3
    assert _get(as_user(f"sam.okafor@{ABC}"), "/home/client-admin")["users"]["active"] >= 10
    assert _get(as_user(f"robert.chen@{ABC}"), "/home/sponsor")["findings"]["total"] >= 1
    assert _get(as_user(f"daniel.kim@{ABC}"), "/home/dpo")["use_cases"]
    assert _get(as_user(f"tom.reyes@{ABC}"), "/home/my-tasks")["entries"]
