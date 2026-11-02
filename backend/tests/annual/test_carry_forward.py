"""F16: an annual review started from a closed engagement carries its systems, answers and evidence links forward; the
client confirms or updates each carried answer; changes are shown to the auditor; the report compares the years."""
from datetime import timedelta

from sqlalchemy import select

from app.annual.models import CarriedAnswer
from app.core.clock import utcnow
from app.engagements.models import ClientRequirement, Engagement, EngagementTeam
from app.questionnaire.models import ChecklistItem, ChecklistResult, Response
from app.systems.models import AISystem
from tests.factories import login_as


def _close(db, e):
    eng = db.get(Engagement, e.id)
    eng.status, eng.stage, eng.completed_at = "completed", 9, utcnow()
    db.commit()
    return eng


def _start(client, db, people, e):
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/engagements/{e.id}/annual-review")
    assert r.status_code == 200, r.text
    return db.get(Engagement, r.json()["engagement_id"])


def test_start_annual_review_copies_systems_answers_evidence_links_scope_and_team(client, db, ats, people, settings):
    from app.files.service import upload

    cid, e, maria, s = ats
    item = db.scalar(select(ChecklistItem).where(ChecklistItem.code == "6.4.03"))
    f = upload(db, client.app.state.settings, people["aud"], data=b"%PDF-1.4", filename="bias.pdf", content_type=None, organization_id=cid, engagement_id=e.id, linked_type="evidence")
    db.add(ChecklistResult(organization_id=cid, engagement_id=e.id, ai_system_id=s.id, checklist_item_id=item.id, confirmed=True, evidence_ids=[f.id]))
    db.commit()
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/engagements/{e.id}/annual-review").status_code == 409  # not closed yet
    prior = _close(db, e)
    login_as(client, db, people["aud"])
    assert client.post(f"/api/v1/engagements/{e.id}/annual-review").status_code == 403
    new = _start(client, db, people, prior)
    assert (new.type, new.status, new.prior_engagement_id, new.client_id) == ("annual_review", "draft", prior.id, cid)
    if prior.period_end:
        assert new.period_start == prior.period_end + timedelta(days=1)
    systems = {x.reference_id: x for x in db.scalars(select(AISystem).where(AISystem.engagement_id == new.id))}
    assert systems["SYS-001"].name == s.name and systems["SYS-001"].built_by == "vendor" and systems["SYS-001"].register_system_id == s.register_system_id
    carried = list(db.scalars(select(Response).where(Response.engagement_id == new.id)))
    assert carried and all(r.source == "carried_forward" and r.verified_at is None for r in carried)
    r601 = next(r for r in carried if r.ai_system_id == systems["SYS-001"].id and r.value == "no")
    assert r601.client_value == "no" and r601.client_status == "answered"
    ca = db.scalar(select(CarriedAnswer).where(CarriedAnswer.response_id == r601.id))
    assert ca.status == "pending" and ca.prior_value == "no"
    res = db.scalar(select(ChecklistResult).where(ChecklistResult.engagement_id == new.id, ChecklistResult.checklist_item_id == item.id))
    assert res.evidence_ids == [f.id] and res.confirmed is False  # the link carries; the auditor confirms it again
    assert {(t.user_id, t.role) for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == new.id))} == \
           {(t.user_id, t.role) for t in db.scalars(select(EngagementTeam).where(EngagementTeam.engagement_id == prior.id, EngagementTeam.deleted_at.is_(None)))}
    assert len(list(db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == new.id)))) == len(list(db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == prior.id, ClientRequirement.deleted_at.is_(None)))))
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/engagements/{prior.id}/annual-review").status_code == 409  # one annual review per engagement
    # the wizard picks up the new draft for review and submission
    assert client.get(f"/api/v1/clients/{cid}/wizard").json()["engagement"]["id"] == new.id


def test_the_client_confirms_unchanged_answers_and_changes_are_highlighted_for_the_auditor(client, db, ats, people):
    cid, e, maria, s = ats
    prior = _close(db, e)
    new = _start(client, db, people, prior)
    login_as(client, db, maria)
    assert client.get(f"/api/v1/engagements/{new.id}/carried").status_code == 404  # a draft is not the client's yet
    new.status = "initiated"
    db.commit()
    out = client.get(f"/api/v1/engagements/{new.id}/carried").json()
    assert out["counts"]["pending"] == out["counts"]["total"] > 0 and out["counts"]["changed"] == 0
    second = next(i for i in out["items"] if i["code"] == "6.2.01")  # Bias testing performed: No last year
    first = next(i for i in out["items"] if i["code"] != "6.2.01")
    r = client.post(f"/api/v1/responses/{first['response_id']}/confirm-carried")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    new_sys = db.get(AISystem, second["system_id"]) if second["system_id"] else None
    target = f"/api/v1/systems/{new_sys.id}/responses/{second['code']}" if new_sys else f"/api/v1/clients/{cid}/responses/{second['code']}"
    assert second["prior_value"] == "no"
    new_value = "yes"
    assert client.put(target, json={"value": new_value, "status": "answered"}).status_code == 200
    out = client.get(f"/api/v1/engagements/{new.id}/carried").json()
    items = {i["response_id"]: i for i in out["items"]}
    assert items[first["response_id"]]["status"] == "confirmed"
    assert items[second["response_id"]]["status"] == "changed" and items[second["response_id"]]["current"]["value"] == new_value
    left = out["counts"]["pending"]
    r = client.post(f"/api/v1/engagements/{new.id}/carried/confirm-unchanged")
    assert r.status_code == 200 and r.json()["confirmed"] == left
    login_as(client, db, people["aud"])
    changed = client.get(f"/api/v1/engagements/{new.id}/carried?changed=1").json()
    assert [i["response_id"] for i in changed["items"]] == [second["response_id"]] and changed["items"][0]["prior"]["value"] == second["prior_value"]
    assert client.post(f"/api/v1/responses/{first['response_id']}/confirm-carried").status_code in (403, 404)  # the client confirms, not Futran


def test_year_over_year_compares_maturity_and_residual_and_goes_in_the_report(client, db, ats, people):
    from app.reports.service import build_report
    from app.scoring import service as scoring
    from tests.scoring.test_service import ATS_DOMAINS, _all_domains

    cid, e, maria, s = ats
    _all_domains(db, people, s, ATS_DOMAINS)
    scoring.engagement_rollup(db, e)
    prior = _close(db, e)
    new = _start(client, db, people, prior)
    from app.annual.service import year_over_year

    yoy = year_over_year(db, new)
    row = next(x for x in yoy["systems"] if x["system"].startswith("SYS-001"))
    assert (row["prior_maturity"], row["prior_residual"], row["prior_rating"]) == (2.25, 58.2, "High (4)")
    assert row["maturity"] == "Not scored yet" and yoy["prior_ref"] == prior.audit_ref
    login_as(client, db, people["chief"])
    assert client.get(f"/api/v1/engagements/{new.id}/year-over-year").json()["systems"][0]["prior_maturity"] is not None
    md = build_report(db, new, "v0.1").markdown
    assert "## Appendix F. Year-over-year comparison" in md and prior.audit_ref in md
