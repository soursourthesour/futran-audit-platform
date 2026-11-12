"""G-10 evidence vault and retention (spec B10): retention tiers 3 / 7 / 10 years (default 7) per client, legal holds that
block every deletion path until released, the 90-day countdown with notice, and storage metering for G-01."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.audit_log.models import AuditLog
from app.biascalc.models import BiasTestRun
from app.biascalc.retention import purge_expired_raw_data
from app.engagements.models import Engagement
from app.files.models import FileObject
from app.files.storage import get_storage
from app.notifications.models import Notification
from app.systems.models import AISystem
from app.vault import service as vault
from app.vault.models import LegalHold
from tests.factories import login_as, make_org, make_user

COMPLETED = datetime(2019, 3, 1, 12)  # 7 years later: 1 March 2026


@pytest.fixture
def vw(db, client, settings):
    f = make_org(db, type="futran")
    w = SimpleNamespace(db=db, client=client, settings=settings)
    w.chief = make_user(db, f, roles=["chief_auditor"], name="Cara Chief", email="cara@futran.test")
    w.fadmin = make_user(db, f, roles=["admin"], name="Ada Admin", email="ada@futran.test")
    w.auditor = make_user(db, f, roles=["auditor"], name="Alex Auditor", email="alex@futran.test")
    w.sales = make_user(db, f, roles=["sales_manager"], name="Sam Sales", email="sam@futran.test")
    w.org = make_org(db, name="Metro Retail Inc.", status="active")
    w.caico = make_user(db, w.org, roles=["caico"], name="Maria Lopez", email="maria@metro.example")
    w.e_old = Engagement(organization_id=w.org.id, client_id=w.org.id, name="LL144 audit 2019", type="ll144_bias_audit", status="completed", stage=9,
                         audit_ref="FSL-AI-AUD-2019-001", completed_at=COMPLETED)
    w.e_new = Engagement(organization_id=w.org.id, client_id=w.org.id, name="Initial assessment 2026", status="in_progress", stage=5, audit_ref="FSL-AI-AUD-2026-002")
    db.add_all([w.e_old, w.e_new])
    db.flush()
    w.sys = AISystem(organization_id=w.org.id, engagement_id=w.e_old.id, name="AEDT 1", reference_id="SYS-001")
    db.add(w.sys)
    db.flush()
    store = get_storage(settings)

    def file(e, name, linked_type="evidence", linked_id=None, size=1024, created=COMPLETED):
        key = store.put(w.org.id, b"x" * 16, name)
        fo = FileObject(organization_id=w.org.id, engagement_id=e.id, storage_key=key, filename=name, content_type="text/plain", size=size, sha256="0" * 64,
                        linked_type=linked_type, linked_id=linked_id, created_at=created)
        db.add(fo)
        db.flush()
        return fo

    w.f_sys = file(w.e_old, "applicant-extract-notes.txt", linked_id=w.sys.id, size=3 * 1024 ** 3)
    w.f_vendor = file(w.e_old, "vendor-terms-v3.txt")
    w.f_gov = file(w.e_old, "hr-policy.txt", linked_type="governance_document")
    w.f_report = file(w.e_old, "final-report.pdf", linked_type="package_document")  # reports and packages are kept
    w.f_live = file(w.e_new, "interview-notes.txt")  # an open engagement: nothing is due
    w.f_bias = file(w.e_old, "applicants.csv", linked_type="bias_dataset", linked_id=w.sys.id)
    w.run = BiasTestRun(organization_id=w.org.id, engagement_id=w.e_old.id, ai_system_id=w.sys.id, dataset_file_id=w.f_bias.id, dataset_filename="applicants.csv",
                        method="selection_rate", library_version="test")
    db.add(w.run)
    db.commit()
    w.as_ = lambda u: login_as(client, db, u)
    return w


def _alive(w, f):
    w.db.refresh(f)
    return f.deleted_at is None


def test_default_tier_is_seven_years_and_tiers_are_3_7_10(vw):
    assert vault.retention_years(vw.db, vw.settings, vw.org.id) == 7
    vw.as_(vw.chief)
    v = vw.client.get(f"/api/v1/staff/clients/{vw.org.id}/vault").json()
    assert v["retention"]["years"] == 7 and v["retention"]["is_default"]
    assert vw.client.put(f"/api/v1/staff/clients/{vw.org.id}/vault/retention", json={"years": 5, "reason": "x"}).status_code == 422
    r = vw.client.put(f"/api/v1/staff/clients/{vw.org.id}/vault/retention", json={"years": 10, "reason": "M-06c uplift ordered"})
    assert r.status_code == 200 and r.json()["retention"]["years"] == 10 and r.json()["retention"]["set_by"] == "Cara Chief"
    assert vault.retention_years(vw.db, vw.settings, vw.org.id) == 10
    assert vw.db.scalar(select(AuditLog).where(AuditLog.action == "vault.retention_tier", AuditLog.organization_id == vw.org.id)) is not None


def test_auditors_and_sales_never_see_the_vault(vw):
    for u in (vw.auditor, vw.sales, vw.caico):
        vw.as_(u)
        assert vw.client.get(f"/api/v1/staff/clients/{vw.org.id}/vault").status_code in (403, 404)


def test_only_the_chief_auditor_places_and_releases_holds(vw):
    body = {"name": "Client counsel request", "matter_ref": "Doe v. Metro", "reason": "Litigation hold from client counsel",
            "scope": {"engagement_ids": [vw.e_old.id], "system_ids": [vw.sys.id], "from": "2019-01-01"}}
    vw.as_(vw.fadmin)
    assert vw.client.post(f"/api/v1/staff/clients/{vw.org.id}/vault/holds", json=body).status_code == 403
    vw.as_(vw.chief)
    r = vw.client.post(f"/api/v1/staff/clients/{vw.org.id}/vault/holds", json=body)
    assert r.status_code == 200, r.text
    hold = r.json()["holds"][0]
    assert hold["ref"] == "LH-001" and hold["active"] and hold["set_by"] == "Cara Chief" and hold["scope_label"]
    assert vw.client.post(f"/api/v1/staff/clients/{vw.org.id}/vault/holds/{hold['id']}/release", json={"reason": ""}).status_code == 422
    r = vw.client.post(f"/api/v1/staff/clients/{vw.org.id}/vault/holds/{hold['id']}/release", json={"reason": "Matter settled"})
    assert r.status_code == 200 and not r.json()["holds"][0]["active"] and r.json()["holds"][0]["released_by"] == "Cara Chief"
    acts = set(vw.db.scalars(select(AuditLog.action).where(AuditLog.organization_id == vw.org.id)))
    assert {"vault.hold_placed", "vault.hold_released"} <= acts


def test_countdown_lists_the_next_90_days_with_hold_status(vw):
    on = date(2026, 1, 15)  # due 1 March 2026: inside 90 days
    vault.place_hold(vw.db, vw.chief, vw.org, name="Counsel", matter_ref="M-1", reason="r", scope={"system_ids": [vw.sys.id]})
    items = vault.countdown(vw.db, vw.settings, vw.org, on)
    names = {i["filename"]: i for i in items}
    assert set(names) == {"applicant-extract-notes.txt", "vendor-terms-v3.txt", "hr-policy.txt", "applicants.csv"}
    assert names["applicant-extract-notes.txt"]["hold"] == "LH-001" and names["vendor-terms-v3.txt"]["hold"] is None
    assert names["applicants.csv"]["kind"] == "Raw data" and names["applicants.csv"]["hold"] == "LH-001"
    assert all(i["engagement"] == "LL144 audit 2019" for i in items)
    assert vault.countdown(vw.db, vw.settings, vw.org, date(2025, 11, 1)) == []  # more than 90 days out


def test_nothing_is_deleted_without_90_days_notice(vw):
    """Items past their date when the vault first sees them get the full 90 days, with a notice to the Chief Auditor and CAICO."""
    vault.run_daily(vw.db, vw.settings, datetime(2026, 6, 1, 10))
    vw.db.commit()
    assert _alive(vw, vw.f_vendor)
    n = vw.db.scalar(select(Notification).where(Notification.user_id == vw.chief.id, Notification.kind == "retention_notice"))
    assert n is not None and "4 items" in n.title
    assert vw.db.scalar(select(Notification).where(Notification.user_id == vw.caico.id, Notification.kind == "retention_notice")) is not None
    vault.run_daily(vw.db, vw.settings, datetime(2026, 8, 29, 10))  # 89 days
    vw.db.commit()
    assert _alive(vw, vw.f_vendor)
    assert len(list(vw.db.scalars(select(Notification).where(Notification.user_id == vw.chief.id, Notification.kind == "retention_notice")))) == 1
    vault.run_daily(vw.db, vw.settings, datetime(2026, 8, 30, 10))  # 90 days
    vw.db.commit()
    assert not _alive(vw, vw.f_vendor) and not _alive(vw, vw.f_gov) and not _alive(vw, vw.f_sys)
    assert _alive(vw, vw.f_report) and _alive(vw, vw.f_live)  # not evidence / engagement still open
    assert not (get_storage(vw.settings).root / vw.f_vendor.storage_key).exists()
    assert vw.db.scalar(select(AuditLog).where(AuditLog.action == "vault.retention_deleted", AuditLog.object_id == vw.f_vendor.id)) is not None


def test_a_legal_hold_blocks_the_vault_deletion_until_released(vw):
    hold = vault.place_hold(vw.db, vw.chief, vw.org, name="Counsel", matter_ref="M-1", reason="r", scope={"engagement_ids": [vw.e_old.id], "system_ids": [vw.sys.id]})
    vw.db.commit()
    vault.run_daily(vw.db, vw.settings, datetime(2026, 6, 1, 10))
    vault.run_daily(vw.db, vw.settings, datetime(2026, 9, 1, 10))
    vw.db.commit()
    assert _alive(vw, vw.f_sys)  # held: on the system in the hold
    assert not _alive(vw, vw.f_vendor)  # not in the hold's scope
    vault.release_hold(vw.db, vw.chief, hold, "Matter settled")
    vault.run_daily(vw.db, vw.settings, datetime(2026, 9, 2, 10))
    vw.db.commit()
    assert not _alive(vw, vw.f_sys)


def test_a_whole_client_hold_blocks_everything(vw):
    vault.place_hold(vw.db, vw.chief, vw.org, name="Regulator inquiry", matter_ref="AG-22", reason="r", scope={})
    vw.db.commit()
    for d in (datetime(2026, 6, 1, 10), datetime(2027, 6, 1, 10)):
        vault.run_daily(vw.db, vw.settings, d)
        purge_expired_raw_data(vw.db, vw.settings, d)
    vw.db.commit()
    assert all(_alive(vw, f) for f in (vw.f_sys, vw.f_vendor, vw.f_gov, vw.f_bias))
    assert vault.org_on_hold(vw.db, vw.org.id)


def test_a_legal_hold_blocks_the_bias_raw_data_purge(vw):
    """The existing F11 job (raw applicant rows deleted at the end of the engagement retention period) honours holds."""
    hold = vault.place_hold(vw.db, vw.chief, vw.org, name="Counsel", matter_ref="M-1", reason="r", scope={"system_ids": [vw.sys.id]})
    vw.db.commit()
    assert purge_expired_raw_data(vw.db, vw.settings, datetime(2026, 6, 1, 10)) == 0
    vw.db.commit()
    vw.db.refresh(vw.run)
    assert vw.run.dataset_file_id == vw.f_bias.id and vw.run.raw_deleted_at is None and _alive(vw, vw.f_bias)
    vault.release_hold(vw.db, vw.chief, hold, "Settled")
    assert purge_expired_raw_data(vw.db, vw.settings, datetime(2026, 6, 2, 10)) == 1
    vw.db.commit()
    assert not _alive(vw, vw.f_bias)


def test_a_hold_outside_its_date_range_does_not_hold(vw):
    vault.place_hold(vw.db, vw.chief, vw.org, name="Counsel", matter_ref="M-1", reason="r", scope={"from": "2024-01-01"})
    vw.db.commit()
    assert vault.hold_for(vw.db, vw.org.id, engagement_id=vw.e_old.id, system_ids=[], on_date=date(2019, 3, 1)) is None
    assert vault.hold_for(vw.db, vw.org.id, engagement_id=vw.e_old.id, system_ids=[], on_date=date(2025, 3, 1)) is not None


def test_storage_metering_feeds_g01_usage(vw):
    assert vault.storage_used_gb(vw.db, vw.org.id) == pytest.approx(3.0, abs=0.01)
    from app.commercial import plans

    assert plans.MEASURES["vault_gb"](vw.db, vw.org.id, date(2026, 11, 1)) == pytest.approx(3.0, abs=0.01)
    vault.place_hold(vw.db, vw.chief, vw.org, name="Counsel", matter_ref="M-1", reason="r", scope={})
    assert plans.MEASURES["legal_holds"](vw.db, vw.org.id, date(2026, 11, 1)) == 1
    vw.as_(vw.chief)
    v = vw.client.get(f"/api/v1/staff/clients/{vw.org.id}/vault").json()
    assert v["storage"]["used_gb"] == pytest.approx(3.0, abs=0.01)
