"""SM-09 builder core: proposals from an estimate or a locked questionnaire, price precedence, %-items, removals,
totals, sections, versions and the diff (spec §4.6)."""
import pytest

from app.core.errors import Conflict, Invalid
from app.proposals import service as ps
from tests.proposals.conftest import add_item


def _line(p, code):
    return next(ln for ln in ps.lines(pw_db(p), p) if ln.catalog_code == code)


def pw_db(p):
    from sqlalchemy.orm import object_session

    return object_session(p)


def test_create_from_estimate_copies_lines_prices_and_discount(db, pw, estimate):
    p = ps.create_from_estimate(db, estimate, pw.sales)
    assert p.version == 1 and p.opportunity_id == pw.opp.id and p.estimate_id == estimate.id
    assert p.discount_recurring_pct == 5 and p.catalog_version == 1 and p.status == "draft"
    a05 = _line(p, "A-05")
    assert a05.list_price == 1500 and a05.override_price == 1200 and a05.unit_price_used == 1200 and a05.line_value == 3600
    assert a05.source == "package"  # on the Governed package the estimate started from
    assert _line(p, "A-02b").deliverables_text.startswith("Independent AI governance audit")
    # M-03a: quarterly × 4 at 4,200 = 16,800 recurring, 5% off
    assert p.totals == {"one_time": 38600, "recurring_y1": 16800, "discount": 840, "y1_total": 54560, "arr": 15960}
    assert pw.opp.stage == "proposal"


def test_estimate_without_an_opportunity_cannot_become_a_proposal(db, pw):
    from app.catalog import estimates

    e = estimates.save(db, pw.sales, {"name": "Loose", "lines": [{"code": "L-01", "qty": 1}]})
    with pytest.raises(Invalid):
        ps.create_from_estimate(db, e, pw.sales)


def test_create_from_questionnaire_uses_the_rule_lines_and_keeps_removed_ones(db, pw, monkeypatch):
    from types import SimpleNamespace

    from app.scoping import service as scoping

    q = SimpleNamespace(id="q1", opportunity_id=pw.opp.id, version=2, status="locked")
    monkeypatch.setattr(scoping, "suggest_lines", lambda db, qid: [
        {"code": "L-01", "qty": 1, "reason": "NYC = yes, AEDTs = 2", "rule_code": "R-L01", "removed_reason": None},
        {"code": "A-05", "qty": 3, "reason": "Inventory partial; 3 sources", "rule_code": "R-A05", "removed_reason": None},
        {"code": "M-09", "qty": 1, "reason": "Client asked for a public page", "rule_code": "R-M09", "removed_reason": None},
        {"code": "A-02a", "qty": 1, "reason": "SQ-C.07 = 8", "rule_code": "R-A02", "removed_reason": "Client already audited"},
        {"code": "Z-99", "qty": 1, "reason": "Not on the list", "rule_code": "R-Z", "removed_reason": None},
    ])
    p = ps.create_from_questionnaire(db, q, pw.sales)
    assert p.questionnaire_id == "q1" and p.questionnaire_version == 2
    l01 = _line(p, "L-01")
    assert l01.source == "rule" and l01.rule_code == "R-L01" and l01.reason == "NYC = yes, AEDTs = 2"
    assert _line(p, "A-02a").removed_reason == "Client already audited"
    m09 = _line(p, "M-09")
    assert m09.sellable_status == "roadmap" and m09.line_value is None  # optional, when available, no price
    z = _line(p, "Z-99")
    assert z.on_catalog is False and z.unit_price_used is None
    assert p.totals["one_time"] == 8500 + 4500


def test_price_precedence_edited_then_list_then_blocked(db, pw, estimate):
    p = ps.create_from_estimate(db, estimate, pw.sales)
    a02 = _line(p, "A-02b")
    ps.update_line(db, pw.sales, p, a02.id, {"override_price": 32000})
    assert a02.unit_price_used == 32000 and a02.edited_by == pw.sales.id and a02.edited_at is not None
    ps.update_line(db, pw.sales, p, a02.id, {"override_price": None})  # reset to list price
    assert a02.unit_price_used == 35000 and a02.override_price is None and a02.edited_by is None
    ps.update_line(db, pw.sales, p, a02.id, {"override_price": 35000})  # the list price itself is not an edit
    assert a02.override_price is None
    nolist = add_item(db, "X-77", name="Unpriced", list_price=None)
    ln = ps.add_line(db, pw.sales, p, nolist.code, 1)
    assert ln.unit_price_used is None and ln.line_value is None
    assert any(r["rule"] == "PRICE" and r["kind"] == "blocked" for r in ps.needed(db, p))


def test_percentage_items_are_their_own_lines_against_the_lines_they_apply_to(db, pw, estimate):
    add_item(db, "A-14", name="Rush delivery", basis="%", list_price=10, low=10, high=10, applies_to=["Audit"])
    p = ps.create_from_estimate(db, estimate, pw.sales)
    ln = ps.add_line(db, pw.sales, p, "A-14", 1)
    # Audit lines: A-02b 35,000 + A-05 3 × 1,200 = 38,600; 10% = 3,860
    assert ln.percent_of == 38600 and ln.line_value == 3860
    assert p.totals["one_time"] == 38600 + 3860


def test_removing_a_rule_line_needs_a_reason_and_can_be_restored(db, pw, monkeypatch):
    from types import SimpleNamespace

    from app.scoping import service as scoping

    monkeypatch.setattr(scoping, "suggest_lines", lambda db, qid: [{"code": "L-01", "qty": 1, "reason": "NYC", "rule_code": "R-L01", "removed_reason": None}])
    p = ps.create_from_questionnaire(db, SimpleNamespace(id="q", opportunity_id=pw.opp.id, version=1, status="locked"), pw.sales)
    l01 = _line(p, "L-01")
    with pytest.raises(Invalid):
        ps.remove_line(db, pw.sales, p, l01.id, "  ")
    ps.remove_line(db, pw.sales, p, l01.id, "Client has a bias audit already")
    assert l01.removed_reason == "Client has a bias audit already" and p.totals["one_time"] == 0
    ps.restore_line(db, pw.sales, p, l01.id)
    assert l01.removed_reason is None and p.totals["one_time"] == 8500
    manual = ps.add_line(db, pw.sales, p, "AA-02", 1)
    ps.remove_line(db, pw.sales, p, manual.id, "")  # a line the rep added goes without a reason
    assert all(ln.catalog_code != "AA-02" for ln in ps.lines(db, p))


def test_roadmap_and_retired_items_cannot_be_added_with_a_price(db, pw, estimate):
    p = ps.create_from_estimate(db, estimate, pw.sales)
    ln = ps.add_line(db, pw.sales, p, "M-09", 1)  # roadmap: listed as optional with no price
    assert ln.line_value is None and ln.sellable_status == "roadmap"
    with pytest.raises(Invalid):
        ps.add_line(db, pw.sales, p, "NOPE", 1)


def test_package_picker_replaces_package_lines_only(db, pw, estimate):
    p = ps.create_from_estimate(db, estimate, pw.sales)
    ps.add_line(db, pw.sales, p, "AA-02", 1)
    ps.apply_package(db, pw.sales, p, "starter")
    codes = {ln.catalog_code for ln in ps.lines(db, p)}
    assert p.package == "starter" and "L-01" in codes and "AA-02" in codes and "A-02b" in codes  # hand-added stays
    assert "A-05" not in codes and "M-03a" not in codes  # the Governed package lines go


def test_sections_are_built_from_deliverables_and_assumptions(db, pw, estimate):
    p = ps.create_from_estimate(db, estimate, pw.sales)
    keys = [s["key"] for s in p.sections]
    assert keys == ["cover", "situation", "services", "deliverables", "pricing", "assumptions", "terms", "acceptance"]
    from app.proposals import document

    md = document.markdown(db, p)
    assert "## What we'll do" in md and "Shadow AI discovery sweep (A-05)" in md
    assert "Delivered by Futran consultants" in md  # P-8 manual-delivery assumption
    assert "50 AI systems in scope" in md  # A-02b inclusions
    assert "AI Governix" not in md and "Futran Audit Platform" in md
    ps.update_line(db, pw.sales, p, _line(p, "A-05").id, {"deliverables_text": "Tailored for Acme: three exports."})
    assert "Tailored for Acme: three exports." in document.markdown(db, p)
    ps.update_section(db, pw.sales, p, "situation", "Acme screens NYC candidates with two AI tools.")
    assert "Acme screens NYC candidates" in document.markdown(db, p)


def test_independence_statement_only_when_flagged(db, pw):
    p = ps.create_blank(db, pw.audit_opp, pw.sales)
    assert p.independence["flag"] is True
    assert "independence" in [s["key"] for s in p.sections]
    from app.proposals import document

    assert "## Independence statement" in document.markdown(db, p)


def test_versions_are_immutable_once_sent_and_diff_shows_changes(db, pw, estimate):
    p1 = ps.create_from_estimate(db, estimate, pw.sales)
    p1.status = "sent"
    db.flush()
    with pytest.raises(Conflict):
        ps.update_line(db, pw.sales, p1, _line(p1, "A-02b").id, {"qty": 2})
    with pytest.raises(Conflict):
        ps.update_terms(db, pw.sales, p1, {"discount_recurring_pct": 0})
    p2 = ps.new_version(db, pw.sales, p1)
    assert p2.version == 2 and p2.thread_id == p1.thread_id and p2.status == "draft"
    ps.update_line(db, pw.sales, p2, _line(p2, "A-02b").id, {"override_price": 33000})
    ps.update_line(db, pw.sales, p2, _line(p2, "A-05").id, {"qty": 2})
    ps.add_line(db, pw.sales, p2, "L-01", 1)
    ps.update_terms(db, pw.sales, p2, {"discount_recurring_pct": 10, "terms": {"payment_days": 45}})
    d = ps.diff(db, p1, p2)
    by = {c["code"]: c for c in d["lines"]}
    assert by["A-02b"]["changes"] == [{"field": "unit price", "from": 35000, "to": 33000}]
    assert by["A-05"]["changes"][0] == {"field": "qty", "from": 3, "to": 2}
    assert by["L-01"]["kind"] == "added"
    assert {"field": "discount on recurring", "from": 5, "to": 10} in d["terms"]
    assert {"field": "payment days", "from": 30, "to": 45} in d["terms"]
    assert _line(p1, "A-02b").unit_price_used == 35000  # v1 untouched


def test_new_version_is_refused_after_acceptance(db, pw, estimate):
    p1 = ps.create_from_estimate(db, estimate, pw.sales)
    p1.status = "accepted"
    with pytest.raises(Conflict):
        ps.new_version(db, pw.sales, p1)
