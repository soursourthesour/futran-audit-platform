from datetime import date

import pytest
from sqlalchemy import select

from app.laws.publish import current_regulations
from app.reference.models import Jurisdiction
from app.regmaster.models import ClientLawApplicability, LawVersion, Requirement, Source
from tests.wsd_world import HIRING_CASE, lit  # noqa: F401


@pytest.fixture
def reg(db, lit):
    """Illinois laws with version 1, an allowlist, and ABC Corp in scope of the first Illinois law."""
    il = db.scalar(select(Jurisdiction).where(Jurisdiction.code == "US-IL"))
    laws = sorted([r for r in current_regulations(db) if r.jurisdiction_id == il.id], key=lambda r: r.short_name)
    for r in laws:
        if r.current_version_id is None:
            v = LawVersion(regulation_id=r.id, version_no=1, status="in_force", effective_on=date(2026, 1, 1), scope_text="Employers using AI in employment decisions")
            db.add(v)
            db.flush()
            r.current_version_id = v.id
    law = laws[0]
    db.add(Requirement(law_version_id=law.current_version_id, code="IL-01", order=1, text="Notify employees before AI is used.", needed_by_stage="go_live"))
    db.add_all([
        Source(jurisdiction_id=il.id, name="Illinois General Assembly", url="https://www.ilga.gov/", domain="www.ilga.gov", kind="official"),
        Source(jurisdiction_id=il.id, name="Illinois Department of Human Rights", url="https://dhr.illinois.gov/", domain="dhr.illinois.gov", kind="official"),
        Source(jurisdiction_id=il.id, name="A law firm blog", url="https://lawfirm.example/", domain="lawfirm.example", kind="secondary"),
    ])
    db.add(ClientLawApplicability(organization_id=lit["abc"].id, regulation_id=law.id, law_version_id=law.current_version_id, in_scope=True, reason_text="Employees in Illinois"))
    db.commit()
    return {"il": il, "laws": laws, "law": law}


def change(law, **kw):
    base = {"change_type": "effective_date", "regulation_id": law.id, "field_path": "law.effective_on", "old_value": "2026-01-01", "new_value": "2027-01-01",
            "summary": "Effective date moved to 1 January 2027.", "source_url": "https://www.ilga.gov/legislation/publicacts/fulltext.asp?Name=104-0001",
            "source_quote": "This Act takes effect January 1, 2027.", "confidence": "high"}
    return base | kw
