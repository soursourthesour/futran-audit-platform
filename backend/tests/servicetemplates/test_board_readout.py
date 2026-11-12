"""G-06 board readout pack (A-13, spec B6): an export from a signed report with a one-page summary, heat map, top 5
findings and roadmap. PDF only: PowerPoint needs a library the platform does not have."""
from app.engagements.models import Engagement
from app.reports.models import Report
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.reports.test_reports import ready  # noqa: F401


def _sign_final(db, e, *, content_hash=None):
    from app.reports.service import _content_data, _hash

    r = Report(organization_id=e.client_id, engagement_id=e.id, version="v1.1", status="final", body_md="Final report",
               content_hash=content_hash or _hash(_content_data(db, db.get(Engagement, e.id))))
    db.add(r)
    db.commit()
    return r


def test_board_readout_needs_a_signed_report_and_matches_it(client, db, ready, people):
    cid, e, maria, f = ready
    login_as(client, db, people["chief"])
    url = f"/api/v1/engagements/{e.id}/board-readout.pdf"
    r = client.get(url)
    assert r.status_code == 409 and "signed" in r.json()["detail"].lower()
    _sign_final(db, e, content_hash="0" * 64)
    assert client.get(url).status_code == 409  # the report changed after it was signed
    _sign_final(db, e)
    r = client.get(url)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    from app.servicetemplates.readout import readout_markdown

    md = readout_markdown(db, db.get(Engagement, e.id))
    for heading in ("One-page summary", "Heat map", "Top 5 findings", "Roadmap"):
        assert f"## {heading}" in md
    assert "Personal AI accounts used with applicant data" in md and "Governix" not in md
    assert md.startswith("# Board readout: ") and "{" not in md.splitlines()[0]


def test_people_outside_the_engagement_cannot_export_it(client, db, ready, people):
    from tests.factories import make_org, make_user

    cid, e, maria, f = ready
    _sign_final(db, e)
    other = make_user(db, make_org(db, name="Elsewhere"), roles=["caico"], name="Eve", email="eve@elsewhere.test")
    db.commit()
    login_as(client, db, other)
    assert client.get(f"/api/v1/engagements/{e.id}/board-readout.pdf").status_code == 404
