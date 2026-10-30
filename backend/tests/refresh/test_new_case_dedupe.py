"""New cases are the same case when the court and docket match (or the court and name, when there is no docket),
whatever the free text says. A duplicate is merged when proposed and refused on approval."""
import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.litigation.models import Case
from app.refresh.claude import FakeRefreshClient
from app.refresh.models import RefreshProposalMeta
from app.refresh.pipeline import execute_run, start_run
from app.refresh.review import decide
from app.regmaster.models import ProposedChange, Source


@pytest.fixture
def us(db, lit):
    from app.reference.models import Jurisdiction

    j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US"))
    db.add(Source(jurisdiction_id=j.id, name="U.S. District Court, N.D. Cal.", url="https://cand.uscourts.gov/", domain="uscourts.gov", kind="official"))
    db.commit()
    return j


def _item(name, docket="3:24-cv-01234", court="U.S. District Court, N.D. Cal.", summary="A new AI hiring case."):
    value = {"name": name, "court": court, "docket_ref": docket, "area": "Hiring", "stage": "filed", "description": summary, "last_update_on": "2026-10-01"}
    import json

    return {"change_type": "new_case", "case_id": None, "field_path": "new_case", "old_value": None, "new_value": json.dumps(value), "summary": summary,
            "source_url": "https://cand.uscourts.gov/cases/123", "source_quote": "Complaint filed against the employer.", "confidence": "high"}


def _run(db, lit, settings, items):
    run = start_run(db, kind="litigation", actor=lit["chief"], scope_mode="chosen", jurisdiction_codes=["US"], settings=settings)
    execute_run(db, settings, run, FakeRefreshClient({"litigation:US": {"changes": items}}))
    db.commit()
    return run


def test_same_court_and_docket_with_other_wording_is_merged(db, lit, settings, us):
    _run(db, lit, settings, [_item("Doe v. Acme Corp.")])
    _run(db, lit, settings, [_item("Jane Doe v. ACME Corporation", docket=" 3:24-CV-01234 ", summary="Applicant sues over AI screening.")])
    assert len(list(db.scalars(select(ProposedChange).where(ProposedChange.field_path == "new_case")))) == 1


def test_same_court_and_name_without_docket_is_merged(db, lit, settings, us):
    _run(db, lit, settings, [_item("Doe v. Acme Corp.", docket=None)])
    _run(db, lit, settings, [_item("doe v.  acme corp", docket="", summary="Other words")])
    assert len(list(db.scalars(select(ProposedChange).where(ProposedChange.field_path == "new_case")))) == 1


def test_approval_refuses_a_case_already_in_the_tracker(db, lit, settings, us):
    db.add(Case(name="Doe v. Acme", court="U.S. District Court, N.D. Cal.", docket_ref="3:24-cv-01234", area="Hiring", stage="filed", jurisdiction_id=us.id, version=1, timeline=[], match_rule={}))
    db.commit()
    run = _run(db, lit, settings, [_item("Doe v. Acme Corp.")])
    pc = db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))
    meta = db.get(RefreshProposalMeta, pc.id)
    meta.needs_second_review = False
    with pytest.raises(Conflict) as e:
        decide(db, settings, pc, lit["chief"], "approve")
    assert "already in the litigation tracker" in e.value.detail
