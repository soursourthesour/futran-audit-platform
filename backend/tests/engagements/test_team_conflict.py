"""One conflict-of-interest line per person, naming every role they hold (fixes 2026-10-27, item 1c)."""
import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.engagements.models import EngagementTeam
from tests.engagements.helpers import _new, _put, complete
from tests.factories import login_as, make_org, make_user


@pytest.fixture
def people(db, matrix):
    from app.reference.catalogs import load_catalogs
    from app.reference.templates import load_templates

    load_templates(db)
    load_catalogs(db)
    f = make_org(db, type="futran")
    p = {
        "aud": make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test"),
        "chief": make_user(db, f, roles=["chief_auditor", "auditor"], name="Dana Whitfield", email="dana@futran.test"),
        "chief2": make_user(db, f, roles=["chief_auditor"], name="Dan Chief", email="dan@futran.test"),
        "em": make_user(db, f, roles=["engagement_manager"], name="Eli Manager", email="eli@futran.test"),
    }
    db.commit()
    return p


def _dana_twice(p, confirmed=True):
    return [
        {"user_id": p["chief"].id, "role": "chief_auditor", "conflict_confirmed": confirmed},
        {"user_id": p["chief"].id, "role": "auditor", "conflict_confirmed": confirmed},
        {"user_id": p["em"].id, "role": "engagement_manager", "conflict_confirmed": True},
        {"user_id": p["aud"].id, "role": "auditor", "conflict_confirmed": True},
    ]


def test_confirmation_records_every_role_the_person_holds(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    _put(client, cid, "scope", {"team": _dana_twice(people)})
    rows = db.scalars(select(EngagementTeam).where(EngagementTeam.user_id == people["chief"].id, EngagementTeam.deleted_at.is_(None))).all()
    assert len(rows) == 2
    assert all(r.conflict_confirmed_roles == ["chief_auditor", "auditor"] for r in rows)
    def entries():
        return db.scalars(select(AuditLog).where(AuditLog.action == "team.conflict_confirmed", AuditLog.after["user_id"].as_string() == people["chief"].id).order_by(AuditLog.at)).all()

    assert entries()[-1].summary.startswith("Dana Whitfield confirmed no conflict of interest as Chief Auditor (Lead Auditor) and Auditor")
    assert entries()[-1].after["roles"] == ["chief_auditor", "auditor"]
    n = len(entries())
    _put(client, cid, "scope", {"team": _dana_twice(people)})  # no change, no new entry
    assert len(entries()) == n


def test_wizard_lists_each_person_once_with_their_roles(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    _put(client, cid, "scope", {"team": _dana_twice(people)})
    w = client.get(f"/api/v1/clients/{cid}/wizard").json()
    dana = [m for m in w["scope"]["people"] if m["name"] == "Dana Whitfield"]
    assert len(dana) == 1
    assert dana[0]["roles"] == ["chief_auditor", "auditor"]
    assert dana[0]["role_label"] == "Chief Auditor (Lead Auditor) and Auditor"
    assert dana[0]["conflict_confirmed"] is True


def test_unconfirmed_person_named_once_with_roles_at_submit(client, db, people):
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    _put(client, cid, "scope", {"team": _dana_twice(people, confirmed=False)})
    msgs = [e["message"] for e in client.post(f"/api/v1/clients/{cid}/submit").json()["errors"] if e["field"] == "scope.team"]
    assert msgs.count("Dana Whitfield has not confirmed there is no conflict of interest as Chief Auditor (Lead Auditor) and Auditor.") == 1
    assert not [m for m in msgs if m.startswith("Dana Whitfield has not confirmed") and m.endswith("as Auditor.")]


def test_client_page_package_and_letter_list_each_person_once(client, db, people, settings, tmp_path):
    settings.file_store = f"local:{tmp_path}"
    client.app.state.settings = settings
    login_as(client, db, people["aud"])
    cid = _new(client)["client_id"]
    complete(client, cid, people)
    _put(client, cid, "scope", {"team": _dana_twice(people)})
    assert client.post(f"/api/v1/clients/{cid}/submit").status_code == 200
    login_as(client, db, people["chief2"])
    page = client.get(f"/api/v1/clients/{cid}").json()
    assert [m["name"] for m in page["team"]].count("Dana Whitfield") == 1
    assert {"name": "Dana Whitfield", "role_label": "Chief Auditor (Lead Auditor) and Auditor"} in [{"name": m["name"], "role_label": m["role_label"]} for m in page["team"]]
    pkg = client.get(f"/api/v1/clients/{cid}/package").json()
    assert [t for t in pkg["summary"]["team"] if t.startswith("Dana Whitfield")] == ["Dana Whitfield (Chief Auditor (Lead Auditor) and Auditor)"]
    letter = pkg["documents"][0]
    body = client.get(f"/api/v1/packages/documents/{letter['id']}/preview").json()["body_md"]
    assert body.count("| Dana Whitfield |") == 1
    assert "| Dana Whitfield | Chief Auditor (Lead Auditor) and Auditor |" in body
    guide = next(d for d in pkg["documents"] if d["item"] == 6)
    gbody = client.get(f"/api/v1/packages/documents/{guide['id']}/preview").json()["body_md"]
    assert gbody.count("Dana Whitfield (") == 1
