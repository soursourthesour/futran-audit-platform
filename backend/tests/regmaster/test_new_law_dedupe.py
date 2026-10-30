"""New laws are the same law when the geography matches and the normalised short name or citation matches, whatever
the free text around them says. A duplicate is merged when proposed and refused on approval."""
import pytest

from app.core.errors import Conflict
from app.regmaster import changes
from app.regmaster.seed import find_law, seed_regmaster


@pytest.fixture
def master(matrix):
    seed_regmaster(matrix)
    return matrix


def _new(db, short_name, citation=None, summary="Add the Utah record", code="US-UT"):
    return changes.propose(db, actor_id="u1", regulation_id=None, field_path="new_law", change_type="new_law", origin="admin_edit", summary=summary,
                           new_value={"jurisdiction_code": code, "short_name": short_name, "citation": citation, "type": "statute",
                                      "version": {"status": "in_force", "scope_text": summary}})


def test_same_name_with_other_wording_is_merged(master):
    a = _new(master, "Utah AI Policy Act", "SB 149 (2024)")
    b = _new(master, "  utah ai policy  act. ", None, summary="Utah's generative AI disclosure law")
    assert a.id == b.id


def test_same_citation_under_another_name_is_merged(master):
    a = _new(master, "Utah AI Policy Act", "SB 149 (2024)")
    b = _new(master, "Artificial Intelligence Amendments", "sb 149  (2024)")
    assert a.id == b.id


def test_same_name_in_another_geography_is_a_different_law(master):
    a = _new(master, "AI Policy Act", code="US-UT")
    b = _new(master, "AI Policy Act", code="US-CO")
    assert a.id != b.id


def test_approval_refuses_a_law_already_in_the_library(master):
    db = master
    ll144 = find_law(db, "US-NYC", "Local Law 144")
    pc = _new(db, ll144.short_name.upper(), code="US-NYC")
    with pytest.raises(Conflict) as e:
        changes.apply_changes(db, [pc], reviewer_id="chief")
    assert "already in the law library" in e.value.detail


def test_approval_refuses_the_second_of_two_proposals_for_one_law(master):
    db = master
    a = _new(db, "Utah AI Policy Act", "SB 149 (2024)")
    changes.apply_changes(db, [a], reviewer_id="chief")
    b = _new(db, "Utah AI Policy Act (as amended)", "SB 149 (2024)")
    with pytest.raises(Conflict):
        changes.apply_changes(db, [b], reviewer_id="chief")
