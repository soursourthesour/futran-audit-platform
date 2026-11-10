"""F8 (11-03 review): the periodic opportunity scan. A Futran Admin setting runs it every N days from the daily jobs; it
opens opportunities through open_from_trigger for laws added or changed, regulatory updates matched to a client and
renewal audits coming up, once per client and reference."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.engagements.models import Engagement
from app.laws.publish import current_regulations
from app.regmaster.models import ClientLawApplicability, LawVersion, ProposedChange
from app.regupdates.models import RegulatoryAlert, RegulatoryUpdate
from app.sales import scan
from app.sales.models import Opportunity, OpportunityScanRun, OpportunityScanSetting
from tests.factories import login_as

NOW = datetime(2026, 11, 10, 10, 0)


def _ll144(db):
    return next(r for r in current_regulations(db) if r.short_name == "NYC Local Law 144")


def _approve_version(db, reg, at, field_path="law.penalty_text", summary="Penalties raised to $1,500 a day"):
    v = LawVersion(regulation_id=reg.id, version_no=9, approved_at=at, approved_by="chief-auditor", change_summary=summary)
    db.add(v)
    db.flush()
    db.add(ProposedChange(change_type="amendment", regulation_id=reg.id, field_path=field_path, summary=summary, status="approved", applied_version_id=v.id, reviewed_at=at))
    reg.current_version_id = v.id
    return v


def _in_scope(db, org, reg, v):
    db.add(ClientLawApplicability(organization_id=org.id, regulation_id=reg.id, law_version_id=v.id, in_scope=True, reason_text="Operates in New York City"))


def _published_update(db, org, at, ref="RU-001", systems=()):
    u = RegulatoryUpdate(reference=ref, change_type="enforcement_action", law_name="NYC Local Law 144", title="Comptroller audit finds weak enforcement",
                         summary="Audit found weak enforcement.", status="published", published_at=at)
    db.add(u)
    db.flush()
    db.add(RegulatoryAlert(organization_id=org.id, update_id=u.id, affected_system_ids=list(systems), match_reason="In scope of NYC Local Law 144"))
    return u


def _completed(db, org, completed_at, name="2025 audit"):
    e = Engagement(organization_id=org.id, client_id=org.id, name=name, status="completed", stage=9, completed_at=completed_at, created_at=completed_at - timedelta(days=60))
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def world(db, lit):
    """ABC Corp: in scope of a law changed last week and matched to an update published last week. Northwind: its
    audit completed eleven months ago, so the renewal is due in about a month."""
    reg = _ll144(db)
    v = _approve_version(db, reg, NOW - timedelta(days=3))
    _in_scope(db, lit["abc"], reg, v)
    lit["update"] = _published_update(db, lit["abc"], NOW - timedelta(days=2), systems=[lit["screening"].id])
    lit["prior"] = _completed(db, lit["nw"], NOW - timedelta(days=335))
    lit["reg"], lit["version"] = reg, v
    db.commit()
    return lit


def _mine(db, *triggers):
    q = select(Opportunity)
    if triggers:
        q = q.where(Opportunity.trigger.in_(triggers))
    return list(db.scalars(q.order_by(Opportunity.trigger)))


# ------------------------------------------------------------------ setting and schedule

def test_off_by_default_and_the_daily_job_does_nothing(db, world, settings):
    assert scan.interval(db) is None
    assert scan.run_scheduled(db, settings, NOW) == 0
    assert db.scalar(select(OpportunityScanRun.id)) is None
    assert _mine(db) == []


def test_interval_choices(db, world):
    for bad in (0, 366, -7):
        with pytest.raises(Exception):
            scan.set_interval(db, world["admin"], bad)
    scan.set_interval(db, world["admin"], 12)  # a custom number
    assert scan.interval(db) == 12
    scan.set_interval(db, world["admin"], None)
    assert scan.interval(db) is None


def test_runs_when_due_and_not_before(db, world, settings):
    scan.set_interval(db, world["admin"], 7)
    db.commit()
    assert scan.run_scheduled(db, settings, NOW) == 1  # never run: due at once
    assert scan.run_scheduled(db, settings, NOW + timedelta(hours=2)) == 0  # same day
    assert scan.run_scheduled(db, settings, NOW + timedelta(days=6)) == 0  # not yet due
    assert scan.run_scheduled(db, settings, NOW + timedelta(days=7, minutes=-5)) == 1  # due by date, whatever the minute
    assert len(db.scalars(select(OpportunityScanRun)).all()) == 2


def test_a_run_claimed_by_another_process_is_not_run_again(db, world, settings):
    scan.set_interval(db, world["admin"], 7)
    db.add(OpportunityScanRun(run_key=f"scheduled:{NOW.date().isoformat()}", trigger="scheduled", started_at=NOW, since=NOW, status="running"))
    db.commit()
    assert scan.run_scheduled(db, settings, NOW) == 0
    assert _mine(db) == []


def test_the_daily_job_list_has_the_scan(db, world, settings):
    from app.notifications.jobs import JOBS, run_daily

    assert "opportunity_scan" in JOBS
    scan.set_interval(db, world["admin"], 30, now=NOW - timedelta(days=30))
    db.commit()
    out = run_daily(db, settings, NOW)
    assert out["opportunity_scan"] == 1
    assert len(_mine(db)) == 3


# ------------------------------------------------------------------ what it finds

def test_each_source_opens_one_opportunity_per_client_and_reference(db, world, settings):
    run = scan.run_now(db, world["admin"], now=NOW)
    assert run.status == "completed"
    assert run.counts == {"laws": 1, "regulatory_updates": 1, "renewals": 1, "already_open": 0, "held_back": 0, "failed_clients": 0}
    law, update, renewal = _mine(db, "law_change"), _mine(db, "regulatory_update"), _mine(db, "renewal_audit")
    assert [(o.organization_id, o.trigger_ref) for o in law] == [(world["abc"].id, f"lawver:{world['version'].id}")]
    assert "NYC Local Law 144" in law[0].why_now and "Penalties raised" in law[0].why_now
    assert [(o.organization_id, o.trigger_ref) for o in update] == [(world["abc"].id, world["update"].id)]
    assert "RU-001" in update[0].why_now and update[0].system_ids == [world["screening"].id]
    assert db.scalar(select(RegulatoryAlert.opportunity_id).where(RegulatoryAlert.update_id == world["update"].id)) == update[0].id
    due = (world["prior"].completed_at + timedelta(days=365)).date()
    assert [(o.organization_id, o.trigger_ref, o.service_kind) for o in renewal] == [(world["nw"].id, f"renewal:{world['prior'].id}:{due.isoformat()}", "audit")]
    assert "annual review" in renewal[0].why_now.lower()
    assert sorted(run.found) == sorted(o.id for o in law + update + renewal)

    # a second scan over the same window finds the same things and opens nothing new
    again = scan.run_scan(db, trigger="manual", actor=world["admin"], now=NOW + timedelta(hours=1), since=NOW - timedelta(days=30))
    assert again.found == [] and again.counts["already_open"] == 3
    assert len(_mine(db)) == 3


def test_only_changes_since_the_last_scan_count(db, world, settings):
    scan.run_now(db, world["admin"], now=NOW)
    reg2 = next(r for r in current_regulations(db) if r.id != world["reg"].id)
    v2 = _approve_version(db, reg2, NOW + timedelta(days=1), summary="New duty to notify")
    _in_scope(db, world["abc"], reg2, v2)
    db.commit()
    later = scan.run_now(db, world["admin"], now=NOW + timedelta(days=2))
    assert later.since == NOW
    assert later.counts["laws"] == 1 and later.counts["regulatory_updates"] == 0
    assert later.counts["renewals"] == 0 and later.counts["already_open"] == 1  # renewals are looked at every scan; Northwind's is open already
    assert sorted(o.trigger_ref for o in _mine(db, "law_change")) == sorted([f"lawver:{world['version'].id}", f"lawver:{v2.id}"])


def test_first_run_looks_back_30_days_even_just_after_switching_on(db, world, settings):
    """11-10 review O4: a long custom interval no longer floods the list on the first scan, and switching the scan on
    then pressing "Run now" still finds the last month's changes (a user testing the feature sees it work)."""
    scan.set_interval(db, world["admin"], 7, now=NOW - timedelta(minutes=1))
    assert scan.run_now(db, world["admin"], now=NOW).since == NOW - timedelta(days=30)


def test_first_run_after_a_long_time_switched_on_looks_back_30_days(db, world, settings):
    scan.set_interval(db, world["admin"], 365, now=NOW - timedelta(days=200))
    assert scan.run_now(db, world["admin"], now=NOW).since == NOW - timedelta(days=30)


def test_changing_the_interval_does_not_change_the_first_lookback(db, world, settings):
    scan.set_interval(db, world["admin"], 7, now=NOW - timedelta(days=3))
    scan.set_interval(db, world["admin"], 15, now=NOW - timedelta(days=1))
    assert scan.run_now(db, world["admin"], now=NOW).since == NOW - timedelta(days=30)


def test_run_now_while_off_looks_back_30_days_at_most(db, world, settings):
    assert scan.run_now(db, world["admin"], now=NOW).since == NOW - timedelta(days=30)
    assert scan.run_now(db, world["admin"], now=NOW + timedelta(days=90)).since == NOW + timedelta(days=60)
    assert scan.run_now(db, world["admin"], now=NOW + timedelta(days=95)).since == NOW + timedelta(days=90)  # since the last scan


def test_the_first_scan_after_switching_on_again_looks_back_30_days_at_most(db, world, settings):
    scan.run_now(db, world["admin"], now=NOW - timedelta(days=100))
    scan.set_interval(db, world["admin"], 30, now=NOW - timedelta(days=2))
    assert scan.run_now(db, world["admin"], now=NOW).since == NOW - timedelta(days=30)
    assert scan.run_now(db, world["admin"], now=NOW + timedelta(days=1)).since == NOW  # then since the last scan

def test_a_recent_scan_while_off_is_where_the_next_one_starts(db, world, settings):
    scan.run_now(db, world["admin"], now=NOW - timedelta(days=5))
    scan.set_interval(db, world["admin"], 30, now=NOW - timedelta(days=2))
    assert scan.run_now(db, world["admin"], now=NOW).since == NOW - timedelta(days=5)


def test_first_run_with_a_long_interval_does_not_backfill_a_year(db, world):
    for i in range(12):
        _published_update(db, world["nw"], NOW - timedelta(days=25 * i + 1), ref=f"RU-{100 + i}")
    db.commit()
    scan.set_interval(db, world["admin"], 365, now=NOW - timedelta(days=365))
    run = scan.run_now(db, world["admin"], now=NOW)
    assert run.counts["regulatory_updates"] == 1 + 2  # ABC's from the world, and Northwind's from 1 and 26 days ago


def test_renewals_are_opened_no_more_than_90_days_ahead(db, world):
    world["prior"].completed_at = NOW - timedelta(days=365 - 91)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert _mine(db, "renewal_audit") == []
    world["prior"].completed_at = NOW - timedelta(days=365 - 90)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW + timedelta(hours=1))
    assert len(_mine(db, "renewal_audit")) == 1


def test_laws_out_of_scope_or_changed_only_in_wording_are_not_opportunities(db, world):
    reg2 = next(r for r in current_regulations(db) if r.id != world["reg"].id)
    v2 = _approve_version(db, reg2, NOW - timedelta(days=1))
    db.add(ClientLawApplicability(organization_id=world["nw"].id, regulation_id=reg2.id, law_version_id=v2.id, in_scope=False))
    reg3 = [r for r in current_regulations(db) if r.id not in (world["reg"].id, reg2.id)][0]
    v3 = _approve_version(db, reg3, NOW - timedelta(days=1), field_path="law.verify_flag", summary="Verified against the official text")
    _in_scope(db, world["nw"], reg3, v3)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert [o.organization_id for o in _mine(db, "law_change", "new_law")] == [world["abc"].id]


def test_versions_the_platform_wrote_itself_are_not_news(db, world):
    """Seeding and matrix re-imports stamp approved_at without a reviewer: only a person's approval counts."""
    reg2 = next(r for r in current_regulations(db) if r.id != world["reg"].id)
    v2 = LawVersion(regulation_id=reg2.id, version_no=1, approved_at=NOW - timedelta(hours=1), change_summary="Law matrix re-import: content carried forward")
    db.add(v2)
    db.flush()
    reg2.current_version_id = v2.id
    _in_scope(db, world["nw"], reg2, v2)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert [o.organization_id for o in _mine(db, "law_change", "new_law")] == [world["abc"].id]


def test_a_new_law_is_labelled_as_one(db, world):
    reg2 = next(r for r in current_regulations(db) if r.id != world["reg"].id)
    v2 = _approve_version(db, reg2, NOW - timedelta(days=1), field_path="new_law", summary=f"Add {reg2.short_name}")
    v2.version_no = 1
    _in_scope(db, world["nw"], reg2, v2)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    o = _mine(db, "new_law")
    assert [x.organization_id for x in o] == [world["nw"].id]
    assert o[0].why_now.startswith("New law in the library")


def test_a_law_opportunity_already_opened_at_approval_is_not_repeated(db, world):
    pc = db.scalar(select(ProposedChange).where(ProposedChange.applied_version_id == world["version"].id))
    db.add(Opportunity(organization_id=world["abc"].id, trigger="law_change", trigger_ref=pc.id, service="Readiness review for the change", stage="new"))
    db.commit()
    run = scan.run_now(db, world["admin"], now=NOW)
    assert run.counts["laws"] == 0 and run.counts["already_open"] == 1
    assert len(_mine(db, "law_change")) == 1


def test_withdrawn_and_watch_updates_are_skipped(db, world):
    world["update"].status = "withdrawn"
    w = _published_update(db, world["nw"], NOW - timedelta(days=1), ref="RU-002")
    w.watch = True
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert _mine(db, "regulatory_update") == []


def test_renewal_skipped_once_an_annual_review_or_a_newer_engagement_has_started(db, world):
    db.add(Engagement(organization_id=world["nw"].id, client_id=world["nw"].id, name="Northwind annual review", type="annual_review", status="draft",
                      prior_engagement_id=world["prior"].id))
    old = _completed(db, world["abc"], NOW - timedelta(days=700), name="2024 audit")
    db.add(Engagement(organization_id=world["abc"].id, client_id=world["abc"].id, name="2025 audit", status="in_progress", stage=4, created_at=old.completed_at + timedelta(days=200)))
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert _mine(db, "renewal_audit") == []


def test_renewal_far_off_is_not_due_yet(db, world):
    world["prior"].completed_at = NOW - timedelta(days=200)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert _mine(db, "renewal_audit") == []


# ------------------------------------------------------------------ independence, approval and failures

def test_current_audit_clients_need_chief_auditor_approval(db, world):
    db.add(Engagement(organization_id=world["abc"].id, client_id=world["abc"].id, name="ABC 2026 audit", status="in_progress", stage=5))
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert {o.trigger: o.needs_ca_approval for o in _mine(db) if o.organization_id == world["abc"].id} == {"law_change": True, "regulatory_update": True}
    assert all(not o.needs_ca_approval for o in _mine(db) if o.organization_id == world["nw"].id)


def test_independence_rule_holds_back_what_it_refuses(db, world, monkeypatch):
    from app.sales import service as sales

    real = sales.open_from_trigger

    def guarded(db_, org_id, trigger, ref, **kw):
        if trigger == "regulatory_update":
            raise sales.IndependenceError()
        return real(db_, org_id, trigger, ref, **kw)

    monkeypatch.setattr(sales, "open_from_trigger", guarded)
    run = scan.run_now(db, world["admin"], now=NOW)
    assert run.counts["held_back"] == 1 and run.counts["regulatory_updates"] == 0 and run.counts["laws"] == 1
    assert _mine(db, "regulatory_update") == []


def test_a_client_that_fails_does_not_stop_the_others(db, world, monkeypatch):
    from app.sales import service as sales

    real = sales.open_from_trigger

    def broken_for_abc(db_, org_id, trigger, ref, **kw):
        if org_id == world["abc"].id:
            real(db_, org_id, trigger, ref, **kw)  # half done, then it fails: nothing of ABC's is kept
            raise RuntimeError("boom")
        return real(db_, org_id, trigger, ref, **kw)

    monkeypatch.setattr(sales, "open_from_trigger", broken_for_abc)
    run = scan.run_now(db, world["admin"], now=NOW)
    assert run.status == "completed"
    assert run.counts["failed_clients"] == 1 and run.counts["renewals"] == 1
    assert run.errors == [{"client": "ABC Corp", "error": "RuntimeError"}]
    assert [o.organization_id for o in _mine(db)] == [world["nw"].id]


def test_every_run_is_audit_logged_with_counts(db, world):
    run = scan.run_now(db, world["admin"], now=NOW)
    db.commit()
    row = db.scalar(select(AuditLog).where(AuditLog.action == "opportunity_scan.run"))
    assert row.object_id == run.id and row.after["counts"]["laws"] == 1 and row.actor_id == world["admin"].id
    assert "3 new opportunities" in row.summary


# ------------------------------------------------------------------ API

def test_admin_sets_the_interval_and_runs_now(client, db, world):
    login_as(client, db, world["admin"])
    r = client.get("/api/v1/admin/opportunity-scan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["every_days"] is None and body["last_run"] is None and body["next_run_on"] is None and body["can_edit"] is True
    assert body["choices"] == [7, 15, 30]
    assert client.put("/api/v1/admin/opportunity-scan", json={"every_days": 400}).status_code == 422
    r = client.put("/api/v1/admin/opportunity-scan", json={"every_days": 15})
    assert r.status_code == 200 and r.json()["every_days"] == 15
    assert db.scalar(select(AuditLog).where(AuditLog.action == "opportunity_scan.settings"))
    db.expire_all()
    s = db.scalar(select(OpportunityScanSetting))
    assert s.enabled_at is not None
    s.enabled_at = NOW - timedelta(days=30)  # switched on a month ago, so the first scan sees last week's changes
    db.commit()
    r = client.post("/api/v1/admin/opportunity-scan/run")
    assert r.status_code == 200, r.text
    last = r.json()["last_run"]
    assert last["status"] == "completed" and last["counts"]["laws"] == 1 and last["by"] == "Ada Admin"
    assert {f["trigger_label"] for f in last["found"]} == {"Law change", "Regulatory update", "Renewal audit"}
    assert r.json()["next_run_on"]
    assert client.put("/api/v1/admin/opportunity-scan", json={"every_days": None}).json()["next_run_on"] is None


def test_only_the_futran_admin_changes_it(client, db, world):
    login_as(client, db, world["chief"])
    r = client.get("/api/v1/admin/opportunity-scan")
    assert r.status_code == 200 and r.json()["can_edit"] is False
    assert client.put("/api/v1/admin/opportunity-scan", json={"every_days": 7}).status_code == 403
    assert client.post("/api/v1/admin/opportunity-scan/run").status_code == 403
    login_as(client, db, world["sales"])
    assert client.get("/api/v1/admin/opportunity-scan").status_code == 403


def test_opportunities_screen_lists_the_renewal_trigger(client, db, world):
    scan.run_now(db, world["admin"], now=NOW)
    db.commit()
    login_as(client, db, world["sales"])
    body = client.get("/api/v1/opportunities").json()
    assert {"value": "renewal_audit", "label": "Renewal audit"} in body["triggers"]
    assert "Renewal audit" in {i["trigger_label"] for i in body["items"]}


# ------------------------------------------------------------------ review of workstream O (11-10)

def _ver(db, reg, at, no, field_path, summary):
    v = LawVersion(regulation_id=reg.id, version_no=no, approved_at=at, approved_by="chief-auditor", change_summary=summary)
    db.add(v)
    db.flush()
    db.add(ProposedChange(change_type="new_law" if field_path == "new_law" else "amendment", regulation_id=reg.id, field_path=field_path, summary=summary,
                          status="approved", applied_version_id=v.id, reviewed_at=at))
    reg.current_version_id = v.id
    return v


def _other_law(db, world):
    return next(r for r in current_regulations(db) if r.id != world["reg"].id)


def test_o1_a_new_law_corrected_in_wording_in_the_same_window_is_still_a_new_law(db, world):
    reg = _other_law(db, world)
    v1 = _ver(db, reg, NOW - timedelta(days=10), 1, "new_law", f"Add {reg.short_name}")
    _in_scope(db, world["nw"], reg, v1)
    v2 = _ver(db, reg, NOW - timedelta(days=5), 2, "law.citation", "Citation corrected")
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    o = [x for x in _mine(db, "new_law", "law_change") if x.organization_id == world["nw"].id]
    assert [(x.trigger, x.trigger_ref) for x in o] == [("new_law", f"lawver:{v2.id}")]
    assert o[0].why_now.startswith("New law in the library")
    # the change id of each version counts as the same opportunity (one opened at approval is not repeated)
    pcs = db.scalars(select(ProposedChange.id).where(ProposedChange.applied_version_id.in_((v1.id, v2.id)))).all()
    db.delete(o[0])
    db.add(Opportunity(organization_id=world["nw"].id, trigger="new_law", trigger_ref=sorted(pcs)[0], service="Readiness review for the change", stage="new"))
    db.commit()
    again = scan.run_scan(db, trigger="manual", actor=world["admin"], now=NOW + timedelta(hours=1), since=NOW - timedelta(days=30))
    assert again.counts["laws"] == 0


def test_o1_a_material_change_then_a_wording_change_in_the_same_window_is_a_change(db, world):
    reg = _other_law(db, world)
    v1 = _ver(db, reg, NOW - timedelta(days=10), 9, "law.penalty_text", "Penalty raised")
    _in_scope(db, world["nw"], reg, v1)
    _ver(db, reg, NOW - timedelta(days=5), 10, "law.verify_flag", "Verified")
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    o = [x for x in _mine(db, "law_change") if x.organization_id == world["nw"].id]
    assert len(o) == 1 and "Penalty raised" in o[0].why_now and "Verified" not in o[0].why_now


def test_o1_wording_changes_only_are_still_not_opportunities(db, world):
    reg = _other_law(db, world)
    v1 = _ver(db, reg, NOW - timedelta(days=10), 9, "law.citation", "Citation corrected")
    _in_scope(db, world["nw"], reg, v1)
    _ver(db, reg, NOW - timedelta(days=5), 10, "law.verify_flag", "Verified")
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert [x for x in _mine(db, "law_change", "new_law") if x.organization_id == world["nw"].id] == []


def _update_proposing(db, org, reg, pc, at, ref="RU-050"):
    u = RegulatoryUpdate(reference=ref, change_type="enforcement_action", law_name=reg.short_name, title="Penalty raised", summary="s", status="published",
                         published_at=at, regulation_id=reg.id, proposed_change_id=pc.id)
    db.add(u)
    db.flush()
    db.add(RegulatoryAlert(organization_id=org.id, update_id=u.id, affected_system_ids=[], match_reason="m"))
    return u


def _nw_opps(db, world):
    return [(o.trigger, o.trigger_ref) for o in _mine(db) if o.organization_id == world["nw"].id and o.trigger != "renewal_audit"]


def test_o2_an_update_and_the_law_change_it_proposed_open_one_opportunity(db, world):
    reg = _other_law(db, world)
    v = _ver(db, reg, NOW - timedelta(days=2), 9, "law.penalty_text", "Penalty raised")
    pc = db.scalar(select(ProposedChange).where(ProposedChange.applied_version_id == v.id))
    _in_scope(db, world["nw"], reg, v)
    _update_proposing(db, world["nw"], reg, pc, NOW - timedelta(days=3))
    db.commit()
    run = scan.run_now(db, world["admin"], now=NOW)
    assert _nw_opps(db, world) == [("law_change", f"lawver:{v.id}")]
    assert run.counts["already_open"] == 1


def test_o2_an_update_opened_first_stops_the_law_change_it_proposed(db, world):
    reg = _other_law(db, world)
    pc = ProposedChange(change_type="amendment", regulation_id=reg.id, field_path="law.penalty_text", summary="Penalty raised", status="pending")
    db.add(pc)
    db.flush()
    u = _update_proposing(db, world["nw"], reg, pc, NOW - timedelta(days=3))
    db.commit()
    scan.run_now(db, world["admin"], now=NOW - timedelta(days=1))
    assert _nw_opps(db, world) == [("regulatory_update", u.id)]
    v = LawVersion(regulation_id=reg.id, version_no=9, approved_at=NOW - timedelta(hours=12), approved_by="chief-auditor", change_summary="Penalty raised")
    db.add(v)
    db.flush()
    pc.status, pc.applied_version_id, reg.current_version_id = "approved", v.id, v.id
    _in_scope(db, world["nw"], reg, v)
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert _nw_opps(db, world) == [("regulatory_update", u.id)]


def test_o2_a_law_change_opened_at_approval_stops_the_update_that_proposed_it(db, world):
    reg = _other_law(db, world)
    v = _ver(db, reg, NOW - timedelta(days=40), 9, "law.penalty_text", "Penalty raised")  # before the window: the update alone is in it
    pc = db.scalar(select(ProposedChange).where(ProposedChange.applied_version_id == v.id))
    db.add(Opportunity(organization_id=world["nw"].id, trigger="law_change", trigger_ref=pc.id, service="Readiness review for the change", stage="new"))
    _update_proposing(db, world["nw"], reg, pc, NOW - timedelta(days=3))
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert _nw_opps(db, world) == [("law_change", pc.id)]


def _new_law_due_soon(db, world, at=NOW - timedelta(days=2)):
    reg = _other_law(db, world)
    v = _ver(db, reg, at, 1, "new_law", f"Add {reg.short_name}")
    v.effective_on, v.compliance_on = (NOW + timedelta(days=40)).date(), None
    _in_scope(db, world["nw"], reg, v)
    db.commit()
    return reg, v


def test_o3_effective_date_first_then_the_scan_opens_one_readiness_review(db, world):
    from app.sales import service as sales

    _new_law_due_soon(db, world)
    assert [o.organization_id for o in sales.open_effective_date_opportunities(db, NOW.date())] == [world["nw"].id]
    scan.run_now(db, world["admin"], now=NOW)
    assert [t for t, _ in _nw_opps(db, world)] == ["effective_date"]


def test_o3_the_scan_first_then_the_effective_date_job_opens_nothing_more(db, world):
    from app.sales import service as sales

    _new_law_due_soon(db, world)
    scan.run_now(db, world["admin"], now=NOW)
    assert sales.open_effective_date_opportunities(db, NOW.date()) == []
    assert [t for t, _ in _nw_opps(db, world)] == ["new_law"]


def test_o3_an_effective_date_review_opened_before_a_later_material_change_does_not_hide_it(db, world):
    reg, v = _new_law_due_soon(db, world, at=NOW - timedelta(days=60))
    db.add(Opportunity(organization_id=world["nw"].id, trigger="effective_date", trigger_ref=f"date:{reg.id}:{v.effective_on.isoformat()}", service="x",
                       stage="new", created_at=NOW - timedelta(days=50)))
    v2 = _ver(db, reg, NOW - timedelta(days=2), 2, "law.penalty_text", "Penalty raised")
    v2.effective_on = v.effective_on
    db.commit()
    scan.run_now(db, world["admin"], now=NOW)
    assert sorted(t for t, _ in _nw_opps(db, world)) == ["effective_date", "law_change"]


def test_o7_next_run_is_today_until_todays_daily_run_has_happened(db, world, settings):
    """The daily run is at 10:00 UTC or the first time the app is open after that, so the next run is today until it has happened."""
    from app.notifications import jobs

    scan.set_interval(db, world["admin"], 7, now=NOW - timedelta(days=1))
    db.commit()
    assert scan.next_run_on(db, NOW.replace(hour=8)) == NOW.date()
    assert scan.next_run_on(db, NOW.replace(hour=15)) == NOW.date()  # 10:00 has passed but the laptop was off: it runs when the app is open
    jobs.run_daily_once(db, settings, NOW.replace(hour=15))
    assert scan.next_run_on(db, NOW.replace(hour=16)) == NOW.date() + timedelta(days=7)
    scan.set_interval(db, world["admin"], 1)
    assert scan.next_run_on(db, NOW.replace(hour=16)) == NOW.date() + timedelta(days=1)
