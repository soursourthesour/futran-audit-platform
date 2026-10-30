"""Intro letter rendering (§25.5)."""
import pytest

from app.engagements.models import ClientRequirement
from app.reference.jurisdictions import by_code
from app.regmaster import engine, letter
from app.regmaster.models import ClientGeography, IntroLetter
from app.regmaster.seed import find_law, seed_regmaster
from tests.factories import make_org


@pytest.fixture
def org(matrix):
    db = matrix
    seed_regmaster(db)
    o = make_org(db)
    db.add(ClientGeography(organization_id=o.id, jurisdiction_id=by_code(db, "US-NYC").id, basis="office", source="manual"))
    ada = find_law(db, "US", "Americans with Disabilities")
    db.add(ClientRequirement(organization_id=o.id, regulation_id=ada.id, source="manual", in_scope=True))
    db.flush()
    engine.run(db, o.id)
    return o


def _letter(db, o):
    x = IntroLetter(organization_id=o.id, version_no=1, status="draft", body=letter.build_body(db, o))
    return x


def test_letter_has_no_raw_markup_and_keeps_the_page_break(matrix, org):
    html = letter.to_html(_letter(matrix, org))
    assert "&lt;" not in html and 'class="pagebreak"' in html


def test_law_without_a_main_duty_uses_its_obligations_not_a_placeholder(matrix, org):
    body = letter.build_body(matrix, org)
    ada = next(x for x in body["laws"] if "Disabilities" in x["law"])
    assert ada["main_duty"] and "law record" not in ada["main_duty"]
