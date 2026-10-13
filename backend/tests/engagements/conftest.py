from pathlib import Path

import pytest

from app.laws.importer import parse_workbook
from app.laws.publish import publish
from app.reference.jurisdictions import seed_iso

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"


@pytest.fixture(scope="session")
def preview():
    return parse_workbook(WORKBOOK)


@pytest.fixture
def matrix(db, preview):
    seed_iso(db)
    publish(db, preview, None, {}, organization_id="futran")
    return db
