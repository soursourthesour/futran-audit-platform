"""WS-K demo step on top of the full demo seed: the bias run matches ABC's published summary, the heat map and lineage
read ABC's audit, benchmarking shows peer figures without naming anyone, and an annual review carries answers forward."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

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


def test_the_bias_run_reproduces_the_published_summary(world, as_user):
    from app.biascalc.models import BiasTestRun
    from app.reports.models import PublicSummary

    db = world["db"]
    run = db.get(BiasTestRun, world["ids"]["bias_run"])
    summary = db.scalar(select(PublicSummary).where(PublicSummary.engagement_id == run.engagement_id))
    out = _get(as_user("auditor1@futran.demo"), f"/bias-tests/{run.id}")
    cats = {(t, c["label"]): c for t, title in (("sex", "Sex"), ("race", "Race/ethnicity")) for c in out["results"]["tables"][t]["categories"]}
    for row in summary.impact_ratios:
        t = "sex" if row["category"] == "Sex" else "race"
        label = row["group"] if t == "sex" or row["group"] == "Hispanic or Latino" else f"{row['group']} (not Hispanic or Latino)"
        c = cats[(t, label)]
        assert (round(c["rate"], 2), round(c["impact_ratio"], 2)) == (row["selection_rate"], row["impact_ratio"]), row
    assert out["unknown_count"] == summary.unknown_category_count == 112 and out["unknown_pct"] == 18.0
    assert out["lowest"]["label"] == "Hispanic or Latino" and round(out["lowest"]["impact_ratio"], 2) == 0.84
    assert out["excluded_categories"] == ["race:asian", "intersectional:asian|female"]
    assert out["data_source"] == summary.data_source


def test_heat_map_and_lineage_read_abcs_audit(world, as_user):
    c = as_user("chief@futran.demo")
    hm = _get(c, f"/clients/{world['ids']['abc']}/heatmap")
    sys1 = next(s for s in hm["systems"] if s["reference_id"] == "SYS-001")
    assert sys1["final_rating"] == "high" and sys1["provisional"] is False and sys1["column"] == 3 and sys1["row"] == "2"
    approved = [f for f in hm["findings"] if f["status"] == "approved"]
    assert approved and hm["findings_grid"]["total"] >= len(approved)
    bias = next(f for f in approved if "bias testing" in f["title"].lower())
    ln = _get(c, f"/findings/{bias['id']}/lineage")
    assert any(o["regulation"].startswith("NYC") or "144" in o["regulation"] for o in ln["obligations"])
    assert ln["remediation"] and ln["responses"][0]["code"] == "6.2.01"
    png = c.get(f"/api/v1/clients/{world['ids']['abc']}/heatmap.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_benchmarking_shows_peer_figures_without_names(world, as_user):
    chief = as_user("chief@futran.demo")
    out = _get(chief, f"/insights/clients/{world['ids']['abc']}")
    assert out["group"] == {"label": "Staffing and recruitment, 250–999 employees", "n": 7}
    bias = next(d for d in out["domains"] if d["key"] == "bias")
    assert bias["peer_median"] == 2.5 and bias["below_peers"] is True
    assert "Demo peer" not in json.dumps(out)
    assert [x["name"] for x in _get(chief, "/insights/clients")["clients"]] == ["ABC Corp"]
    practice = json.dumps(_get(as_user("sales@futran.demo"), "/insights/practice"))
    assert "ABC" not in practice and "Demo peer" not in practice and "domain_scores" not in practice


def test_the_annual_review_carries_answers_and_leaves_abcs_audit_current(world, as_user):
    from app.engagements.models import Engagement

    db = world["db"]
    new = db.get(Engagement, world["ids"]["annual_review"])
    assert new.type == "annual_review" and new.status == "draft" and new.prior_engagement_id
    carried = _get(as_user("chief@futran.demo"), f"/engagements/{new.id}/carried")
    assert carried["counts"]["total"] > 20 and carried["counts"]["pending"] == carried["counts"]["total"]
    report = _get(as_user(f"maria.lopez@{ABC}"), "/me/systems")
    assert report["engagement"]["id"] == new.prior_engagement_id  # the client still sees the completed audit
