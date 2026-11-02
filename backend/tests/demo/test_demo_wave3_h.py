"""WS-H demo step on top of the full demo seed: screen 26 has published, awaiting-review and watch items with ABC Corp's
impact and upcoming dates; screen 28 has an approved project with conditions and one in review; a register edit raised a
reassessment trigger."""
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
    from app.demo import wave3

    steps = wave3.STEPS
    wave3.STEPS = steps[: steps.index("wave3_h") + 1]  # this step on top of the earlier seed; later steps have their own tests
    try:
        ids = run(db, settings)
    finally:
        wave3.STEPS = steps
    yield {"db": db, "app": create_app(settings, engine=eng), "ids": ids}
    db.close()
    eng.dispose()


@pytest.fixture
def as_user(world):
    from app.tenancy.models import User
    from tests.factories import login_as

    clients = []

    def _as(email: str) -> TestClient:
        c = TestClient(world["app"])
        clients.append(c)
        u = world["db"].scalar(select(User).where(User.email == email))
        assert u is not None, email
        return login_as(c, world["db"], u)

    yield _as
    for c in clients:
        c.close()


def _get(c: TestClient, path: str):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    return r.json()


def test_screen_26_has_published_awaiting_review_and_watch_items(world, as_user):
    d = _get(as_user("chief@futran.demo"), "/reg/updates")
    mine = {r["id"]: r for r in d["rows"] if r["kind"] == "update"}
    nyc, ca, watch = mine[world["ids"]["reg_update_nyc"]], mine[world["ids"]["reg_update_ca"]], mine[world["ids"]["reg_update_watch"]]
    assert nyc["status"] == "published" and "ABC Corp" in [c["name"] for c in nyc["clients"]]
    assert ca["status"] == "awaiting_review" and ca["verify_note"]
    assert watch["watch"] is True and watch["client_count"] == 0
    assert d["counts"]["awaiting_review"] >= 1


def test_impact_for_abc_lists_the_screening_system_and_the_alert_waits_for_approval(world, as_user):
    from app.clientalerts.models import AlertRule, AlertSend

    c = as_user("chief@futran.demo")
    imp = _get(c, f"/reg/updates/{world['ids']['reg_update_nyc']}/impact/{world['ids']['abc']}")
    assert any("ScreenRank" in s["name"] for s in imp["systems"]) and imp["alert_status"] == "waiting_approval"
    db = world["db"]
    s = db.scalar(select(AlertSend).join(AlertRule, AlertRule.id == AlertSend.alert_rule_id).where(AlertRule.trigger == "regulatory_update"))
    assert s.organization_id == world["ids"]["abc"] and s.status == "waiting_approval"
    assert _get(c, f"/reg/updates/calendar?organization_id={world['ids']['abc']}")["rows"] is not None


def test_abc_sees_what_it_means_and_its_projects(world, as_user):
    c = as_user(f"maria.lopez@{ABC}")
    items = _get(c, "/updates")["items"]
    assert any(i["id"] == world["ids"]["reg_update_nyc"] for i in items)
    rows = {r["id"]: r for r in _get(c, "/projects")["rows"]}
    ok, review = rows[world["ids"]["project_approved"]], rows[world["ids"]["project_in_review"]]
    assert ok["decision"] == "approved_with_conditions" and ok["register_system_id"] and ok["open_conditions"] == 2
    assert review["status"] == "in_review" and review["proposed_tier"] == 3 and review["opinion_opportunity_id"]
    p = _get(c, f"/projects/{ok['id']}")
    assert p["register_system"]["stage"] == "proposed" and [x["status"] for x in p["conditions"]] == ["met", "open"]
    assert any(law["matched"] and "Local Law 144" in law["name"] for law in _get(c, f"/projects/{review['id']}")["matched_regulations"])


def test_the_register_edit_raised_a_version_trigger_and_the_update_one_on_the_screening_system(world, as_user):
    c = as_user(f"maria.lopez@{ABC}")
    rows = _get(c, f"/register/{world['ids']['trigger_system']}/triggers")["rows"]
    version = [r for r in rows if (r["type"], r["source"]) == ("version_change", "register_edit")]
    assert len(version) == 1 and "2.3" in version[0]["detail"] and "2.4" in version[0]["detail"]
    home = _get(c, "/reassessment")["rows"]
    assert {"version_change", "regulatory_update"} <= {r["type"] for r in home}
