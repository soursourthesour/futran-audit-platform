"""Spec B8: EU AI Act requirements are seeded into the law library as Requirement rows, only where the library lacks
them. Rows already there are linked, never duplicated or changed; a second run adds nothing."""
from sqlalchemy import select

from app.euaiact import lawseed, rules
from app.laws.models import Regulation
from app.regmaster.models import LawVersion, Requirement


def _eu(db):
    from app.regmaster.seed import find_law

    reg = find_law(db, "EU", "2024/1689")
    return reg, db.get(LawVersion, reg.current_version_id)


def _rows(db, v):
    return {r.code: r for r in db.scalars(select(Requirement).where(Requirement.law_version_id == v.id))}


def test_adds_only_the_missing_articles_and_links_the_rest(matrix):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(matrix)
    db = matrix
    reg, v = _eu(db)
    before = {c: (r.text, r.citation) for c, r in _rows(db, v).items()}
    assert set(before) == {f"EU-{n:02d}" for n in range(1, 14)}

    out = lawseed.ensure_requirements(db)
    added = {r["ref"] for r in out["added"]}
    assert added == {"5", "9", "10", "11", "12", "13", "14(1)", "15", "17", "23", "24", "43", "47", "49", "53", "72"}
    assert out["found"] == []  # every library row in the data file is a gap in the starter library
    rows = _rows(db, v)
    for code, (text, cit) in before.items():  # existing rows untouched
        assert (rows[code].text, rows[code].citation) == (text, cit)
    new = [r for c, r in rows.items() if c not in before]
    assert len(new) == 16 and all(r.verify_flag for r in new)
    assert sorted(r.code for r in new) == [f"EU-{n:02d}" for n in range(14, 30)]
    art23 = next(r for r in new if r.citation.startswith("EU AI Act Art. 23"))
    assert art23.applies_to == ["importer"] and art23.role_id is not None and art23.source_url and "eur-lex" in art23.source_url

    # every obligation on the workspace now has a library row
    for o in rules.data()["obligations"]:
        assert lawseed.library_row(db, o["ref"]) is not None, o["key"]

    # a second run finds everything and adds nothing
    again = lawseed.ensure_requirements(db)
    assert again["added"] == [] and len(again["found"]) == 16
    assert len(_rows(db, v)) == 29


def test_a_row_someone_already_added_is_linked_not_duplicated(matrix):
    from app.regmaster.seed import seed_regmaster

    seed_regmaster(matrix)
    db = matrix
    _reg, v = _eu(db)
    db.add(Requirement(law_version_id=v.id, code="EU-14", order=99, text="Risk management (added by the Chief Auditor)", citation="EU AI Act Art. 9"))
    db.flush()
    out = lawseed.ensure_requirements(db)
    assert "9" not in {r["ref"] for r in out["added"]} and "9" in {r["ref"] for r in out["found"]}
    rows = _rows(db, v)
    assert sum(1 for r in rows.values() if rules.article_refs(r.citation)[:1] == ["9"]) == 1
    assert len({r.code for r in rows.values()}) == len(rows)  # codes stay unique (EU-14 was taken)


def test_no_eu_ai_act_in_the_library_changes_nothing(db):
    out = lawseed.ensure_requirements(db)
    assert out == {"added": [], "found": [], "missing_law": True}
    assert db.scalar(select(Regulation.id)) is None
