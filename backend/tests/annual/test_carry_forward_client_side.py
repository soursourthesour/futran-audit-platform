"""F16 review fix: carry-forward gives the client back only what the client answered last year, on client questions.
Auditor-only answers, the auditor's corrections and the auditor's verification are never shown to the client as theirs
and never become this year's answers of record without the auditor acting."""
from sqlalchemy import select

from app.annual.models import CarriedAnswer
from app.questionnaire.models import Question, Response
from app.questionnaire.service import Target, save_response
from app.systems.models import AISystem
from tests.annual.test_carry_forward import _close, _start
from tests.factories import login_as

AUDITOR_ONLY = ("3.3.05s", "5.1a.05", "3.3.10")


def test_client_sees_only_its_own_prior_answers_to_client_questions(client, db, ats, people):
    cid, e, maria, s = ats
    # the auditor records an auditor-only judgement; the client answered 6.2.01 "yes" but the auditor's record is "no"
    save_response(db, people["aud"], Target(e, s), "3.3.10", {"value": "INTERNAL: vendor evasive in interview", "status": "answered"}, futran=True)
    save_response(db, maria, Target(e, s), "6.2.01", {"value": "yes", "status": "answered"}, futran=False)
    save_response(db, maria, Target(e, s), "3.3.06", {"value": "yes", "status": "answered"}, futran=False)
    db.commit()
    prior = _close(db, e)
    new = _start(client, db, people, prior)
    new.status = "initiated"
    db.commit()
    login_as(client, db, maria)
    out = client.get(f"/api/v1/engagements/{new.id}/carried")
    assert out.status_code == 200, out.text
    codes = {i["code"]: i for i in out.json()["items"]}
    assert not [c for c in AUDITOR_ONLY if c in codes]
    assert set(codes) == {"6.2.01", "3.3.06"}  # 3.3.02 and the rest were answered by Futran, never by the client
    assert codes["6.2.01"]["prior"]["value"] == "yes"  # the client's own answer, not the auditor's correction
    new_rows = list(db.scalars(select(Response).where(Response.engagement_id == new.id)))
    assert all(r.verified_at is None and r.answered_side != "futran" for r in new_rows)
    qs = {q.id: q for q in db.scalars(select(Question))}
    # nothing the auditor alone said last year becomes this year's answer of record
    assert not [qs[r.question_id].code for r in new_rows if qs[r.question_id].default_respondent != "client" and r.status != "unanswered"]
    assert not [qs[r.question_id].code for r in new_rows if r.status != "unanswered" and qs[r.question_id].code not in ("6.2.01", "3.3.06")]
    r = next(r for r in new_rows if qs[r.question_id].code == "6.2.01")
    assert (r.value, r.client_value) == ("yes", "yes")


def test_the_client_never_sees_carried_auditor_questions(client, db, ats, people):
    """Engagements carried before the fix may hold auditor-question rows; the client's list leaves them out."""
    cid, e, maria, s = ats
    prior = _close(db, e)
    new = _start(client, db, people, prior)
    new.status = "initiated"
    ns = db.scalar(select(AISystem).where(AISystem.engagement_id == new.id, AISystem.reference_id == "SYS-001"))
    q = db.scalar(select(Question).where(Question.code == "5.1a.05"))
    r = db.scalar(select(Response).where(Response.engagement_id == new.id, Response.ai_system_id == ns.id, Response.question_id == q.id))
    if r is None:
        r = Response(organization_id=cid, engagement_id=new.id, ai_system_id=ns.id, question_id=q.id, value="high", status="answered", answered_side="client", source="carried_forward",
                     client_value="high", client_status="answered", evidence_ids=[], client_evidence_ids=[])
        db.add(r)
        db.flush()
        old = db.scalar(select(Response).where(Response.engagement_id == prior.id, Response.ai_system_id == s.id, Response.question_id == q.id))
        db.add(CarriedAnswer(organization_id=cid, engagement_id=new.id, response_id=r.id, prior_response_id=old.id, prior_value="high", prior_status="answered", prior_evidence_ids=[]))
    db.commit()
    login_as(client, db, maria)
    assert "5.1a.05" not in {i["code"] for i in client.get(f"/api/v1/engagements/{new.id}/carried").json()["items"]}
    assert client.post(f"/api/v1/responses/{r.id}/confirm-carried").status_code in (403, 404)
    client.post(f"/api/v1/engagements/{new.id}/carried/confirm-unchanged")
    db.expire_all()
    assert db.scalar(select(CarriedAnswer).where(CarriedAnswer.response_id == r.id)).status == "pending"
    login_as(client, db, people["chief"])
    assert "5.1a.05" in {i["code"] for i in client.get(f"/api/v1/engagements/{new.id}/carried").json()["items"]}
