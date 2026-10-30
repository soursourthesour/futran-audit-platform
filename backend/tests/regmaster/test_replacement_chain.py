"""A Reference data edit, a matrix re-import or an accepted law update replaces the Regulation row (superseded_by_id).
Everything that keys on a law follows that chain to the live row, and links to the old row move to the new one."""
import pytest
from sqlalchemy import select

from app.engagements.models import ClientRequirement
from app.laws.publish import chain_ids, current_regulations, current_version_of
from app.laws.service import edit_law
from app.reference.jurisdictions import by_code
from app.regmaster import changes, engine, letter
from app.regmaster.models import ChangeImpact, ClientGeography, ClientLawApplicability, IntroLetter, LawVersion, ScopeTest
from app.regmaster.seed import ensure_versions, find_law, seed_regmaster
from tests.factories import make_org, make_user


@pytest.fixture
def master(matrix):
    seed_regmaster(matrix)
    return matrix


@pytest.fixture
def staff(master):
    futran = make_org(master, type="futran", name="Futran X")
    admin = make_user(master, futran, roles=["admin"], name="Ann Admin", email="ann@futran.test")
    chief = make_user(master, futran, roles=["chief_auditor"], name="Carl Chief", email="carl@futran.test")
    return admin, chief


def _untested_law(db):
    tested = set(db.scalars(select(ScopeTest.law_version_id).distinct()))
    return next(r for r in current_regulations(db) if r.current_version_id not in tested)


def test_law_ticked_again_after_unticking_is_back_in_scope(master):
    db = master
    org = make_org(db)
    law = _untested_law(db)
    cr = ClientRequirement(organization_id=org.id, regulation_id=law.id, in_scope=True)
    db.add(cr)
    db.flush()
    engine.run(db, org.id)
    cr.in_scope = False
    db.flush()
    engine.run(db, org.id)
    row = db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id == law.id))
    assert row.deleted_at is not None
    cr.in_scope = True
    db.flush()
    engine.run(db, org.id)
    db.refresh(row)
    assert row.deleted_at is None and row.in_scope


def test_approved_change_lands_on_the_live_law_after_a_reference_edit(master, staff):
    db = master
    admin, chief = staff
    law = find_law(db, "US-NYC", "Local Law 144")
    pc = changes.propose(db, actor_id=admin.id, regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,500 per violation",
                         summary="Penalty amount", origin="admin_edit")
    edit_law(db, admin, law.id, {"enforcer": "NYC Department of Consumer and Worker Protection"})
    db.flush()
    ensure_versions(db)
    changes.apply_changes(db, [pc], chief.id)
    live = current_version_of(db, law.id)
    assert live.id != law.id
    assert db.get(LawVersion, live.current_version_id).penalty_text == "Up to $1,500 per violation"
    assert law.current_version_id == db.scalar(select(LawVersion.id).where(LawVersion.id == law.current_version_id))  # the dead row is untouched


def test_changes_to_old_and_live_row_become_one_version(master, staff):
    db = master
    admin, chief = staff
    law = find_law(db, "US-NYC", "Local Law 144")
    a = changes.propose(db, actor_id=admin.id, regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,500", summary="Penalty", origin="admin_edit")
    live = edit_law(db, admin, law.id, {"enforcer": "DCWP"})
    db.flush()
    ensure_versions(db)
    b = changes.propose(db, actor_id=admin.id, regulation_id=live.id, field_path="law.cure_period", new_value="None", summary="Cure", origin="admin_edit")
    before = db.scalar(select(LawVersion.version_no).where(LawVersion.id == live.current_version_id))
    v = changes.apply_changes(db, [a, b], chief.id)
    assert v.regulation_id == live.id and v.version_no == before + 1
    assert v.penalty_text == "Up to $1,500" and v.cure_period == "None"


def test_edit_moves_applicability_and_register_links_to_the_new_row(master, staff):
    from app.register.models import RegisterSystem, RegisterSystemLaw

    db = master
    admin, _ = staff
    org = make_org(db)
    law = find_law(db, "US-NYC", "Local Law 144")
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, "US-NYC").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, org.id)
    engine.override(db, org.id, law.id, False, "No hiring in New York City", None)
    s = RegisterSystem(organization_id=org.id, reference="AIS-001", name="Screening", type="vendor_app", sourcing="vendor")
    db.add(s)
    db.flush()
    db.add(RegisterSystemLaw(organization_id=org.id, register_system_id=s.id, regulation_id=law.id))
    db.flush()
    new = edit_law(db, admin, law.id, {"enforcer": "DCWP"})
    db.flush()
    rows = list(db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id.in_([law.id, new.id]))))
    assert [r.regulation_id for r in rows] == [new.id]
    assert rows[0].override and not rows[0].in_scope and rows[0].reason_text == "No hiring in New York City"
    assert db.scalar(select(RegisterSystemLaw.regulation_id).where(RegisterSystemLaw.register_system_id == s.id)) == new.id
    engine.run(db, org.id)  # the override survives the next run
    row = db.scalar(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id == new.id))
    assert row.override and not row.in_scope


def test_impacts_follow_the_chain(master, staff):
    db = master
    admin, _ = staff
    org = make_org(db)
    law = find_law(db, "US-NYC", "Local Law 144")
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, "US-NYC").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, org.id)
    edit_law(db, admin, law.id, {"enforcer": "DCWP"})
    db.flush()
    ensure_versions(db)
    pc = changes.propose(db, actor_id=admin.id, regulation_id=law.id, field_path="law.penalty_text", new_value="Up to $1,500", summary="Penalty", origin="admin_edit")
    assert [i.organization_id for i in db.scalars(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc.id))] == [org.id]


def test_confirmed_law_stays_a_candidate_after_a_reference_edit(master, staff):
    db = master
    admin, _ = staff
    org = make_org(db)
    law = _untested_law(db)
    db.add(ClientRequirement(organization_id=org.id, regulation_id=law.id, in_scope=True))
    db.flush()
    new = edit_law(db, admin, law.id, {"enforcer": "Someone else"})
    db.flush()
    ensure_versions(db)
    assert new.id in {r.id for r, _v in engine.candidate_laws(db, org.id)}


def test_changes_since_letter_follow_the_chain(master, staff):
    db = master
    admin, _ = staff
    org = make_org(db)
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, "US-NYC").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, org.id)
    body = letter.build_body(db, org)
    db.add(IntroLetter(organization_id=org.id, version_no=1, status="sent", body=body, law_versions_used=[x["law_version_id"] for x in body["laws"]]))
    db.flush()
    law = find_law(db, "US-NYC", "Local Law 144")
    edit_law(db, admin, law.id, {"enforcer": "DCWP"})
    db.flush()
    engine.run(db, org.id)
    texts = [i["text"] for i in letter.changes_since(db, org.id)["items"]]
    assert not [t for t in texts if "now applies" in t or "no longer applies" in t], texts


def test_chain_ids_lists_every_row_of_the_law(master, staff):
    db = master
    admin, _ = staff
    law = find_law(db, "US-NYC", "Local Law 144")
    mid = edit_law(db, admin, law.id, {"enforcer": "A"})
    db.flush()
    last = edit_law(db, admin, mid.id, {"enforcer": "B"})
    db.flush()
    assert chain_ids(db, mid.id) == [law.id, mid.id, last.id]
    assert current_version_of(db, law.id).id == last.id


def test_start_up_repair_moves_links_left_on_replaced_rows(master, staff):
    """Laptop data written before the fix: rows still point at the replaced law, and the engine made a second row."""
    from app.regmaster.startup import repair_replaced_links

    db = master
    admin, _ = staff
    org = make_org(db)
    law = find_law(db, "US-NYC", "Local Law 144")
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, "US-NYC").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, org.id)
    engine.override(db, org.id, law.id, False, "No hiring in New York City", None)
    # replace the row the old way: no links moved
    from app.laws.models import Regulation

    data = {c.key: getattr(law, c.key) for c in Regulation.__table__.columns if c.key not in ("id", "created_at", "superseded_by_id", "retired_in_version_id")}
    new = Regulation(**data)
    db.add(new)
    db.flush()
    law.superseded_by_id = new.id
    db.flush()
    ensure_versions(db)
    db.add(ClientLawApplicability(organization_id=org.id, regulation_id=new.id, law_version_id=new.current_version_id, in_scope=True, reason_text="Operates in New York City"))
    db.flush()
    assert repair_replaced_links(db) >= 1
    live = list(db.scalars(select(ClientLawApplicability).where(ClientLawApplicability.organization_id == org.id, ClientLawApplicability.regulation_id.in_([law.id, new.id]),
                                                                  ClientLawApplicability.deleted_at.is_(None))))
    assert [(r.regulation_id, r.override, r.in_scope) for r in live] == [(new.id, True, False)]
    assert repair_replaced_links(db) == 0  # idempotent
