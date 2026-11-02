"""Connector authorization (spec §21 F2, with the protections the mail connectors have since the security review): the
OAuth state is bound to the browser session and user that started it and is single use; what the provider grants is
checked against the organisation's own domains and other organisations' tenants; read-only scopes only; tokens are
stored encrypted; disconnect deletes them."""
from urllib.parse import parse_qs, urlparse

import pytest

from app.audit_log.models import AuditLog
from app.connectors import service as svc
from app.connectors.adapters.fake import FAKE
from app.connectors.models import Connector
from app.core.errors import AppError

WRITE_WORDS = ("write", "send", "manage", "modify", "delete", "security", ".all.write")


def _state(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def _start(w, settings, ctype="entra_id", user=None, session="sess-1"):
    user = user or w.admin
    url = svc.start_consent(w.db, settings, user, session, w.org, ctype)
    return _state(url)


def test_consent_connects_and_stores_the_token_encrypted(w, settings):
    st = _start(w, settings)
    conn = svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example", "admin_consent": "True"}, session_id="sess-1", user_id=w.admin.id)
    assert conn.status == "connected" and conn.tenant_id == "fake-tenant-abccorp.example" and conn.verified_domains == ["abccorp.example"]
    assert conn.token_encrypted and "fake-access" not in conn.token_encrypted
    assert conn.authorized_by == w.admin.id and conn.oauth_state_hash is None


@pytest.mark.parametrize("ctype", ["entra_id", "microsoft_365", "google_workspace", "okta"])
def test_every_connector_asks_for_read_only_scopes(w, settings, ctype):
    from app.connectors.adapters import get_adapter

    scopes = get_adapter(settings, ctype).scopes()
    assert scopes
    for s in scopes:
        low = s.lower()
        assert low.endswith(".read") or low.endswith("readonly") or ".read." in low or low.endswith(".read.all"), s
        assert not any(wd in low for wd in WRITE_WORDS if wd != ".all.write"), s


def test_the_state_is_single_use(w, settings):
    st = _start(w, settings)
    svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example", "admin_consent": "True"}, session_id="sess-1", user_id=w.admin.id)
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example", "admin_consent": "True"}, session_id="sess-1", user_id=w.admin.id)


def test_the_state_must_come_back_to_the_same_session(w, settings):
    st = _start(w, settings)
    with pytest.raises(AppError) as exc:
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example"}, session_id="another-session", user_id=w.admin.id)
    assert "same browser" in str(exc.value.detail)
    assert w.db.get(Connector, svc.connector(w.db, w.org, "entra_id").id).status != "connected"


def test_the_state_must_come_back_to_the_same_user(w, settings):
    st = _start(w, settings)
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example"}, session_id="sess-1", user_id=w.caico.id)


def test_a_state_for_one_provider_is_refused_on_another(w, settings):
    st = _start(w, settings, ctype="google_workspace")
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example"}, session_id="sess-1", user_id=w.admin.id)


def test_a_tampered_state_is_refused(w, settings):
    st = _start(w, settings)
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st[:-3] + "abc", "domain": "abccorp.example"}, session_id="sess-1", user_id=w.admin.id)


def test_a_tenant_that_does_not_own_the_organisations_domain_is_refused(w, settings):
    FAKE.tenants["tenant-other"] = ["otherco.example"]
    st = _start(w, settings)
    with pytest.raises(AppError) as exc:
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "tenant": "tenant-other", "domain": "otherco.example"}, session_id="sess-1", user_id=w.admin.id)
    assert "abccorp.example" in str(exc.value.detail)
    conn = svc.connector(w.db, w.org, "entra_id")
    assert conn.status == "error" and conn.token_encrypted is None and conn.tenant_id is None


def test_a_tenant_connected_to_another_organisation_is_refused(w, settings):
    FAKE.tenants["shared-tenant"] = ["abccorp.example", "otherco.example"]
    st_other = svc.start_consent(w.db, settings, w.other_admin, "sess-o", w.other, "entra_id")
    svc.complete_consent(w.db, settings, "microsoft", {"state": _state(st_other), "tenant": "shared-tenant"}, session_id="sess-o", user_id=w.other_admin.id)
    st = _start(w, settings)
    with pytest.raises(AppError) as exc:
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "tenant": "shared-tenant"}, session_id="sess-1", user_id=w.admin.id)
    assert "another organisation" in str(exc.value.detail)


def test_the_same_tenant_may_back_both_microsoft_connectors_of_one_organisation(w, settings):
    for ctype in ("entra_id", "microsoft_365"):
        st = _start(w, settings, ctype=ctype)
        assert svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example"}, session_id="sess-1", user_id=w.admin.id).status == "connected"


def test_a_person_who_lost_the_right_to_manage_integrations_cannot_finish(w, settings):
    from app.tenancy.models import RoleAssignment

    st = _start(w, settings)
    for ra in w.db.query(RoleAssignment).filter_by(user_id=w.admin.id):
        ra.role = "contributor"
    w.db.flush()
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example"}, session_id="sess-1", user_id=w.admin.id)


def test_okta_connects_with_credentials_of_an_org_whose_users_are_the_clients(w, settings):
    conn = svc.connect_okta(w.db, settings, w.admin, w.org, "https://abccorp.okta.com/", "cid", "secret")
    assert conn.status == "connected" and conn.tenant_id == "abccorp.okta.com"
    assert "secret" not in (conn.token_encrypted or "") and conn.token_encrypted


def test_okta_refuses_an_org_whose_users_are_someone_elses(w, settings):
    FAKE.okta_orgs["evil.okta.com"] = ["otherco.example"]
    with pytest.raises(AppError):
        svc.connect_okta(w.db, settings, w.admin, w.org, "evil.okta.com", "cid", "secret")
    assert svc.connector(w.db, w.org, "okta").token_encrypted is None


def test_okta_refuses_a_domain_that_is_not_okta(w, settings):
    with pytest.raises(AppError) as exc:
        svc.connect_okta(w.db, settings, w.admin, w.org, "abccorp.example.com", "cid", "secret")
    assert exc.value.errors[0]["field"] == "domain"


def test_okta_reports_wrong_credentials_without_storing_them(w, settings):
    with pytest.raises(AppError):
        svc.connect_okta(w.db, settings, w.admin, w.org, "abccorp.okta.com", "cid", "wrong")
    conn = svc.connector(w.db, w.org, "okta")
    assert conn.token_encrypted is None and conn.status == "error"


def test_disconnect_deletes_the_token_and_logs_it(w, settings):
    st = _start(w, settings, ctype="google_workspace")
    conn = svc.complete_consent(w.db, settings, "google", {"state": st, "domain": "abccorp.example", "code": "c"}, session_id="sess-1", user_id=w.admin.id)
    svc.disconnect(w.db, settings, w.admin, conn)
    assert conn.status == "disconnected" and conn.token_encrypted is None and conn.token_ref is None and conn.tenant_id is None
    assert FAKE.revoked and FAKE.revoked[0]["type"] == "google_workspace"
    assert w.db.query(AuditLog).filter(AuditLog.action == "connector.disconnected").count() == 1


def test_a_failed_reconnect_keeps_the_working_connection(w, settings):
    st = _start(w, settings)
    conn = svc.complete_consent(w.db, settings, "microsoft", {"state": st, "domain": "abccorp.example", "admin_consent": "True"}, session_id="sess-1", user_id=w.admin.id)
    token, tenant = conn.token_encrypted, conn.tenant_id
    st = _start(w, settings)  # the admin starts again, then cancels on the provider's page
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "error": "access_denied"}, session_id="sess-1", user_id=w.admin.id)
    FAKE.tenants["tenant-other"] = ["otherco.example"]
    st = _start(w, settings)  # or signs in to the wrong tenant
    with pytest.raises(AppError):
        svc.complete_consent(w.db, settings, "microsoft", {"state": st, "tenant": "tenant-other"}, session_id="sess-1", user_id=w.admin.id)
    assert conn.status == "connected" and conn.token_encrypted == token and conn.tenant_id == tenant
    assert "still" in (conn.error or "") and w.db.query(AuditLog).filter(AuditLog.action == "connector.refused").count() == 2
    assert svc.sync(w.db, settings, conn, w.admin).status == "completed" and conn.error is None


def test_a_mistyped_okta_secret_keeps_the_working_connection(w, settings):
    conn = svc.connect_okta(w.db, settings, w.admin, w.org, "abccorp.okta.com", "cid", "s3cret")
    token = conn.token_encrypted
    with pytest.raises(AppError):
        svc.connect_okta(w.db, settings, w.admin, w.org, "abccorp.okta.com", "cid", "wrong")
    assert conn.status == "connected" and conn.token_encrypted == token and "still" in conn.error
    assert svc.sync(w.db, settings, conn, w.admin).status == "completed"
