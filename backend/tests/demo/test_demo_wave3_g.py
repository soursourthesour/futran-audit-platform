"""The WS-G demo step (app/demo/wave3_g.py) on top of the full demo seed: copilot suggestions on Meridian's credit risk
model whose quotes are really in the uploaded documents, decisions, a completeness review, the AI log, obligations on
NYC Local Law 144, and ABC Corp's customer questionnaire in progress."""
import pytest
from sqlalchemy import select

from tests.demo.test_demo_v061 import _get, as_user, world  # noqa: F401  (one demo world per module)


def test_copilot_demo_has_real_citations_and_decisions(world, as_user):
    from app.ai.models import AIInteraction, DocumentText
    from app.ai.text import find_quote
    from app.findings.models import Finding
    from app.questionnaire.models import Response

    db, sid = world["db"], world["ids"]["meridian_credit_system"]
    rows = list(db.scalars(select(AIInteraction).where(AIInteraction.ai_system_id == sid)))
    pre = [r for r in rows if r.feature == "copilot_prefill"]
    assert len(pre) >= 16 and {"accepted", "suggested", "unsupported", "rejected"} <= {r.status for r in pre}
    for r in rows:  # every quote marked found is in the cited document
        for c in r.citations or []:
            if c.get("file_id") and c.get("found"):
                dt = db.scalar(select(DocumentText).where(DocumentText.file_id == c["file_id"]))
                assert find_quote(dt.pages, c["quote"], c["page"]) == c["page"], c
    assert db.scalar(select(Response).where(Response.ai_system_id == sid, Response.source == "ai_suggested_accepted")) is not None
    assert db.scalar(select(Finding).where(Finding.ai_system_id == sid, Finding.origin == "ai_suggestion", Finding.status == "draft")) is not None
    assert any(r.follow_up == "interview" for r in pre)
    assert any(r.feature == "review_check" and (r.output or {}).get("interview_says") for r in rows)
    assert any(r.feature == "evidence_check" and (r.output or {}).get("verdict") == "does_not_support" for r in rows)
    assert {r.feature for r in rows} >= {"copilot_prefill", "evidence_check", "review_check", "ask", "explain"}


def test_ai_log_and_panel_through_the_api(world, as_user):
    from app.engagements.models import Engagement

    db, ids = world["db"], world["ids"]
    e = db.scalar(select(Engagement).where(Engagement.client_id == ids["meridian"]))
    log = _get(as_user("qa@futran.demo"), f"/engagements/{e.id}/ai-log")
    assert log["totals"]["suggestions"] >= 20 and log["totals"]["accepted"] >= 2 and log["switch"]["enabled"] is True
    panel = _get(as_user("auditor1@futran.demo"), f"/systems/{ids['meridian_credit_system']}/copilot?section=6.1")
    assert len(panel["documents"]) == 3 and len(panel["suggestions"]) == 8 and panel["interview_list"]


def test_obligations_and_questionnaire_demo(world, as_user):
    from app.ai.models import AnswerLibraryItem, Obligation, Questionnaire, QuestionnaireItem

    db = world["db"]
    obs = list(db.scalars(select(Obligation).where(Obligation.deleted_at.is_(None))))
    assert sum(o.status == "approved" for o in obs) == 2 and any(o.status == "suggested" for o in obs)
    q = db.scalar(select(Questionnaire).where(Questionnaire.customer_name == "Northwind Bank"))
    items = list(db.scalars(select(QuestionnaireItem).where(QuestionnaireItem.questionnaire_id == q.id)))
    assert len(items) == 8 and q.status == "in_progress"
    statuses = {i.status for i in items}
    assert "accepted" in statuses and "answered" in statuses and ("suggested" in statuses or "unsupported" in statuses)
    assert db.scalar(select(AnswerLibraryItem).where(AnswerLibraryItem.organization_id == q.organization_id, AnswerLibraryItem.source == "questionnaire")) is not None
    c = as_user("maria.lopez@abccorp.example")
    assert _get(c, "/questionnaires")["rows"][0]["counts"]["questions"] == 8
