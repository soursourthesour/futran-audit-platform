from collections import Counter

import pytest
from sqlalchemy import select

from app.questionnaire.models import ChecklistItem, Question, TemplateVersion
from app.questionnaire.seed import load_question_bank


@pytest.fixture
def bank(db):
    tv = load_question_bank(db)
    return db, tv


def codes(db, tv, **filters):
    stmt = select(Question.code).where(Question.template_version_id == tv.id)
    for k, v in filters.items():
        stmt = stmt.where(getattr(Question, k) == v)
    return set(db.scalars(stmt))


def _range(prefix, n, width=2):
    return {f"{prefix}.{i:0{width}d}" for i in range(1, n + 1)}


SPEC_CODES = (
    _range("3.1", 10) | _range("3.2", 10) | _range("3.3", 10) | {"3.3.05s"}
    | _range("5.1", 8) | _range("5.1a", 6) | _range("5.2", 8) | _range("5.3", 9)
    | _range("6.1", 8) | _range("6.2", 9) | _range("6.3", 8)
    | {f"V.0{i}" for i in range(1, 9)}
    | _range("7.1", 8) | _range("7.2", 5)
    | _range("8.1", 10) | _range("8.2", 8) | _range("8.3", 8)
    | _range("9.2", 8)
)


def test_template_version_1_0_with_5_1a(bank):
    db, tv = bank
    assert (tv.name, tv.version, tv.addenda) == ("Futran AI System Audit", "1.0", ["5.1a"])
    assert db.query(TemplateVersion).count() == 1


def test_all_spec_codes_present(bank):
    db, tv = bank
    missing = SPEC_CODES - codes(db, tv)
    assert not missing, sorted(missing)


def test_engagement_level_governance_fields(bank):
    db, tv = bank
    eng = codes(db, tv, scope="engagement")
    assert {"4.1.01", "4.1.03", "4.1.07", "4.2.02", "4.2.05"} <= eng
    assert not (eng & SPEC_CODES)


def test_checklist_counts(bank):
    db, tv = bank
    counts = Counter(db.scalars(select(ChecklistItem.section).where(ChecklistItem.template_version_id == tv.id)))
    assert {k: counts[k] for k in ["4.3", "5.4", "6.4", "7.3", "8.4"]} == {"4.3": 10, "5.4": 17, "6.4": 10, "7.3": 10, "8.4": 11}
    pending = db.scalars(select(ChecklistItem).where(ChecklistItem.section == "5.4", ChecklistItem.pending_review.is_(True))).all()
    assert len(pending) == 5


def test_every_checklist_item_has_a_maturity_domain(bank):
    db, tv = bank
    domains = set(db.scalars(select(ChecklistItem.maturity_domain)))
    assert domains == {"governance", "data", "model", "bias", "oversight", "security", "incident", "vendor_risk"}


def test_light_set_is_3_5_7_2_9(bank):
    db, tv = bank
    light_sections = {s for s in db.scalars(select(Question.sub_section).where(Question.light.is_(True)))}
    assert light_sections == {"3.1", "3.2", "3.3", "5.1", "5.1a", "5.2", "5.3", "7.2", "9.2"}


def test_vendor_assurance_replaces_6_1_and_6_3(bank):
    db, tv = bank
    q = {c: db.scalar(select(Question).where(Question.code == c)) for c in ("6.1.01", "6.3.02", "V.01", "6.2.01", "9.2.01")}
    assert "vendor" not in q["6.1.01"].build_types and "vendor" not in q["6.3.02"].build_types
    assert q["V.01"].build_types == ["vendor", "hybrid"]
    assert q["6.2.01"].build_types is None  # bias testing applies to every build type
    assert q["9.2.01"].build_types == ["vendor", "hybrid"]


def test_intern_notes_are_futran_only_help(bank):
    db, _ = bank
    q = db.scalar(select(Question).where(Question.code == "6.2.01"))
    assert "Overall accuracy alone is not bias testing" in q.section_note
    assert q.help_text is None or "intern" not in q.help_text.lower()


def test_assessment_questions_are_auditor_only(bank):
    db, tv = bank
    assert {"3.3.05s", "3.3.08", "3.3.10", "5.1a.05", "5.1a.06", "6.3.01"} <= codes(db, tv, default_respondent="auditor")


def test_loader_idempotent(bank):
    db, tv = bank
    n = db.query(Question).count()
    tv2 = load_question_bank(db)
    assert tv2.id == tv.id and db.query(Question).count() == n
