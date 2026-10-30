"""§25.1 principle 4 and §25.3 step 4: each proposed change rests on a page web search really cited and a passage from
it. The JSON step runs without tools, so a link or quote it writes that the searches did not cite is forced to low
confidence (a second review). Litigation changes resting on a secondary (law-firm) source are low confidence too."""
from sqlalchemy import select

from app.refresh.claude import FakeRefreshClient
from app.refresh.demo import demo_client
from app.refresh.models import RefreshProposalMeta
from app.refresh.pipeline import citation_supported, execute_run, start_run
from app.regmaster.models import ProposedChange
from tests.refresh.conftest import change

URL = "https://www.ilga.gov/legislation/publicacts/fulltext.asp?Name=104-0001"
QUOTE = "This Act takes effect January 1, 2027."


def _run(db, lit, settings, client, codes=("US-IL",), kind="law", **kw):
    run = start_run(db, kind=kind, actor=lit["chief"], jurisdiction_codes=list(codes), settings=settings, **kw)
    execute_run(db, settings, run, client)
    db.commit()
    return run


def _pc(db, run):
    return db.scalar(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id))


def test_cited_page_and_passage_keep_the_confidence(db, lit, reg, settings):
    cited = {"US-IL": {URL: ["Section 99. Effective date. This Act takes   effect\nJanuary 1, 2027. Section 100."]}}
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}}, citations=cited))
    pc = _pc(db, run)
    assert pc.confidence == "high" and not db.get(RefreshProposalMeta, pc.id).needs_second_review


def test_quote_not_in_any_cited_passage_is_low_confidence(db, lit, reg, settings):
    cited = {"US-IL": {URL: ["This Act takes effect upon becoming law."]}}
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}}, citations=cited))
    pc = _pc(db, run)
    meta = db.get(RefreshProposalMeta, pc.id)
    assert pc.confidence == "low" and meta.claude_confidence == "high" and meta.needs_second_review
    assert any("not among the passages" in w for w in run.warnings), run.warnings


def test_page_the_searches_never_cited_is_low_confidence(db, lit, reg, settings):
    cited = {"US-IL": {"https://www.ilga.gov/other-page": [QUOTE]}}
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}}, citations=cited))
    assert _pc(db, run).confidence == "low"


def test_nothing_cited_is_low_confidence(db, lit, reg, settings):
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}}, citations={"US-IL": {}}))
    assert _pc(db, run).confidence == "low"


def test_the_fake_cites_what_it_quotes_by_default(db, lit, reg, settings):
    run = _run(db, lit, settings, FakeRefreshClient({"US-IL": {"changes": [change(reg["law"])]}}))
    assert _pc(db, run).confidence == "high"


def test_demo_client_items_on_the_allowlist_stay_high(db, lit, reg, settings):
    run = _run(db, lit, settings, demo_client())
    rows = list(db.scalars(select(ProposedChange).where(ProposedChange.refresh_run_id == run.id)))
    assert {r.confidence for r in rows} == {"high", "low"}


def test_matching_rules():
    cited = {"https://Example.gov/a/": ["One  two\nthree four."]}
    assert citation_supported(cited, "https://example.gov/a", "two three")
    assert citation_supported(cited, "https://example.gov/a#s1", "One two three four.")
    assert not citation_supported(cited, "https://example.gov/b", "two three")
    assert not citation_supported(cited, "https://example.gov/a", "two three five")
    assert not citation_supported(None, "https://example.gov/a", "two three")


def test_litigation_change_on_a_secondary_source_is_low_confidence(db, lit, settings):
    from app.litigation.models import Case
    from app.litigation.service import match_case
    from app.reference.models import Jurisdiction
    from app.regmaster.models import Source
    from tests.wsd_world import HIRING_CASE

    us = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US"))
    db.add(Source(jurisdiction_id=us.id, name="U.S. District Court, N.D. Cal.", url="https://cand.uscourts.gov/", domain="uscourts.gov", kind="official"))
    db.add(Source(jurisdiction_id=us.id, name="A law firm alert", url="https://lawfirm.example/", domain="lawfirm.example", kind="secondary"))
    case = Case(name=HIRING_CASE["name"], area="Hiring discrimination", stage="discovery", jurisdiction_id=us.id, match_rule=HIRING_CASE["match_rule"], version=1, timeline=[])
    db.add(case)
    db.flush()
    match_case(db, case)
    item = {"change_type": "case_update", "case_id": case.id, "field_path": "case.stage", "old_value": "discovery", "new_value": "trial",
            "summary": "Trial date set.", "source_url": "https://lawfirm.example/alerts/mobley", "source_quote": "The case is set for jury trial.", "confidence": "high"}
    run = start_run(db, kind="litigation", actor=lit["chief"], scope_mode="chosen", jurisdiction_codes=["US"], settings=settings, source_set="with_secondary")
    execute_run(db, settings, run, FakeRefreshClient({"litigation:US": {"changes": [item]}}))
    db.commit()
    pc = _pc(db, run)
    meta = db.get(RefreshProposalMeta, pc.id)
    assert pc.confidence == "low" and meta.needs_second_review and meta.claude_confidence == "high"
