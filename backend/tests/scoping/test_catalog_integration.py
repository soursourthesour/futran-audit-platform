"""Against R1's price list: rules whose line code is not in the catalog are flagged (never dropped), and the running
estimate reads list prices, one-time and recurring."""
from app.catalog.seed import seed_starter
from app.scoping import rulebook, service


def test_rules_missing_from_the_starter_price_list_are_flagged_not_dropped(db, world):
    seed_starter(db)
    rows = rulebook.all_rules(db)
    flags = rulebook.flags(db, rows)
    assert len(rows) == 39
    ok = sorted(r.code for r in rows if r.code not in flags)
    assert ok == ["MR-01a", "MR-01b", "MR-03", "MR-04b", "MR-06a", "MR-07a", "MR-09", "MR-12a", "MR-13a", "MR-15b"]
    assert flags["MR-17"] == "X-04 is not in the price list. Add it there, or change the rule."


def test_running_estimate_at_list_prices(db, world):
    seed_starter(db)
    q = service.start(db, world["opp"], world["sales"])
    service.save_answers(db, q, [{"code": "SQ-C.07", "value": 6}, {"code": "SQ-B.01", "value": 600}, {"code": "SQ-F.01", "value": "monitor"},
                                 {"code": "SQ-C.10", "value": "partial"}, {"code": "SQ-C.11", "value": ["m365", "google"]}, {"code": "SQ-H.01", "value": "yes"}],
                         actor=world["sales"])
    est = service.estimate(db, q)
    # A-02a 15,000 + A-05 1,500 x 2 + A-06b 4,000 one-time; M-01a annual; X-04 not in the starter list
    assert est["available"] is True and est["one_time"] == 15000 + 3000 + 4000
    assert est["recurring_y1"] > 0 and est["missing"] == ["X-04"]


def test_lock_and_build_proposal_uses_r4s_builder_with_removed_lines_kept(client, db, world):
    from app.proposals.models import Proposal, ProposalLine
    from sqlalchemy import select
    from tests.factories import login_as

    seed_starter(db)
    q = service.start(db, world["opp"], world["sales"])
    service.save_answers(db, q, [{"code": "SQ-C.07", "value": 6}, {"code": "SQ-B.01", "value": 600}, {"code": "SQ-C.10", "value": "none"}], actor=world["sales"])
    service.remove_line(db, q, "A-05", "Client exported its own tool list", world["sales"])
    db.commit()
    login_as(client, db, world["sales"])
    r = client.post(f"/api/v1/scoping/{q.id}/lock", json={"build_proposal": True})
    assert r.status_code == 200, r.text
    p = db.get(Proposal, r.json()["proposal_id"])
    lines = {pl.catalog_code: pl for pl in db.scalars(select(ProposalLine).where(ProposalLine.proposal_id == p.id))}
    assert set(lines) == {"A-02a", "A-05", "A-06b"} and lines["A-05"].removed_reason == "Client exported its own tool list"
    assert lines["A-02a"].rule_code == "MR-01a" and lines["A-02a"].source == "rule"
