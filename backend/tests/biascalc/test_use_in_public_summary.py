""""Use in public summary" (§ 5-303, § 5-301(d)): the generated exclusion text is replaced on every use and never mixes
with or replaces a hand-written note; nothing is cut short without saying so."""
from sqlalchemy import select

from app.reports.models import PublicSummary
from app.reports.public_summary import summary_text
from tests.biascalc.conftest import SMALL, applicant_csv
from tests.biascalc.test_runs import run
from tests.factories import login_as

WITH_SMALL = SMALL | {("Female", "Asian"): (3, 1)}  # 3 of 223 people: under 2%, excluded
WHY = "Under 2% of the data; a ratio on three people is not meaningful."


def _use(client, rid, justification=None):
    return client.post(f"/api/v1/bias-tests/{rid}/public-summary", json={"justification": justification})


def _summary(db, e):
    db.expire_all()
    return db.scalar(select(PublicSummary).where(PublicSummary.engagement_id == e.id))


def test_the_exclusion_is_replaced_on_each_use_and_the_hand_written_note_is_kept(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    small = run(client, s.id, applicant_csv(WITH_SMALL, unknown=(20, 5))).json()["id"]
    plain = run(client, s.id, applicant_csv(SMALL, unknown=(20, 5))).json()["id"]
    assert _use(client, small, WHY).status_code == 200
    ps = _summary(db, e)
    excluded = [r for r in ps.impact_ratios if r.get("excluded")]
    assert {r["group"] for r in excluded} == {"Asian (not Hispanic or Latino)", "Asian female (not Hispanic or Latino)"} and all(r["justification"] == WHY and r["applicants"] == 3 for r in excluded)
    assert "Asian (not Hispanic or Latino): 3 applicants, selection rate 0.33, excluded from the impact ratio calculation. Justification: " + WHY in summary_text(ps)
    ps.notes = "Hand-written note by the auditor."
    db.commit()
    assert _use(client, small, WHY).status_code == 200
    assert _summary(db, e).notes == "Hand-written note by the auditor."  # not overwritten when there are exclusions
    assert _use(client, plain).status_code == 200
    ps = _summary(db, e)
    assert not [r for r in ps.impact_ratios if r.get("excluded")] and ps.notes == "Hand-written note by the auditor."  # no stale exclusion
    # a summary written before this change, with the generated text in the note
    ps.notes = "Hand-written note by the auditor.\nExcluded from the impact ratio calculations because each is under 2% of the data: Race/ethnicity · Asian: 3 applicants. Justification: old."
    db.commit()
    assert _use(client, plain).status_code == 200
    assert _summary(db, e).notes == "Hand-written note by the auditor."


def test_long_text_is_refused_with_a_message_not_cut_short(client, db, ats, people):
    cid, e, maria, s = ats
    login_as(client, db, people["aud"])
    small = run(client, s.id, applicant_csv(WITH_SMALL, unknown=(20, 5))).json()["id"]
    r = _use(client, small, "x" * 1001)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "justification" and "1,000" in r.json()["errors"][0]["message"]
    assert _summary(db, e) is None
    assert _use(client, small, WHY).status_code == 200
    body = {"tool_name": "ATS", "notes": "n" * 4001, "impact_ratios": [], "evidence_file_ids": []}
    r = client.put(f"/api/v1/clients/{cid}/public-summary", json=body)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "notes" and "4,000" in r.json()["errors"][0]["message"]

