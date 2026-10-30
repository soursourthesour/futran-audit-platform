"""Regulatory master models (spec §25.2). The tables other workstreams build on."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.laws.models import MatrixVersion, Regulation
from app.reference.models import Jurisdiction
from app.regmaster.models import (
    ChangeImpact,
    ClientGeography,
    ClientLawApplicability,
    CommitteeRule,
    IntroLetter,
    LawRoleMap,
    LawVersion,
    ProposedChange,
    Requirement,
    RoleCatalog,
    ScopeTest,
    Source,
)
from tests.factories import make_org


def _law(db, code="US-CO", name="SB 26-189"):
    j = db.query(Jurisdiction).filter_by(code=code).one_or_none() or Jurisdiction(code=code, name=code, level="state")
    db.add(j)
    v = MatrixVersion(label="t")
    db.add(v)
    db.flush()
    r = Regulation(jurisdiction_id=j.id, matrix_version_id=v.id, short_name=name, feature="consequential_decisions_admt", type="statute")
    db.add(r)
    db.flush()
    return j, r


def test_every_regmaster_table_exists(engine):
    names = set(inspect(engine).get_table_names())
    for t in ("law_versions", "scope_tests", "requirements", "role_catalog", "law_role_maps", "committee_rules", "reg_sources",
              "client_geographies", "client_law_applicability", "intro_letters", "proposed_changes", "change_impacts"):
        assert t in names, t
    cols = {c["name"] for c in inspect(engine).get_columns("regulations")}
    assert {"current_version_id", "binding", "topics"} <= cols
    jcols = {c["name"] for c in inspect(engine).get_columns("jurisdictions")}
    assert {"level", "parent_id"} <= jcols


def test_law_version_hangs_off_regulation_with_requirements_and_role_maps(db):
    j, r = _law(db)
    role = RoleCatalog(code="explainability_contact", number=15, name="Explainability contact", level="system", default_stage="go_live")
    src = Source(jurisdiction_id=j.id, name="Colorado General Assembly", url="https://leg.colorado.gov/bills/sb26-189", kind="official")
    db.add_all([role, src])
    db.flush()
    lv = LawVersion(regulation_id=r.id, version_no=1, status="enacted_not_in_force", signed_on=date(2026, 5, 14), compliance_on=date(2027, 1, 1), applies_to=["developer", "deployer"])
    db.add(lv)
    db.flush()
    r.current_version_id = lv.id
    req = Requirement(law_version_id=lv.id, code="CO-04", text="Explain an adverse outcome", applies_to=["deployer"], needed_by_stage="go_live", role_id=role.id, citation="SB 26-189", source_quote="...", source_id=src.id)
    rm = LawRoleMap(law_version_id=lv.id, role_id=role.id, level="required", needed_by_stage="go_live", requirement_ids=[])
    st = ScopeTest(law_version_id=lv.id, order=1, question_text="Does the client make decisions about Colorado residents?", answer_type="yes_no", in_scope_rule={"equals": "yes"})
    cr = CommitteeRule(law_version_id=lv.id, committee_type="ai_governance_committee", level="recommended", composition_text="Chair: accountable executive")
    db.add_all([req, rm, st, cr])
    db.flush()
    assert db.get(Regulation, r.id).current_version_id == lv.id
    assert db.query(Requirement).filter_by(law_version_id=lv.id).one().role_id == role.id


def test_client_side_rows_carry_the_tenant(db):
    org = make_org(db)
    j, r = _law(db)
    lv = LawVersion(regulation_id=r.id, version_no=1, status="in_force")
    db.add(lv)
    db.flush()
    db.add_all([
        ClientGeography(organization_id=org.id, jurisdiction_id=j.id, basis="office", source="wizard"),
        ClientLawApplicability(organization_id=org.id, regulation_id=r.id, law_version_id=lv.id, in_scope=False, reason_text="No Colorado operations or residents"),
        IntroLetter(organization_id=org.id, version_no=1, status="draft", body={}, law_versions_used=[lv.id]),
    ])
    db.flush()
    pc = ProposedChange(change_type="amendment", regulation_id=r.id, field_path="law.compliance_on", old_value="2026-06-30", new_value="2027-01-01", summary="x", source_url="https://leg.colorado.gov", source_quote="q", confidence="high")
    db.add(pc)
    db.flush()
    db.add(ChangeImpact(proposed_change_id=pc.id, organization_id=org.id, ai_system_ids=[], roles_affected=[], letter_update_needed=True))
    db.flush()
    assert pc.status == "pending"


MIGRATIONS = Path(__file__).resolve().parents[2]


def _alembic(url: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(MIGRATIONS / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS / "migrations"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, rev)


PRE_WS_A = "0e474e894577"


def test_migration_creates_version_one_for_every_current_law(tmp_path):
    path = tmp_path / "m.db"
    url = f"sqlite:///{path}"
    _alembic(url, PRE_WS_A)
    c = sqlite3.connect(path)
    c.execute("insert into jurisdictions (id, code, name, level, has_laws, active, created_at, updated_at) values ('j1','US-NYC','New York City','city',1,1,'2026-01-01','2026-01-01')")
    c.execute("insert into matrix_versions (id, label, origin, status, published_at) values ('v1','m','import','published','2026-01-01')")
    base = "insert into regulations (id, jurisdiction_id, matrix_version_id, short_name, feature, type, applies_to, verify_flag, public_summary, origin, created_at, effective_date_text, status_text, enforcer, superseded_by_id) values (?, 'j1', 'v1', ?, 'employment_hiring', 'statute', 'deployer', 0, 0, 'import', '2026-01-01', ?, ?, ?, ?)"
    c.execute(base, ("r2", "NYC Local Law 144", "5 July 2023", "In force", "DCWP", None))
    c.execute(base, ("r1", "NYC Local Law 144 (old)", None, None, None, "r2"))
    c.commit()
    c.close()
    _alembic(url, "head")
    c = sqlite3.connect(path)
    rows = c.execute("select regulation_id, version_no, status, enforcer, effective_text from law_versions").fetchall()
    assert rows == [("r2", 1, "in_force", "DCWP", "5 July 2023")]
    assert c.execute("select current_version_id is not null from regulations where id='r2'").fetchone() == (1,)
    assert c.execute("select current_version_id from regulations where id='r1'").fetchone() == (None,)
    assert c.execute("select count(*) from regulations").fetchone() == (2,)


@pytest.mark.parametrize("text,expected", [("In force", "in_force"), ("Enacted; effective 1 Jan 2027", "enacted_not_in_force"), ("Repealed", "repealed"), ("Delayed to 2027", "delayed"), (None, "in_force"),
                                           ("Not yet in force", "pending"), ("Signed; not yet in force", "pending"), ("Pending in committee", "pending")])
def test_status_text_maps_to_version_status(text, expected):
    from app.regmaster.versioning import status_from_text

    assert status_from_text(text, "statute") == expected


def test_guidance_type_maps_to_guidance_status():
    from app.regmaster.versioning import status_from_text

    assert status_from_text(None, "voluntary") == "guidance"


def test_migration_gives_approved_repeals_their_date_back(tmp_path):
    path = tmp_path / "r.db"
    url = f"sqlite:///{path}"
    _alembic(url, "4acc52a327dc")
    c = sqlite3.connect(path)
    c.execute("insert into jurisdictions (id, code, name, level, has_laws, active, created_at, updated_at) values ('j1','US-NYC','New York City','city',1,1,'2026-01-01','2026-01-01')")
    c.execute("insert into matrix_versions (id, label, origin, status, published_at) values ('m1','m','import','published','2026-01-01')")
    c.execute("insert into regulations (id, jurisdiction_id, matrix_version_id, short_name, feature, type, applies_to, verify_flag, public_summary, origin, created_at) values ('r1','j1','m1','LL144','employment_hiring','statute','deployer',0,0,'import','2026-01-01')")
    for vid, no, status in (("v1", 1, "in_force"), ("v2", 2, "repealed")):
        c.execute("insert into law_versions (id, regulation_id, version_no, status, verify_flag, created_at) values (?, 'r1', ?, ?, 0, '2026-01-01')", (vid, no, status))
    c.execute("insert into proposed_changes (id, origin, change_type, regulation_id, field_path, new_value, summary, confidence, status, created_at, applied_version_id) "
              "values ('p1','admin_edit','repeal','r1','repeal',?,'Repealed','high','approved','2026-01-01','v2')", ('{"status": "repealed", "effective_on": "2027-07-01"}',))
    c.commit()
    c.close()
    _alembic(url, "head")
    c = sqlite3.connect(path)
    assert c.execute("select id, repealed_on from law_versions order by id").fetchall() == [("v1", None), ("v2", "2027-07-01")]


def test_migration_corrects_not_yet_in_force_versions(tmp_path):
    """The v1 data move read "not yet in force" as in force; the correction leaves a person's own decision alone."""
    path = tmp_path / "s.db"
    url = f"sqlite:///{path}"
    _alembic(url, "b7d1e3a90c21")
    c = sqlite3.connect(path)
    c.execute("insert into jurisdictions (id, code, name, level, has_laws, active, created_at, updated_at) values ('j1','US-CO','Colorado','state',1,1,'2026-01-01','2026-01-01')")
    c.execute("insert into matrix_versions (id, label, origin, status, published_at) values ('m1','m','import','published','2026-01-01')")
    reg = "insert into regulations (id, jurisdiction_id, matrix_version_id, short_name, feature, type, applies_to, verify_flag, public_summary, origin, created_at, status_text) values (?, 'j1', 'm1', ?, 'employment_hiring', 'statute', 'deployer', 0, 0, 'import', '2026-01-01', ?)"
    c.execute(reg, ("r1", "SB 26-189", "Signed; not yet in force"))
    c.execute(reg, ("r2", "HB 1", "In force"))
    c.execute(reg, ("r3", "SB 2", "Not yet in force"))
    ver = "insert into law_versions (id, regulation_id, version_no, status, verify_flag, created_at) values (?, ?, 1, ?, 0, '2026-01-01')"
    c.execute(ver, ("v1", "r1", "in_force"))
    c.execute(ver, ("v2", "r2", "in_force"))
    c.execute(ver, ("v3", "r3", "in_force"))
    c.execute("insert into proposed_changes (id, origin, change_type, regulation_id, field_path, new_value, summary, confidence, status, created_at, applied_version_id) "
              "values ('p1','admin_edit','amendment','r3','law.status','\"in_force\"','Now in force','high','approved','2026-01-01','v3')")
    c.commit()
    c.close()
    _alembic(url, "head")
    _alembic(url, "head")  # idempotent
    c = sqlite3.connect(path)
    assert c.execute("select id, status from law_versions order by id").fetchall() == [("v1", "pending"), ("v2", "in_force"), ("v3", "in_force")]


def test_migration_switches_off_schedules_nobody_turned_on(tmp_path):
    path = tmp_path / "rs.db"
    url = f"sqlite:///{path}"
    _alembic(url, "c4e8f2b61d07")
    c = sqlite3.connect(path)
    row = "insert into refresh_settings (id, kind, schedule_enabled, every_days, scope_mode, jurisdiction_ids, checks, source_set, cost_cap_usd, updated_by, updated_at) values (?, ?, 1, 14, 'all', '[]', '[]', 'official', 5.0, ?, '2026-10-01')"
    c.execute(row, ("s1", "law", None))  # made by default when the screen first opened
    c.execute(row, ("s2", "litigation", "chief-1"))  # saved by the Chief Auditor
    c.commit()
    c.close()
    _alembic(url, "head")
    c = sqlite3.connect(path)
    assert c.execute("select kind, schedule_enabled from refresh_settings order by kind").fetchall() == [("law", 0), ("litigation", 1)]
