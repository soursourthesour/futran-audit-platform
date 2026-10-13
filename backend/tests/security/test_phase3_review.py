"""Regression tests for the Phase 3 review findings (C1, I1–I7 and the minors fixed with them)."""
import csv
import io
from io import BytesIO

import pytest
from docx import Document
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.engagements.models import ClientLocation, ClientRequirement, Engagement
from app.files.models import FileObject
from app.files.service import read
from app.initiation.models import InitiationPackage, PackageDocument
from app.laws.models import Regulation
from app.signoffs.models import Signature, SignOff
from app.tenancy.models import User
from tests.engagements.helpers import _new, _put, complete
from tests.factories import login_as, make_org, make_user
from tests.initiation.conftest import APPROVAL, people, submitted  # noqa: F401


def _approve(client, db, people, cid):
    login_as(client, db, people["chief"])
    r = client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL)
    assert r.status_code == 200, r.text


# ---- C1: whoever edited or submitted a draft cannot approve it
def test_chief_who_edited_and_submitted_cannot_approve(client, db, people, submitted, settings, tmp_path):
    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    login_as(client, db, people["chief"])
    _put(client, cid, "scope", {"exclusions": "Chief's edit"})
    assert client.post(f"/api/v1/clients/{cid}/submit").status_code == 200
    r = client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL)
    assert r.status_code == 403
    login_as(client, db, people["chief2"])
    assert client.post(f"/api/v1/clients/{cid}/approve", json=APPROVAL).status_code == 200
    e = db.scalar(select(Engagement).where(Engagement.client_id == cid))
    db.refresh(e)
    assert e.submitted_by == people["chief"].id
    so = db.scalar(select(SignOff).where(SignOff.engagement_id == e.id))
    assert people["chief"].id in so.excluded_signer_ids
    # Cara prepared it, so she cannot sign sign-off 1 for Futran either
    login_as(client, db, people["chief"])
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Cara Chief"}).status_code == 403


# ---- I1: merge values cannot break the letter's tables or inject links
def test_merge_values_cannot_break_letter_tables(client, db, people, submitted, settings):
    cid, e = submitted()
    login_as(client, db, people["aud"])
    e.status = "draft"
    db.commit()
    _put(client, cid, "scope", {"business_processes": "Screening.\nRanking of applicants.", "departments": ["R|D", "HR"], "planned_systems": ["Tool [click](http://evil.example)"]})
    client.post(f"/api/v1/clients/{cid}/submit")
    login_as(client, db, people["chief"])
    letter = client.get(f"/api/v1/clients/{cid}/package").json()["documents"][0]
    doc = Document(BytesIO(read(settings, db.get(FileObject, letter["docx_file_id"]))))
    scope = doc.tables[0]
    rows = {r.cells[0].text: r.cells[1].text for r in scope.rows}
    assert rows["Departments in scope"] == "R|D, HR"
    assert "Screening. Ranking of applicants." in rows["Business processes"]
    assert len(scope.rows) == 7  # header + 6 rows, nothing split off
    html = client.get(f"/api/v1/packages/documents/{letter['id']}/preview").json()["html"]
    assert "<a href" not in html and "[click](http://evil.example)" in html


# ---- I2: generated CSV is real CSV and formula-safe
def test_department_csv_is_quoted_and_formula_safe(client, db, people, submitted, settings):
    cid, e = submitted()
    login_as(client, db, people["aud"])
    e.status = "draft"
    db.commit()
    _put(client, cid, "scope", {"departments": ["Sales, Marketing", '=HYPERLINK("http://x","y")', "HR"]})
    client.post(f"/api/v1/clients/{cid}/submit")
    login_as(client, db, people["chief"])
    dept = client.get(f"/api/v1/clients/{cid}/package").json()["documents"][3]
    rows = list(csv.reader(io.StringIO(read(settings, db.get(FileObject, dept["csv_file_id"])).decode())))
    assert rows[0] == ["department", "head_name", "head_email", "headcount"]
    assert [r[0] for r in rows[1:]] == ["Sales, Marketing", "'=HYPERLINK(\"http://x\",\"y\")", "HR"]
    assert all(len(r) == 4 for r in rows)


# ---- I3: superseded and retired laws
def test_requirements_follow_law_versions(client, db, people, submitted):
    from app.laws.service import edit_law

    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    e = db.scalar(select(Engagement).where(Engagement.client_id == cid))
    req = db.scalar(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.regulation_id.is_not(None), ClientRequirement.deleted_at.is_(None)))
    old_id = req.regulation_id
    new = edit_law(db, people["chief"], old_id, {"obligations_text": "Updated."})
    db.commit()
    w = client.get(f"/api/v1/clients/{cid}/wizard").json()
    ids = [r["regulation_id"] for r in w["locations"]["requirements"]]
    assert new.id in ids and old_id not in ids
    # saving the old id maps it to the current version, without duplicating it
    out = _put(client, cid, "requirements", {"requirements": [{"regulation_id": old_id, "label": "x", "source": "auto"}, {"regulation_id": new.id, "label": "x", "source": "auto"}]})
    assert out["errors"] == []
    live = db.scalars(select(ClientRequirement).where(ClientRequirement.engagement_id == e.id, ClientRequirement.deleted_at.is_(None))).all()
    assert [r.regulation_id for r in live] == [new.id]
    # a retired law is refused
    new.retired_in_version_id = new.matrix_version_id
    db.commit()
    out = _put(client, cid, "requirements", {"requirements": [{"regulation_id": new.id, "label": "x", "source": "auto"}]})
    assert out["errors"] == [{"field": "requirements.0", "message": "This law is no longer in the matrix."}]


# ---- I4: double submit, approve and sign
def test_status_moves_are_compare_and_set(client, db, people, submitted):
    from app.core.errors import Conflict
    from app.engagements.service import transition

    cid, e = submitted()
    stale = db.get(Engagement, e.id)
    db.execute(Engagement.__table__.update().where(Engagement.id == e.id).values(status="initiated"))
    with pytest.raises(Conflict):
        transition(db, people["chief"], stale, "initiated")  # object still says pending_approval


def test_signature_unique_per_role(db):
    names = {tuple(c.columns.keys()) for c in Signature.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert ("sign_off_id", "role") in names and ("sign_off_id", "user_id") in names
    pkg = {tuple(c.columns.keys()) for c in InitiationPackage.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"}
    assert ("engagement_id", "version") in pkg


# ---- I5: package edits survive a return and are locked outside approval
def test_package_edits_carry_forward_and_lock(client, db, people, submitted):
    cid, e = submitted()
    login_as(client, db, people["chief"])
    doc = client.get(f"/api/v1/clients/{cid}/package").json()["documents"][1]
    client.put(f"/api/v1/packages/documents/{doc['id']}", json={"body_md": "# Roles\n\nChief's wording."})
    client.post(f"/api/v1/clients/{cid}/return", json={"comment": "Fix the dates."})
    # while the draft is with the author, the old package cannot be edited
    assert client.put(f"/api/v1/packages/documents/{doc['id']}", json={"body_md": "x"}).status_code == 409
    login_as(client, db, people["aud"])
    client.post(f"/api/v1/clients/{cid}/submit")
    login_as(client, db, people["chief"])
    new = client.get(f"/api/v1/clients/{cid}/package").json()
    assert new["version"] == 2
    roles = new["documents"][1]
    assert roles["edited"] is True
    assert "Chief's wording." in client.get(f"/api/v1/packages/documents/{roles['id']}/preview").json()["html"]


# ---- I6: wizard edits are audited
def test_wizard_saves_are_audited(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    _put(client, cid, "company", {"legal_name": "ABC Corp Inc."})
    _put(client, cid, "company", {"legal_name": "ABC Corp Inc."})  # no change, no entry
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "wizard.save")).all()
    assert len(logs) == 1
    assert logs[0].after == {"legal_name": "ABC Corp Inc."} and logs[0].before == {"legal_name": None} and logs[0].actor_id == people["aud"].id


# ---- I7: file downloads by link type
def test_file_access_by_link_type(client, db, people, submitted, settings):
    from app.files.service import upload

    cid, e = submitted()
    _approve(client, db, people, cid)
    pkgs = db.scalars(select(InitiationPackage).where(InitiationPackage.engagement_id == e.id)).all()
    sent = next(p for p in pkgs if p.status == "sent")
    letter = db.scalar(select(PackageDocument).where(PackageDocument.package_id == sent.id, PackageDocument.item == 1))
    maria = db.scalar(select(User).where(User.email == "maria@abc.test"))
    maria.status = "active"
    odd = upload(db, settings, people["aud"], data=b"internal", filename="qa-notes.txt", content_type="text/html", organization_id=cid, engagement_id=e.id, linked_type="qa_note", linked_id="x")
    db.commit()
    login_as(client, db, maria)
    r = client.get(f"/api/v1/files/{letter.pdf_file_id}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get(f"/api/v1/files/{odd.id}").status_code == 404  # unknown link types are Futran-only
    login_as(client, db, people["aud"])
    r = client.get(f"/api/v1/files/{odd.id}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")  # type from the extension, not the uploader


def test_html_uploads_refused(db, settings, people):
    from app.core.errors import Invalid
    from app.files.service import upload

    org = make_org(db, name="Any")
    with pytest.raises(Invalid):
        upload(db, settings, None, data=b"<script>", filename="x.html", content_type="text/html", organization_id=org.id)


# ---- minors fixed with the pass
def test_client_cannot_read_wizard(client, db, people, submitted):
    cid, e = submitted()
    _approve(client, db, people, cid)
    maria = db.scalar(select(User).where(User.email == "maria@abc.test"))
    maria.status = "active"
    db.commit()
    login_as(client, db, maria)
    assert client.get(f"/api/v1/clients/{cid}/wizard").status_code == 404
    assert client.get(f"/api/v1/clients/{cid}/suggestions").status_code == 404


def test_autosave_keeps_rows_and_survives_bad_values(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    site = {"site_name": "HQ", "country_code": "US", "subdivision_code": "US-NY", "city": "New York", "employees_at_site": 40}
    for _ in range(3):  # the browser does not know the new id between saves
        _put(client, cid, "locations", {"locations": [site]})
    live = db.scalars(select(ClientLocation).where(ClientLocation.organization_id == cid, ClientLocation.deleted_at.is_(None))).all()
    assert len(live) == 1 and len(db.scalars(select(ClientLocation).where(ClientLocation.organization_id == cid)).all()) == 1
    out = _put(client, cid, "locations", {"locations": [{"id": live[0].id, "site_name": "HQ", "country_code": "ZZ", "employees_at_site": "lots"}]})
    assert {e["field"] for e in out["errors"]} == {"locations.locations.0.country_code", "locations.locations.0.employees_at_site"}
    db.refresh(live[0])
    assert live[0].deleted_at is None and live[0].employees_at_site == 40 and live[0].country_code == "US"
    out = _put(client, cid, "requirements", {"requirements": [{"label": "x" * 400, "source": "manual"}]})
    assert out["errors"][0]["field"] == "requirements.0.label"


def test_only_team_chief_signs_when_there_is_one(client, db, people, submitted):
    cid, e = submitted()
    _approve(client, db, people, cid)
    so = db.scalar(select(SignOff).where(SignOff.engagement_id == e.id))
    login_as(client, db, people["chief2"])
    assert client.post(f"/api/v1/signoffs/{so.id}/sign", json={"typed_name": "Dan Chief"}).status_code == 403


def test_markdown_images_not_rendered():
    from app.documents.render import render_markdown

    assert "<img" not in render_markdown("![x](https://tracker.example/p.png)")
