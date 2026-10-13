import shutil
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select

from app.engagements.models import ClientRequirement
from app.laws.importer import parse_workbook
from app.laws.models import MatrixVersion, Regulation
from app.laws.publish import current_regulations, publish
from app.reference.jurisdictions import seed_iso
from app.reference.models import Jurisdiction
from tests.factories import make_org, make_user

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"


@pytest.fixture(scope="module")
def preview():
    return parse_workbook(WORKBOOK)


@pytest.fixture
def admin(db):
    seed_iso(db)
    f = make_org(db, type="futran")
    return make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")


def test_publish_creates_version_and_regulations(db, preview, admin):
    v = publish(db, preview, admin, edits={})
    assert v.status == "published" and v.status_date.isoformat() == "2026-10-05"
    n = len([r for r in preview.rows if r.kind == "regulation"])
    assert len(current_regulations(db)) == n
    ny = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US-NY"))
    assert ny.has_laws is True
    assert db.scalar(select(Jurisdiction).where(Jurisdiction.code == "EU")).feature_notes["employment_hiring"]


def test_publish_applies_short_name_edits(db, preview, admin):
    row = next(r for r in preview.rows if r.kind == "regulation" and r.jurisdiction_code == "US-CO")
    publish(db, preview, admin, edits={row.row_key: "Colorado SB 26-189 (ADMT)"})
    assert db.scalar(select(Regulation).where(Regulation.source_row_ref == row.row_key)).short_name == "Colorado SB 26-189 (ADMT)"


def test_republish_same_workbook_keeps_identity(db, preview, admin):
    publish(db, preview, admin, edits={})
    ids = {r.id for r in current_regulations(db)}
    v2 = publish(db, preview, admin, edits={})
    assert {r.id for r in current_regulations(db)} == ids
    assert db.query(MatrixVersion).filter_by(status="superseded").count() == 1
    assert v2.status == "published"


def test_reimport_keeps_referenced_and_supersedes(db, preview, admin, tmp_path):
    publish(db, preview, admin, edits={})
    title_vii = next(r for r in current_regulations(db) if r.short_name.startswith("Title VII"))
    org = make_org(db, type="client", name="ABC Corp")
    db.add(ClientRequirement(organization_id=org.id, regulation_id=title_vii.id, source="auto", in_scope=True))
    db.flush()
    copy = tmp_path / "matrix.xlsx"
    shutil.copy(WORKBOOK, copy)
    wb = openpyxl.load_workbook(copy)
    ws = wb["Federal Laws"]
    for row in ws.iter_rows(min_row=5):
        if row[1].value and str(row[1].value).startswith("Title VII"):
            row[5].value = "Changed obligations text."
    wb.save(copy)
    publish(db, parse_workbook(copy), admin, edits={})
    old = db.get(Regulation, title_vii.id)
    assert old is not None and old.superseded_by_id is not None
    new = db.get(Regulation, old.superseded_by_id)
    assert new.obligations_text == "Changed obligations text."
    assert new in current_regulations(db)
    assert old not in current_regulations(db)
