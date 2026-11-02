import pytest
from sqlalchemy import select

from app.engagements.models import Engagement
from app.questionnaire.models import Question
from app.questionnaire.seed import load_question_bank
from app.systems.models import AISystem
from tests.wsd_world import lit  # noqa: F401


@pytest.fixture
def audited(db, lit):
    """ABC Corp's résumé screening (AIS-001) is SYS-001 in a current engagement, scored, with verified answers in
    5.1 (data) and 8.3 (incidents)."""
    from app.questionnaire.models import Response

    load_question_bank(db)
    e = Engagement(organization_id=lit["abc"].id, client_id=lit["abc"].id, name="ABC 2026 audit", status="in_progress", stage=5)
    db.add(e)
    db.flush()
    s = AISystem(organization_id=lit["abc"].id, engagement_id=e.id, name="Résumé screening", reference_id="SYS-001", status="scored",
                 register_system_id=lit["screening"].id, tool_ids=[], use_case_ids=[])
    db.add(s)
    db.flush()
    rows = {}
    for code in ("5.1.01", "8.3.01"):
        q = db.scalar(select(Question).where(Question.code == code))
        r = Response(organization_id=lit["abc"].id, engagement_id=e.id, ai_system_id=s.id, question_id=q.id, status="answered", value="yes",
                     evidence_ids=[], client_evidence_ids=[], verified_by=lit["aud"].id, answered_side="futran")
        from app.core.clock import utcnow

        r.verified_at = utcnow()
        db.add(r)
        rows[code] = r
    db.commit()
    return {"engagement": e, "system": s, "responses": rows}
