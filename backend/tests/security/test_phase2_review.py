"""Regression tests for the Phase 2 review findings (C1, I1–I6, M1–M8)."""
import shutil
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Invalid
from app.laws.importer import parse_workbook
from app.laws.models import Regulation
from app.laws.publish import current_regulations, current_version_of, plan_publish, publish
from app.laws.service import add_law, edit_law
from app.questionnaire.rules import EngagementFacts, SystemContext, evaluate_finding, is_applicable
from app.reference.jurisdictions import resolve_jurisdictions, seed_iso
from tests.factories import login_as, make_org, make_user

WORKBOOK = Path(__file__).resolve().parents[2] / "seeds" / "law_matrix.xlsx"
SYS = SystemContext()
F = EngagementFacts()


@pytest.fixture(scope="module")
def preview():
    return parse_workbook(WORKBOOK)


@pytest.fixture
def admin(db):
    seed_iso(db)
    f = make_org(db, type="futran")
    return make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")


def _il_law(db):
    return next(r for r in current_regulations(db) if r.short_name.startswith("AI Video Interview Act"))


# ---- C1: curated changes survive re-import
def test_preview_rename_survives_reimport(db, preview, admin):
    row = next(r for r in preview.rows if r.kind == "regulation" and r.short_name.startswith("AI Video Interview Act"))
    publish(db, preview, admin, edits={row.row_key: "Illinois AI Video Interview Act"})
    v2 = publish(db, preview, admin, edits={})
    assert v2.summary["retired"] == 0 and v2.summary["created"] == 0
    names = [r.short_name for r in current_regulations(db) if "Video Interview" in r.short_name]
    assert names == ["Illinois AI Video Interview Act"]


def test_manual_edit_survives_reimport_of_unchanged_row(db, preview, admin):
    publish(db, preview, admin, edits={})
    law = _il_law(db)
    edited = edit_law(db, admin, law.id, {"short_name": "IL AIVIA", "obligations_text": "Curated obligations."})
    v = publish(db, preview, admin, edits={})
    assert v.summary["retired"] == 0 and v.summary["updated"] == 0
    cur = current_version_of(db, law.id)
    assert cur.id == edited.id and cur.obligations_text == "Curated obligations."


def test_manual_add_and_claude_add_never_retired(db, preview, admin):
    publish(db, preview, admin, edits={})
    added = add_law(db, admin, "US-NYC", {"short_name": "NYC Int. 999", "feature": "employment_hiring"})
    publish(db, preview, admin, edits={})
    assert db.get(Regulation, added.id).retired_in_version_id is None


def test_workbook_change_on_curated_row_is_a_conflict(db, preview, admin, tmp_path):
    publish(db, preview, admin, edits={})
    law = _il_law(db)
    edit_law(db, admin, law.id, {"obligations_text": "Curated obligations."})
    copy = tmp_path / "m.xlsx"
    shutil.copy(WORKBOOK, copy)
    wb = openpyxl.load_workbook(copy)
    ws = wb["State Matrix"]
    for row in ws.iter_rows(min_row=5):
        if row[0].value == "Illinois":
            row[2].value = row[2].value.replace("AI Video Interview Act (2020)", "AI Video Interview Act (2020, amended 2026)")
    wb.save(copy)
    pv2 = parse_workbook(copy)
    plan = plan_publish(db, pv2, edits={})
    assert len(plan["conflicts"]) == 1 and "Video Interview" in plan["conflicts"][0]["current_short_name"]
    v = publish(db, pv2, admin, edits={})
    assert current_version_of(db, law.id).obligations_text == "Curated obligations."
    assert v.summary["conflicts"] == 1
    conflict_key = plan["conflicts"][0]["row_key"]
    publish(db, parse_workbook(copy), admin, edits={}, take_workbook=[conflict_key])
    assert "amended 2026" in current_version_of(db, law.id).full_text


def test_current_version_follows_chain(db, preview, admin):
    publish(db, preview, admin, edits={})
    law = _il_law(db)
    a = edit_law(db, admin, law.id, {"obligations_text": "one"})
    b = edit_law(db, admin, a.id, {"obligations_text": "two"})
    assert current_version_of(db, law.id).id == b.id


# ---- I1: duplicate identities in a workbook are stable
def test_duplicate_names_are_stable_across_reimport(db, preview, admin):
    from copy import deepcopy

    pv = deepcopy(preview)
    rows = [r for r in pv.rows if r.kind == "regulation" and r.jurisdiction_code == "US-IL" and r.feature == "employment_hiring"]
    for r in rows:
        r.short_name = "Same name"
    publish(db, pv, admin, edits={})
    ids = {r.id for r in current_regulations(db)}
    v2 = publish(db, pv, admin, edits={})
    assert v2.summary["updated"] == 0 and {r.id for r in current_regulations(db)} == ids


def test_stale_preview_cannot_publish(client, db, admin):
    db.commit()
    login_as(client, db, admin)
    ids = []
    for _ in range(2):
        with open(WORKBOOK, "rb") as fh:
            ids.append(client.post("/api/v1/admin/laws/import", files={"file": ("m.xlsx", fh, "application/octet-stream")}).json()["preview_id"])
    assert client.post(f"/api/v1/admin/laws/import/{ids[1]}/publish", json={"edits": {}}).status_code == 200
    r = client.post(f"/api/v1/admin/laws/import/{ids[0]}/publish", json={"edits": {}})
    assert r.status_code == 409 and "newer" in r.json()["detail"]


def test_preview_shows_publish_plan(client, db, admin):
    db.commit()
    login_as(client, db, admin)
    with open(WORKBOOK, "rb") as fh:
        pv = client.post("/api/v1/admin/laws/import", files={"file": ("m.xlsx", fh, "application/octet-stream")}).json()
    assert pv["plan"]["created"] > 200 and pv["plan"]["retired"] == 0 and pv["plan"]["conflicts"] == []


# ---- I2 / M4: templates are sandboxed and test-rendered on save
def test_template_sandbox_blocks_python_internals(db, admin):
    from app.reference.templates import edit_template, load_templates, render_string

    load_templates(db)
    with pytest.raises(Exception):
        render_string("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})
    with pytest.raises(Invalid):
        edit_template(db, admin, "roles_note", "{{ ''.__class__.__mro__[1].__subclasses__() }}")


def test_template_subscript_on_missing_value_is_caught_on_save(db, admin):
    from app.reference.templates import edit_template, load_templates, render_string

    load_templates(db)
    assert render_string('{{ client["name"] }}', {}) == ""
    t = edit_template(db, admin, "roles_note", "Hello {{ client['name'] }} {{ engagement.departments | join(', ') }}")
    assert t.version == 2


# ---- I3: refresh commits per jurisdiction and stale runs resolve
def test_refresh_commits_between_research_calls(db, admin):
    from app.laws.models import LawRefreshRun
    from app.laws.refresh import run_refresh

    publish(db, parse_workbook(WORKBOOK), admin, {})
    js = [j.id for j in [resolve_jurisdictions(db, "US", "US-IL")[0], resolve_jurisdictions(db, "US", "US-NY")[0]]]
    commits = []

    class Stub:
        def research(self, prompt):
            commits.append(db.in_transaction())  # no open transaction (and so no SQLite write lock) during the network call
            return "```json\n[]\n```"

    run_refresh(db, admin, js, Stub(), commit=db.commit)
    assert commits == [False, False]
    assert db.get(LawRefreshRun, db.scalars(select(LawRefreshRun.id)).first()).status == "completed"


def test_stale_running_runs_marked_failed(client, db, admin):
    from datetime import timedelta

    from app.core.clock import utcnow
    from app.laws.models import LawRefreshRun

    db.add(LawRefreshRun(jurisdiction_ids=[], requested_by=admin.id, status="running", created_at=utcnow() - timedelta(hours=3)))
    db.commit()
    login_as(client, db, admin)
    runs = client.get("/api/v1/admin/laws/refresh").json()
    assert runs[0]["status"] == "failed" and "interrupted" in runs[0]["error"]


# ---- I4: "we plan to" only counts as No for rules about missing controls
def test_nyip_does_not_trigger_positive_value_rules():
    prohibited = {"when": {"in": ["prohibited"]}, "severity": "critical", "title": "Prohibited"}
    dir_rule = {"when": {"lt": 0.8}, "severity": "high", "title": "DIR"}
    nc = {"when": {"in": ["high"]}, "severity": "high", "title": "NC", "null_compliance": True}
    for rule in (prohibited, dir_rule, nc):
        assert evaluate_finding(rule, None, "not_yet_in_place", {}, SYS, F) is None
    no_rule = {"when": {"in": ["no", "planned"]}, "severity": "high", "title": "No bias testing"}
    assert evaluate_finding(no_rule, None, "not_yet_in_place", {}, SYS, F) is not None


# ---- I5: findings match the template
def test_never_done_dates_trigger_findings():
    rule = {"when": {"older_than_months": 12, "or_never": True}, "severity": "medium", "title": "Old"}
    assert evaluate_finding(rule, "never", "answered", {}, SYS, F, today=date(2026, 10, 13))


def test_question_bank_template_findings(db):
    from app.questionnaire.models import Question
    from app.questionnaire.seed import load_question_bank

    load_question_bank(db)
    q = {c: db.scalar(select(Question).where(Question.code == c)) for c in ("5.3.04", "5.3.07", "6.1.02", "6.1.06", "8.1.09", "5.3.09", "9.2.01")}
    assert q["5.3.04"].finding_rule and "unknown" in q["5.3.04"].finding_rule["when"]["in"]
    assert evaluate_finding(q["5.3.07"].finding_rule, ["access_control"], "answered", {}, SYS, F)
    assert evaluate_finding(q["6.1.02"].finding_rule, "no", "answered", {}, SystemContext(depth="light"), F) is None
    assert evaluate_finding(q["6.1.06"].finding_rule, "none", "answered", {}, SystemContext(depth="full"), F)
    assert q["8.1.09"].finding_rule["when"]["or_never"] and q["5.3.09"].finding_rule["when"]["or_never"]
    # M8: vendor due diligence also applies to in-house systems that call external APIs
    rule = {"all": [q["9.2.01"].section_rule]} if q["9.2.01"].section_rule else None
    assert is_applicable(rule, {"3.2.10": "OpenAI API"}, SystemContext(built_by="in_house"), F)
    assert not is_applicable(rule, {"3.2.10": ""}, SystemContext(built_by="in_house"), F)
    assert is_applicable(rule, {}, SystemContext(built_by="vendor"), F)


# ---- I6: methodology inputs are machine-usable
def test_methodology_knockouts_are_rules_and_consequence_uses_auditor_severity(db):
    from app.reference.catalogs import load_catalogs
    from app.reference.models import RiskMethodology

    load_catalogs(db)
    m = db.scalar(select(RiskMethodology))
    assert m.factor_weights["consequence"]["question"] == "3.3.05s"
    ds = m.factor_weights["data_sensitivity"]
    assert ds["questions"] == ["5.1.02", "5.1.03", "5.1.04"]
    top = ds["levels"][0]
    assert top["score"] == 5 and is_applicable(top["rule"], {"5.1.04": "yes"}, SYS, F) and not is_applicable(top["rule"], {"5.1.03": "yes"}, SYS, F)
    for k in m.knockout_rules:
        is_applicable(k["rule"], {}, SYS, F)  # parses
    ko = {k["code"]: k for k in m.knockout_rules}
    assert is_applicable(ko["no_bias_testing"]["rule"], {"6.2.01": "no", "3.3.07": "yes"}, SYS, F)
    assert not is_applicable(ko["no_bias_testing"]["rule"], {"6.2.01": "no", "3.3.07": "no"}, SYS, F)


# ---- M1 / M2 / M3
def test_upload_size_capped(client, db, admin):
    db.commit()
    login_as(client, db, admin)
    client.app.state.settings = client.app.state.settings.model_copy(update={"max_upload_mb": 0})
    with open(WORKBOOK, "rb") as fh:
        r = client.post("/api/v1/admin/laws/import", files={"file": ("m.xlsx", fh, "application/octet-stream")})
    assert r.status_code == 422 and "MB" in r.json()["detail"]


def test_bad_proposal_fields_skipped(db, admin):
    from app.laws.models import RegulationProposal
    from app.laws.refresh import run_refresh

    publish(db, parse_workbook(WORKBOOK), admin, {})
    il = resolve_jurisdictions(db, "US", "US-IL")[0]
    reply = '```json\n[{"change_type": "add", "fields": {"short_name": ["not", "a", "string"]}, "rationale": "r", "sources": [{"title": "t", "url": "https://x.test"}]}, {"change_type": "add", "fields": {"short_name": "' + "x" * 300 + '"}, "rationale": "r", "sources": [{"title": "t", "url": "https://x.test"}]}]\n```'

    class Stub:
        def research(self, p):
            return reply

    run = run_refresh(db, admin, [il.id], Stub())
    assert db.query(RegulationProposal).filter_by(run_id=run.id).count() == 0
    assert len(run.warnings) == 2


def test_retire_of_superseded_law_rejected(db, admin):
    from app.laws.models import LawRefreshRun, RegulationProposal
    from app.laws.refresh import accept_proposals

    publish(db, parse_workbook(WORKBOOK), admin, {})
    law = _il_law(db)
    run = LawRefreshRun(jurisdiction_ids=[law.jurisdiction_id], status="completed")
    db.add(run)
    db.flush()
    p = RegulationProposal(run_id=run.id, jurisdiction_id=law.jurisdiction_id, regulation_id=law.id, change_type="retire", proposed={}, rationale="r", sources=[{"title": "t", "url": "https://x"}])
    db.add(p)
    db.flush()
    edit_law(db, admin, law.id, {"obligations_text": "changed"})
    with pytest.raises(Invalid):
        accept_proposals(db, admin, [p.id], [])


# ---- M6 / M7
def test_bare_state_codes_resolve(db):
    seed_iso(db)
    assert [j.code for j in resolve_jurisdictions(db, "US", "NY", "Brooklyn")] == ["US-NYC", "US-NY", "US"]
    assert [j.code for j in resolve_jurisdictions(db, "US", "CA", None)] == ["US-CA", "US"]


def test_engagement_string_facts_case_insensitive():
    assert is_applicable({"engagement": "industry", "in": ["banking", "bfsi"]}, {}, SYS, EngagementFacts(industry="BFSI"))
