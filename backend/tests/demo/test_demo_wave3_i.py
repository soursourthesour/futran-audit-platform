"""WS-I demo data (policy builder 27, training 33, Trust Center 32) on top of the full demo seed."""
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


def _as(world, email):
    from app.tenancy.models import User
    from tests.factories import login_as

    db = world["db"]
    c = TestClient(world["app"])
    return login_as(c, db, db.scalar(select(User).where(User.email == email)))


def _get(c, path):
    r = c.get(f"/api/v1{path}")
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    return r.json()


def test_acceptable_use_policy_published_with_acknowledgments(world):
    c = _as(world, f"maria.lopez@{ABC}")
    pols = {p["template"]["code"]: p for p in _get(c, "/policies")["policies"]}
    aup = pols["acceptable_use"]
    assert aup["status"] == "published" and aup["review_due"]
    acks = aup["acknowledgments"]
    assert acks["sent"] >= 10 and 0 < acks["acknowledged"] < acks["sent"]
    detail = _get(c, f"/policies/{aup['id']}")
    assert any("ScreenRank" in " ".join(b.get("items") or []) for b in detail["blocks"]) and detail["edited"]
    assert pols["human_oversight"]["status"] == "awaiting_approval" and pols["human_oversight"]["futran_review_requested_at"]
    assert pols["model_change_management"]["status"] == "draft"


def test_training_completion_by_department_is_realistic(world):
    c = _as(world, f"maria.lopez@{ABC}")
    ov = _get(c, "/training")
    depts = {d["name"]: d for d in ov["departments"]}
    assert depts["HR"]["pct"] >= 80 and depts["Sales & Marketing"]["below_target"] is True
    assert ov["program"]["target_pct"] == 80 and ov["program"]["evidence"]
    assert sum(m["assigned"] > 0 for m in ov["modules"]) == 4


def test_trust_center_live_with_confirmed_items(world):
    pub = TestClient(world["app"]).get("/api/v1/public/trust/abc-corp")
    assert pub.status_code == 200 and pub.headers["x-robots-tag"] == "noindex"
    kinds = {i["kind"] for i in pub.json()["items"]}
    assert {"badge", "commitment", "policy", "governance"} <= kinds and "rights_contact" not in kinds
    chief = _as(world, "chief@futran.demo")
    queue = _get(chief, "/trust/confirmations")["items"]
    assert [i["kind"] for i in queue] == ["rights_contact"]
    editor = _get(_as(world, f"maria.lopez@{ABC}"), "/trust")
    assert sum(v["views"] for v in editor["views"]) > 100
