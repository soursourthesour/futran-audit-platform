"""The wave 3 WS-J demo step on top of the full demo seed: ABC Corp on the Monitor plan, two connected fake connectors,
an expense upload, discovered tools in every state, and a monitoring run with healthy, attention and failed checks."""
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    settings = Settings(database_url="sqlite://", mfa_required=False, email_mode="outbox", secret_key="test-secret-key-not-for-production-0123456789",
                        disable_scheduler=True, seed_on_start=False, file_store=f"local:{tmp_path_factory.mktemp('files')}", refresh_client="fake")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    import app.models_registry  # noqa: F401
    from app.cli import _futran_org
    from app.core.models import Base
    from app.demo.seed_demo import run
    from app.reference import LOADERS

    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, expire_on_commit=False)()
    _futran_org(db)
    for _name, loader in LOADERS:
        loader(db)
    db.commit()
    ids = run(db, settings)
    yield {"db": db, "ids": ids}
    db.close()
    eng.dispose()


def test_abc_is_on_the_monitor_plan_with_two_connected_connectors_and_an_expense_upload(world):
    from app.connectors.models import Connector, ConnectorRun
    from app.tenancy.models import Organization

    db, cid = world["db"], world["ids"]["abc"]
    assert db.get(Organization, cid).subscription_plan == "monitor"
    conns = {c.type: c for c in db.scalars(select(Connector).where(Connector.organization_id == cid))}
    assert conns["okta"].status == conns["google_workspace"].status == "connected"
    assert conns["okta"].token_encrypted and "demo-okta-secret" not in conns["okta"].token_encrypted
    assert db.scalar(select(ConnectorRun).where(ConnectorRun.connector_id == conns["expense_csv"].id, ConnectorRun.kind == "upload")).rows_matched == 9


def test_discovered_tools_are_in_every_state(world):
    from app.connectors import service as svc
    from app.tenancy.models import Organization

    db, cid = world["db"], world["ids"]["abc"]
    tools = svc.tools(db, db.get(Organization, cid))
    by = {(t["product"], t["source"]): t for t in tools}
    assert by[("ChatGPT", "expense_csv")]["status"] == "mapped" and by[("ChatGPT", "expense_csv")]["declared"]
    assert by[("Claude", "expense_csv")]["status"] == "confirmed"
    assert by[("Midjourney", "expense_csv")]["status"] == "dismissed" and by[("Midjourney", "expense_csv")]["dismiss_reason"]
    assert by[("Otter.ai", "google_workspace")]["status"] == "new" and not by[("Otter.ai", "google_workspace")]["declared"]
    assert by[("Otter.ai", "google_workspace")]["department"] == "Sales & Marketing" and by[("Otter.ai", "google_workspace")]["user_count"] == 11


def test_the_monitoring_run_has_healthy_attention_and_failed_checks(world):
    from app.monitoring import service as mon
    from app.tenancy.models import Organization

    db, cid = world["db"], world["ids"]["abc"]
    d = mon.dashboard(db, db.get(Organization, cid))
    assert d["kpis"]["healthy"] and d["kpis"]["attention"] and d["kpis"]["failed"]
    checks = {r["check_code"] for r in d["needs_action"]}
    assert {"undeclared_ai_tool", "vendor_soc2_expiring"} <= checks
    assert d["next_review_on"]
