"""Proposed changes (§25.1 principle 1): nothing changes a live record until the Chief Auditor approves it.
On approval a new LawVersion is written with versioned maps; affected clients are re-run."""
import pytest
from sqlalchemy import select

from app.core.errors import Invalid
from app.reference.jurisdictions import by_code
from app.regmaster import changes, engine
from app.regmaster.models import ChangeImpact, ClientGeography, LawRoleMap, LawVersion, ProposedChange, Requirement, RoleCatalog
from app.regmaster.seed import find_law, seed_regmaster
from tests.factories import make_org


@pytest.fixture
def master(matrix):
    seed_regmaster(matrix)
    return matrix


def _co(db):
    return find_law(db, "US-CO", "^SB 26-189$")


def test_propose_keeps_live_record_unchanged(master):
    db = master
    reg = _co(db)
    v_before = reg.current_version_id
    pc = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="law.cure_period", new_value="30 days", summary="Cure period shortened", origin="admin_edit")
    assert pc.status == "pending" and pc.old_value.startswith("60 days")
    assert reg.current_version_id == v_before
    assert db.get(LawVersion, v_before).cure_period.startswith("60 days")


def test_propose_rejects_unknown_field(master):
    with pytest.raises(Invalid):
        changes.propose(master, actor_id="u1", regulation_id=_co(master).id, field_path="law.nonsense", new_value="x", summary="x", origin="admin_edit")


def test_auditor_suggestion_needs_a_source(master):
    with pytest.raises(Invalid):
        changes.propose(master, actor_id="u1", regulation_id=_co(master).id, field_path="law.cure_period", new_value="30 days", summary="x", origin="auditor_suggestion")


def test_duplicate_pending_proposal_is_merged(master):
    db = master
    reg = _co(db)
    a = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="law.cure_period", new_value="30 days", summary="x", origin="admin_edit")
    b = changes.propose(db, actor_id="u2", regulation_id=reg.id, field_path="law.cure_period", new_value="30 days", summary="x", origin="admin_edit")
    assert a.id == b.id


def test_approval_writes_next_version_with_copied_maps(master):
    db = master
    reg = _co(db)
    old = db.get(LawVersion, reg.current_version_id)
    pc = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="role_map.impact_assessment_owner", new_value={"level": "recommended", "needed_by_stage": "go_live"}, summary="Recommend an impact assessment owner", origin="admin_edit", change_type="role_mapping")
    new = changes.apply_changes(db, [pc], reviewer_id="chief")
    assert new.version_no == old.version_no + 1 and reg.current_version_id == new.id
    assert pc.status == "approved" and pc.applied_version_id == new.id
    roles = {db.get(RoleCatalog, m.role_id).code: m.level for m in db.scalars(select(LawRoleMap).where(LawRoleMap.law_version_id == new.id))}
    assert roles["impact_assessment_owner"] == "recommended" and roles["explainability_contact"] == "required"
    # the old version keeps its maps, so past letters stay reproducible
    assert db.scalar(select(LawRoleMap).where(LawRoleMap.law_version_id == old.id, LawRoleMap.role_id == db.scalar(select(RoleCatalog.id).where(RoleCatalog.code == "impact_assessment_owner")))) is None
    assert len(db.scalars(select(Requirement).where(Requirement.law_version_id == new.id)).all()) == 8


def test_requirement_change_and_removal(master):
    db = master
    reg = _co(db)
    p1 = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="requirement.CO-05", new_value={"text": "Explain within 30 days", "role": "explainability_contact", "citation": "§6-1-1704(3), C.R.S. (SB 26-189)", "source_quote": "WITHIN THIRTY DAYS AFTER MAKING THE DECISION", "source_url": "https://leg.colorado.gov/bill_files/115943/download"}, summary="Reword CO-05", origin="admin_edit")
    p2 = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="requirement.CO-08", new_value=None, summary="Rules adopted", origin="admin_edit")
    new = changes.apply_changes(db, [p1, p2], reviewer_id="chief")
    codes = {r.code: r for r in db.scalars(select(Requirement).where(Requirement.law_version_id == new.id))}
    assert "CO-08" not in codes and codes["CO-05"].text == "Explain within 30 days"


def test_requirement_without_quote_is_refused(master):
    db = master
    with pytest.raises(Invalid):
        changes.propose(db, actor_id="u1", regulation_id=_co(db).id, field_path="requirement.CO-09", new_value={"text": "New duty", "citation": "x"}, summary="x", origin="admin_edit")


def test_impacts_name_clients_and_roles(master):
    db = master
    org = make_org(db)
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, "US-CO").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, org.id)
    pc = changes.propose(db, actor_id="u1", regulation_id=_co(db).id, field_path="role_map.worker_rep_contact", new_value={"level": "required", "needed_by_stage": "go_live"}, summary="x", origin="admin_edit", change_type="role_mapping")
    imp = db.scalar(select(ChangeImpact).where(ChangeImpact.proposed_change_id == pc.id))
    assert imp.organization_id == org.id and imp.roles_affected == ["worker_rep_contact"]


def test_approval_reruns_applicability(master):
    db = master
    org = make_org(db)
    db.add(ClientGeography(organization_id=org.id, jurisdiction_id=by_code(db, "US-CO").id, basis="office", source="manual"))
    db.flush()
    engine.run(db, org.id)
    reg = _co(db)
    pc = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="law.status", new_value="in_force", summary="Now in force", origin="admin_edit", change_type="effective_date")
    new = changes.apply_changes(db, [pc], reviewer_id="chief")
    row = next(r for r in engine.run(db, org.id) if r.regulation_id == reg.id)
    assert row.law_version_id == new.id


def test_new_law_proposal_creates_law_on_approval(master):
    db = master
    pc = changes.propose(db, actor_id="u1", regulation_id=None, field_path="new_law", change_type="new_law", origin="admin_edit", summary="Add Texas TRAIGA record", new_value={
        "jurisdiction_code": "US-UT", "short_name": "Utah AI Policy Act", "citation": "SB 149 (2024)", "type": "statute", "binding": True,
        "version": {"status": "in_force", "scope_text": "Businesses using generative AI with Utah consumers", "applies_to": ["deployer"]},
        "scope_tests": [{"question_text": "Does the client interact with Utah consumers using generative AI?", "prefill_from": "client_geographies", "in_scope_rule": {"equals": "yes", "codes": ["US-UT"]}}],
    })
    assert pc.regulation_id is None
    v = changes.apply_changes(db, [pc], reviewer_id="chief")
    assert v.version_no == 1 and db.get(ProposedChange, pc.id).regulation_id == v.regulation_id


def test_repeal_proposal_sets_status_on_approval(master):
    db = master
    reg = find_law(db, "US-NYC", "Local Law 144")
    pc = changes.propose(db, actor_id="u1", regulation_id=reg.id, field_path="repeal", new_value={"status": "repealed"}, summary="Repealed", origin="admin_edit", change_type="repeal")
    assert pc.old_value == "in_force"
    v = changes.apply_changes(db, [pc], reviewer_id="chief")
    assert v.status == "repealed"


@pytest.mark.parametrize("url,expected", [
    ("https://cppa.ca.gov/regulations/x.pdf", "high"),          # exact host
    ("https://www.cppa.ca.gov/regulations/x.pdf", "high"),      # www. of an allowlisted host
    ("https://leg.colorado.gov/bills/sb26-189", "high"),        # subdomain of an allowlisted host (colorado.gov)
    ("https://nist.gov/itl/ai", "high"),                        # bare domain of an allowlisted www. host (www.nist.gov)
    ("https://evilcolorado.gov/bills/sb26-189", "low"),         # look-alike suffix
    ("https://colorado.gov.example.com/x", "low"),              # allowlisted name inside another domain
    ("https://www.hklaw.com/x", "low"),                         # secondary source
])
def test_allowlist_matches_domain_and_subdomains_but_not_look_alikes(master, url, expected):
    pc = changes.propose(master, actor_id=None, regulation_id=_co(master).id, field_path="law.cure_period", new_value=f"60 days ({url})", summary="x",
                         origin="claude_refresh", source_url=url, source_quote="sixty days")
    assert pc.confidence == expected


def test_claude_draft_treats_a_www_host_of_an_official_domain_as_official(master):
    from app.regmaster.draft import draft_law

    class Fake:
        def research(self, prompt):
            return '```json {"short_name": "x", "sources": [{"name": "CPPA", "url": "https://www.cppa.ca.gov/regulations/"}, {"name": "Look-alike", "url": "https://evilcppa.ca.gov/x"}]} ```'

    out = draft_law(master, Fake(), "CCPA regs")
    assert [s["kind"] for s in out["draft"]["sources"]] == ["official", "secondary"]
