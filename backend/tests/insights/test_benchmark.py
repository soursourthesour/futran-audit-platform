"""Benchmarking (F15, screen 34): peer figures only for groups of at least five consenting clients, never a client's name
or exact score outside its own view, and the practice view for Sales without client names."""
import json

from sqlalchemy import select

from app.insights import benchmark
from app.insights.models import BenchmarkSnapshot
from tests.factories import login_as, make_org, make_user

DOMAINS = ["governance", "data", "model", "bias", "oversight", "security", "incident", "vendor_risk"]


def peer(db, name, *, consent=True, industry="staffing", band="250-999", bias=2.0, themes=("no_bias_audit",)):
    org = make_org(db, name=name, industry=industry, employee_band=band)
    org.benchmark_consent = consent
    db.add(BenchmarkSnapshot(organization_id=org.id, industry=industry, size_band=band, consent=consent, domain_scores={d: 3.0 for d in DOMAINS} | {"bias": bias},
                             overall_maturity=2.8, overall_rating="high", finding_themes=list(themes)))
    db.flush()
    return org


def test_median_and_threshold_are_plain_functions():
    assert benchmark.median([1.0, 3.0, 2.0]) == 2.0 and benchmark.median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert benchmark.MIN_PEERS == 5


def test_no_peer_figure_until_five_consenting_peers_and_non_consenting_clients_never_count(client, db, people):
    me = peer(db, "Subject Co", bias=1.0)
    for i in range(4):
        peer(db, f"Peer {i}", bias=2.0 + i)
    peer(db, "Refused Co", consent=False, bias=5.0)
    db.commit()
    out = benchmark.comparison(db, me)
    assert out["group"] is None and out["domains"][0]["peer_median"] is None
    assert out["groups_considered"] == [{"label": "Staffing and recruitment, 250–999 employees", "n": 4, "shown": False}, {"label": "Staffing and recruitment", "n": 4, "shown": False},
                                        {"label": "250–999 employees", "n": 4, "shown": False}, {"label": "All consenting clients", "n": 4, "shown": False}]
    peer(db, "Peer 4", bias=4.0)
    db.commit()
    out = benchmark.comparison(db, me)
    assert out["group"] == {"label": "Staffing and recruitment, 250–999 employees", "n": 5}
    bias = next(d for d in out["domains"] if d["key"] == "bias")
    assert bias == {"key": "bias", "label": "Bias, fairness and ethics", "client": 1.0, "peer_median": 4.0, "below_peers": True}  # median of 2, 3, 4, 5, 4
    assert "Peer" not in json.dumps(out)


def test_a_broader_group_is_used_when_the_narrow_one_is_too_small(client, db, people):
    me = peer(db, "Subject Co")
    for i in range(3):
        peer(db, f"Same {i}")
    for i in range(2):
        peer(db, f"Bigger {i}", band="1000+")
    db.commit()
    assert benchmark.comparison(db, me)["group"] == {"label": "Staffing and recruitment", "n": 5}


def test_a_client_that_has_not_consented_sees_no_comparison(client, db, people):
    me = peer(db, "Private Co", consent=False)
    for i in range(6):
        peer(db, f"Peer {i}")
    db.commit()
    out = benchmark.comparison(db, me)
    assert out["group"] is None and out["note"] == "This client has not consented to benchmarking in its engagement letter, so it is not compared with peers."


def test_the_chief_auditors_screen_names_only_the_subject_and_sales_sees_only_the_practice_view(client, db, people):
    me = peer(db, "Subject Co", bias=1.0)
    names = [f"Confidential Peer {i}" for i in range(6)]
    exact = [2.11, 2.17, 2.29, 2.31, 2.43, 2.47]
    for i, n in enumerate(names):
        peer(db, n, bias=exact[i], themes=("no_bias_audit", "no_ai_policy") if i % 2 else ("no_ai_policy",))
    sales = make_user(db, make_org(db, type="futran", name="Futran"), roles=["sales_team"], name="Sam Seller", email="sam@futran.test")
    db.commit()
    login_as(client, db, people["chief"])
    r = client.get(f"/api/v1/insights/clients/{me.id}")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Subject Co" in body and not any(n in body for n in names)
    assert not any(str(x) in body for x in exact)  # no peer's own score
    assert next(d for d in r.json()["domains"] if d["key"] == "bias")["peer_median"] == 2.3  # (2.29 + 2.31) / 2
    practice = client.get("/api/v1/insights/practice").json()
    assert practice["clients"] == 7
    top = practice["themes"][0]
    assert top["code"] == "no_ai_policy" and top["clients"] == 6 and top["service"]
    login_as(client, db, sales)
    assert client.get(f"/api/v1/insights/clients/{me.id}").status_code in (403, 404)
    p = client.get("/api/v1/insights/practice")
    assert p.status_code == 200
    text = json.dumps(p.json())
    assert "Subject Co" not in text and not any(n in text for n in names) and "domain_scores" not in text
    assert client.get("/api/v1/insights/clients").status_code in (403, 404)


def test_practice_view_is_hidden_below_five_consenting_clients(client, db, people):
    for i in range(4):
        peer(db, f"Peer {i}")
    peer(db, "No consent", consent=False)
    db.commit()
    out = benchmark.practice(db)
    assert out["clients"] == 4 and out["themes"] == [] and out["note"] == "Shown when at least 5 clients have consented to benchmarking."


def test_snapshot_is_taken_from_the_scorecard_and_findings_at_final_sign_off(client, db, ats, people):
    from app.findings.service import create_finding
    from app.reports import register as _reports_register  # noqa: F401
    from app.insights import register as _insights_register  # noqa: F401
    from app.scoring.service import engagement_rollup
    from app.signoffs import service as so_svc
    from app.tenancy.models import Organization

    cid, e, maria, s = ats
    assert benchmark.snapshot_on_signoff in so_svc.ON_APPROVED[7]
    f = create_finding(db, people["aud"], e, {"title": "No bias testing", "severity": "high", "template_section": "6.2", "source_question_ids": ["6.2.01"]})
    f.status = "approved"
    org = db.get(Organization, cid)
    org.benchmark_consent, org.industry, org.employee_band = True, "staffing", "250-999"
    engagement_rollup(db, e)
    snap = benchmark.record_snapshot(db, e)
    assert snap.consent is True and snap.industry == "staffing" and snap.size_band == "250-999"
    assert "no_bias_audit" in snap.finding_themes
    assert benchmark.record_snapshot(db, e).id == snap.id  # one per engagement, recomputed


def test_consent_is_recorded_by_the_chief_auditor(client, db, ats, people):
    from app.audit_log.models import AuditLog
    from app.tenancy.models import Organization

    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    assert client.put(f"/api/v1/insights/clients/{cid}/consent", json={"consent": True}).status_code in (403, 404)
    login_as(client, db, people["chief"])
    r = client.put(f"/api/v1/insights/clients/{cid}/consent", json={"consent": True, "note": "Clause 14 of the signed engagement letter."})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Organization, cid).benchmark_consent is True
    assert db.scalar(select(AuditLog).where(AuditLog.action == "benchmark.consent")) is not None
