"""An approval never silently overwrites a field that changed after the change was proposed (base_version_id)."""
import pytest

from app.core.errors import Conflict
from app.regmaster import changes
from app.regmaster.models import LawVersion
from app.regmaster.seed import find_law, seed_regmaster


@pytest.fixture
def master(matrix):
    seed_regmaster(matrix)
    return matrix


def _law(db):
    return find_law(db, "US-NYC", "Local Law 144")


def test_same_field_changed_since_is_refused(master):
    db = master
    law = _law(db)
    stale = changes.propose(db, actor_id="u1", regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,000", summary="Penalty (first)", origin="admin_edit")
    other = changes.propose(db, actor_id="u2", regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $2,000", summary="Penalty (second)", origin="admin_edit")
    changes.apply_changes(db, [other], reviewer_id="chief")
    with pytest.raises(Conflict) as e:
        changes.apply_changes(db, [stale], reviewer_id="chief")
    assert "proposed against an earlier version" in e.value.detail
    assert db.get(LawVersion, law.current_version_id).penalty_text == "Up to $2,000"
    assert stale.status == "pending"


def test_other_field_changed_since_is_applied(master):
    db = master
    law = _law(db)
    a = changes.propose(db, actor_id="u1", regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,000", summary="Penalty", origin="admin_edit")
    b = changes.propose(db, actor_id="u2", regulation_id=law.id, field_path="law.cure_period", new_value="None", summary="Cure", origin="admin_edit")
    changes.apply_changes(db, [b], reviewer_id="chief")
    v = changes.apply_changes(db, [a], reviewer_id="chief")
    assert v.penalty_text == "Up to $1,000" and v.cure_period == "None"


def test_requirement_copied_forward_unchanged_is_not_a_change(master):
    """Copying a version gives its requirements new ids; only their content counts."""
    db = master
    law = _law(db)
    code = db.query(__import__("app.regmaster.models", fromlist=["Requirement"]).Requirement).filter_by(law_version_id=law.current_version_id).first().code
    a = changes.propose(db, actor_id="u1", regulation_id=law.id, field_path=f"requirement.{code}", new_value=None, summary="Remove a requirement", origin="admin_edit")
    b = changes.propose(db, actor_id="u2", regulation_id=law.id, field_path="law.cure_period", new_value="None", summary="Cure", origin="admin_edit")
    changes.apply_changes(db, [b], reviewer_id="chief")
    changes.apply_changes(db, [a], reviewer_id="chief")
    assert a.status == "approved"
