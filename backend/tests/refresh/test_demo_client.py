"""The test client used by the demo and browser tests proposes changes that say they are not research."""
from sqlalchemy import select

from app.refresh.demo import NOTE, demo_client
from app.refresh.pipeline import execute_run, start_run
from app.regmaster.models import ProposedChange


def test_demo_client_proposals_are_labelled(db, lit, reg, settings):
    run = start_run(db, kind="law", actor=lit["chief"], jurisdiction_codes=["US-IL"], settings=settings)
    execute_run(db, settings, run, demo_client())
    rows = list(db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id)))
    assert len(rows) == 2 and all(NOTE in r.summary for r in rows)
    assert {r.confidence for r in rows} == {"high", "low"}  # the second rests on a source off the allowlist
