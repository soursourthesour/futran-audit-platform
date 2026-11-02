"""Screen 29: running the bias calculator on a system, who may do it, and what each run feeds."""
from datetime import timedelta

from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.biascalc.models import BiasTestRun
from app.biascalc.stats import LIBRARY_VERSION
from app.files.models import FileObject
from tests.factories import login_as


def run(client, sid, data: bytes, filename="applicants.csv", **form):
    fields = {"method": "selection_rate", "data_source": "Historical applicant data for New York roles, January to June."} | {k: str(v) for k, v in form.items()}
    return client.post(f"/api/v1/systems/{sid}/bias-tests", files={"file": (filename, data, "text/csv")}, data=fields)


def test_auditor_runs_the_calculator_and_the_run_is_kept_with_its_file_in_the_client_tenant(client, db, ats, people, small_csv):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    r = run(client, s.id, small_csv)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["method"] == "selection_rate" and out["library_version"] == LIBRARY_VERSION
    assert out["results"]["total"] == 200 and out["unknown_count"] == 20
    race = {c["key"]: c for c in out["results"]["tables"]["race"]["categories"]}
    assert race["white"]["impact_ratio"] == 1.0 and round(race["hispanic_latino"]["impact_ratio"], 2) == 0.75 and race["hispanic_latino"]["below_threshold"]
    assert out["lowest"] == {"dimension": "intersectional", "key": "hispanic_latino|female", "label": "Hispanic or Latino female", "impact_ratio": 0.5}
    row = db.get(BiasTestRun, out["id"])
    f = db.get(FileObject, row.dataset_file_id)
    assert f.organization_id == cid and f.engagement_id == e.id and f.linked_type == "bias_dataset" and f.linked_id == row.id
    assert row.run_by == people["aud"].id and row.organization_id == cid
    assert db.scalar(select(AuditLog).where(AuditLog.action == "bias_test.run", AuditLog.object_id == row.id)) is not None
    listed = client.get(f"/api/v1/systems/{s.id}/bias-tests").json()
    assert [x["id"] for x in listed["runs"]] == [row.id]
    assert listed["settings"] == {"threshold": 0.8, "small_share": 0.02, "exclude_small": True}


def test_invalid_data_is_refused_with_the_validation_report_and_nothing_is_stored(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    r = run(client, s.id, b"id,selected,sex,race\n1,yes,male,white\n2,perhaps,female,white\n")
    assert r.status_code == 422
    assert r.json()["errors"][0] == {"row": 3, "field": "selected", "message": "Row 3: enter selected as yes or no."}
    assert db.scalar(select(BiasTestRun)) is None
    r = run(client, s.id, b"id,selected,sex,race\n1,yes,male,white\n", method="scoring_rate")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "method"


def test_only_the_engagement_team_runs_it_and_the_client_cannot_see_runs(client, db, ats, people, small_csv):
    cid, e, maria, s = ats
    login_as(client, db, people["aud2"])  # an auditor not on this engagement
    assert run(client, s.id, small_csv).status_code == 404
    login_as(client, db, maria)
    assert run(client, s.id, small_csv).status_code in (403, 404)
    assert client.get(f"/api/v1/systems/{s.id}/bias-tests").status_code in (403, 404)
    login_as(client, db, people["chief"])
    assert run(client, s.id, small_csv).status_code == 200


def test_thresholds_come_from_the_risk_methodology(client, db, ats, people, small_csv):
    from app.reference.models import RiskMethodology

    cid, e, maria, s = ats
    m = db.scalar(select(RiskMethodology))
    m.config = {**m.config, "bias_calculator": {"impact_ratio_threshold": 0.7, "small_category_share": 0.3, "exclude_small_categories": True}}
    db.commit()
    login_as(client, db, people["aud"])
    out = run(client, s.id, small_csv).json()
    race = {c["key"]: c for c in out["results"]["tables"]["race"]["categories"]}
    assert not race["hispanic_latino"]["below_threshold"]  # 0.75 meets a 0.70 threshold
    inter = out["results"]["tables"]["intersectional"]
    assert inter["excluded"] == ["hispanic_latino|male", "hispanic_latino|female", "white|female"]  # each is under 30% of the table
    assert out["settings"]["threshold"] == 0.7


def test_what_the_run_feeds(client, db, ats, people, small_csv):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    out = run(client, s.id, small_csv).json()
    feeds = out["feeds"]
    assert feeds["q_6_2_06"] == 0.5
    assert feeds["q_5_1a_03"] == 10.0
    assert feeds["q_5_1a_05"] == "low"  # under 20% unknown
    assert feeds["below_threshold"] == [
        {"dimension": "sex", "key": "female", "label": "Female", "impact_ratio": 0.75},
        {"dimension": "race", "key": "hispanic_latino", "label": "Hispanic or Latino", "impact_ratio": 0.75},
        {"dimension": "intersectional", "key": "hispanic_latino|female", "label": "Hispanic or Latino female", "impact_ratio": 0.5},
    ]
    assert feeds["draft_findings"] == 1
    assert feeds["public_summary_required"] is True


def test_apply_answers_records_the_figures_as_the_auditor(client, db, ats, people, small_csv):
    from app.questionnaire.service import Target
    from app.scoring.service import scoring_answers

    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    rid = run(client, s.id, small_csv).json()["id"]
    r = client.post(f"/api/v1/bias-tests/{rid}/apply-answers")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == ["6.2.06", "5.1a.03", "5.1a.05"]
    db.expire_all()
    answers = scoring_answers(db, s)
    assert answers["6.2.06"] == 0.5 and answers["5.1a.03"] == 10.0 and answers["5.1a.05"] == "low"


def test_draft_findings_go_to_the_findings_draft_flow_once(client, db, ats, people, small_csv):
    from app.findings.models import Finding

    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    rid = run(client, s.id, small_csv).json()["id"]
    r = client.post(f"/api/v1/bias-tests/{rid}/draft-findings")
    assert r.status_code == 200, r.text
    assert len(r.json()["created"]) == 1
    f = db.scalar(select(Finding).where(Finding.origin == "bias_run"))
    assert f.status == "draft" and f.severity == "high" and f.ai_system_id == s.id and f.source_question_ids == ["6.2.06"]
    assert f.title == "Impact ratio below 0.80 for 3 categories"
    assert "Hispanic or Latino female: 0.50" in f.description and "6 RCNY § 5-301" in f.description
    assert client.post(f"/api/v1/bias-tests/{rid}/draft-findings").json()["created"] == []  # not twice


def test_raw_data_is_deleted_after_the_retention_period_unless_the_client_keeps_it(client, db, ats, people, small_csv, settings):
    from app.biascalc.retention import purge_expired_raw_data
    from app.core.clock import utcnow
    from app.files.service import read

    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    a = run(client, s.id, small_csv).json()["id"]
    b = run(client, s.id, small_csv).json()["id"]
    login_as(client, db, maria)
    assert client.put(f"/api/v1/bias-tests/{b}/keep-raw-data", json={"keep": True}).status_code == 200
    login_as(client, db, people["aud"])
    assert client.put(f"/api/v1/bias-tests/{b}/keep-raw-data", json={"keep": False}).status_code in (403, 404)  # the client decides
    eng = db.get(type(e), e.id)
    eng.retention_years, eng.completed_at = 1, utcnow() - timedelta(days=400)
    db.commit()
    settings = client.app.state.settings
    assert purge_expired_raw_data(db, settings, utcnow()) == 1
    ra, rb = db.get(BiasTestRun, a), db.get(BiasTestRun, b)
    assert ra.raw_deleted_at is not None and ra.dataset_file_id is None and ra.results["total"] == 200  # results stay
    assert rb.raw_deleted_at is None and read(settings, db.get(FileObject, rb.dataset_file_id)) == small_csv
    assert purge_expired_raw_data(db, settings, utcnow()) == 0


def test_raw_data_is_kept_while_the_engagement_is_open(client, db, ats, people, small_csv):
    from app.biascalc.retention import purge_expired_raw_data
    from app.core.clock import utcnow

    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    run(client, s.id, small_csv)
    assert purge_expired_raw_data(db, client.app.state.settings, utcnow() + timedelta(days=3650)) == 0


def test_a_file_the_client_uploaded_to_the_engagement_can_be_used(client, db, ats, people, small_csv):
    from app.files.service import upload

    cid, e, maria, s = ats
    f = upload(db, client.app.state.settings, maria, data=small_csv, filename="our-applicants.csv", content_type="text/csv", organization_id=cid, engagement_id=e.id, linked_type="evidence")
    other = upload(db, client.app.state.settings, maria, data=small_csv, filename="elsewhere.csv", content_type="text/csv", organization_id=cid, engagement_id=None)
    db.commit()
    login_as(client, db, people["aud"])
    r = client.post(f"/api/v1/systems/{s.id}/bias-tests", data={"method": "selection_rate", "file_id": f.id, "data_source": "Client upload"})
    assert r.status_code == 200, r.text
    assert r.json()["dataset_filename"] == "our-applicants.csv"
    r = client.post(f"/api/v1/systems/{s.id}/bias-tests", data={"method": "selection_rate", "file_id": other.id})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "file_id"
