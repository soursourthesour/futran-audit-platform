"""E1 Futran mailbox, E2 client mailbox onboarding, OAuth callbacks, per-user mailbox (§27.1) and email settings."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.core.db import get_db
from app.core.errors import AppError, Conflict, Forbidden, Invalid, NotFound
from app.mail import adminlog, connections as cx, directory
from app.mail.groups import ensure_default_groups
from app.mail.models import DirectoryGroup, MailConnection, UserMailConnection
from app.mail.providers import PROVIDER_LABELS, credentials_status, use_fake
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization

router = APIRouter(tags=["email"])


class ConnectIn(BaseModel):
    provider: str
    mailbox_address: str | None = None
    tenant: str | None = None
    next: str | None = None  # personal mailbox only: the same-origin path to return to


class ToIn(BaseModel):
    to: str = ""


class ItIn(BaseModel):
    email: str = ""
    provider: str = "microsoft365"


class SettingsIn(BaseModel):
    per_user_sync: str


class TestConsentIn(BaseModel):
    state: str
    mailbox: str | None = None
    approve: bool = True


def _may(db: Session, actor: Actor, action: Action, **kw) -> bool:
    try:
        authorize(db, actor, action, **kw)
        return True
    except (Forbidden, NotFound):
        return False


def _directory_out(db: Session, conn: MailConnection | None) -> dict | None:
    ds = directory.for_connection(db, conn) if conn is not None else None
    if ds is None:
        return None
    groups = db.scalars(select(DirectoryGroup).where(DirectoryGroup.organization_id == conn.organization_id, DirectoryGroup.deleted_at.is_(None)).order_by(DirectoryGroup.name))
    return {"schedule": ds.schedule, "include_guests": ds.include_guests, "use_directory_groups": ds.use_directory_groups, "department_field": ds.department_field,
            "scope_group": ds.scope_group, "scope_group_name": ds.scope_group_name, "last_run_at": ds.last_run_at.isoformat() if ds.last_run_at else None,
            "people": ds.people, "joined": ds.joined, "left": ds.left, "changed": ds.changed, "status": ds.status, "report": ds.report or {},
            "groups": [{"id": g.directory_id, "name": g.name, "member_count": g.member_count} for g in groups]}


def _send_test(db: Session, settings, actor: Actor, conn: MailConnection, to: str) -> None:
    try:
        cx.send_test(db, settings, actor.user, conn, to or actor.user.email)
    except cx.TestEmailFailed:
        db.commit()  # keep the record and the admin log entry of the failed attempt (§26.7)
        raise


# ---- E1: the Futran mailbox
def _futran(db: Session, actor: Actor, manage: bool = False) -> Organization:
    if not actor.is_futran:
        raise Forbidden()
    authorize(db, actor, Action.MANAGE_FUTRAN_MAILBOX if manage else Action.VIEW_FUTRAN_GROUPS)  # others read only
    return actor.organization


@router.get("/mail/futran")
def futran_status(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _futran(db, actor)
    conn = cx.org_connection(db, org)
    return {"connection": cx.connection_out(conn), "credentials": credentials_status(settings), "can_manage": _may(db, actor, Action.MANAGE_FUTRAN_MAILBOX),
            "per_user_sync": cx.per_user_policy(db, org.id), "email_mode": settings.email_mode}


@router.post("/mail/futran/connect")
def futran_connect(body: ConnectIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _futran(db, actor, manage=True)
    conn = cx.org_connection(db, org, create=True)
    return {"url": cx.start_consent(db, settings, actor.user, conn, provider=body.provider, kind="admin", mailbox=body.mailbox_address, tenant=body.tenant)}


@router.patch("/mail/futran/connection")
def futran_update(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _futran(db, actor, manage=True)
    return cx.connection_out(cx.update(db, actor.user, cx.org_connection(db, org, create=True), data))


@router.post("/mail/futran/test")
def futran_test(body: ToIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _futran(db, actor, manage=True)
    conn = cx.org_connection(db, org, create=True)
    _send_test(db, settings, actor, conn, body.to)
    return {"sent": True}


@router.post("/mail/futran/check-domain")
def futran_check(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _futran(db, actor, manage=True)
    conn = cx.org_connection(db, org)
    if conn is None or not conn.domain:
        raise Conflict("Set the sending mailbox first.")
    cx.domain_check(db, settings, conn)
    return cx.connection_out(conn)


@router.post("/mail/futran/disconnect")
def futran_disconnect(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _futran(db, actor, manage=True)
    conn = cx.org_connection(db, org)
    if conn is None:
        raise NotFound()
    cx.disconnect(db, settings, actor.user, conn)
    return cx.connection_out(conn)


# ---- E2: the client mailbox (the Client Admin, during onboarding; the CAICO sees it)
def _client(db: Session, actor: Actor, manage: bool = False) -> Organization:
    if actor.is_futran:
        raise Forbidden()
    authorize(db, actor, Action.MANAGE_CLIENT_MAILBOX if manage else Action.VIEW_CLIENT_MAILBOX, org_id=actor.organization.id)
    return actor.organization


def _client_out(db: Session, settings, actor: Actor, org: Organization) -> dict:
    conn = cx.org_connection(db, org)
    d = _directory_out(db, conn)
    step = 1
    if conn is not None and conn.status == "connected":
        step = max(2, conn.onboarding_step or 2)
    from app.mail.delivery import futran_connection

    fut = futran_connection(db)
    return {"connection": cx.connection_out(conn), "directory": d, "step": step, "credentials": credentials_status(settings),
            "can_manage": _may(db, actor, Action.MANAGE_CLIENT_MAILBOX, org_id=org.id), "futran_sender": fut.mailbox_address if fut else None,
            "organization": org.name, "per_user_sync": cx.per_user_policy(db, org.id), "can_set_user_sync": _may(db, actor, Action.SET_USER_MAIL_SYNC, org_id=org.id)}


@router.get("/mail/client")
def client_status(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    return _client_out(db, settings, actor, _client(db, actor))


@router.post("/mail/client/connect")
def client_connect(body: ConnectIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    conn = cx.org_connection(db, org, create=True)
    return {"url": cx.start_consent(db, settings, actor.user, conn, provider=body.provider, kind="admin", mailbox=body.mailbox_address, tenant=body.tenant)}


@router.post("/mail/client/request-it")
def client_request_it(body: ItIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    cx.request_it(db, settings, actor.user, cx.org_connection(db, org, create=True), body.email, body.provider)
    return {"sent": True}


@router.patch("/mail/client/connection")
def client_update(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    cx.update(db, actor.user, cx.org_connection(db, org, create=True), data)
    return _client_out(db, settings, actor, org)


@router.post("/mail/client/directory")
def client_directory(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    conn = cx.org_connection(db, org)
    if conn is None or conn.status != "connected":
        raise Conflict("Connect your email system first.")
    fields = ("schedule", "include_guests", "use_directory_groups", "department_field", "scope_group")
    ds = directory.for_connection(db, conn)
    before = {k: getattr(ds, k) for k in fields} if ds else None
    ds = directory.configure(db, actor.user, conn, data)
    changed = [k for k in fields if before is None or before[k] != getattr(ds, k)]
    if changed:
        words = {"schedule": f"sync {dict(daily='daily', weekly='weekly', off='off').get(ds.schedule, 'every 6 hours')}",
                 "include_guests": "guests and contractors included" if ds.include_guests else "guests and contractors left out",
                 "use_directory_groups": "directory groups used as a source" if ds.use_directory_groups else "directory groups not used",
                 "department_field": f"department from the {ds.department_field} field", "scope_group": f"only people in {ds.scope_group_name}" if ds.scope_group else "everyone in the directory"}
        adminlog.write(db, organization_id=org.id, category="directory", action="settings", actor=actor.user, summary="Directory sync settings: " + "; ".join(words[k] for k in changed))
    return _client_out(db, settings, actor, org)


@router.post("/mail/client/directory/sync")
def client_directory_sync(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    conn = cx.org_connection(db, org)
    if conn is None or conn.status != "connected":
        raise Conflict("Connect your email system first.")
    ds = directory.for_connection(db, conn) or directory.configure(db, actor.user, conn, {})
    directory.run_directory_sync(db, settings, ds, actor=actor.user)
    conn.onboarding_step = max(conn.onboarding_step or 1, 3)
    if ds.status != "ok":
        db.commit()  # keep the failed run and its admin log entry (§26.7)
        raise Conflict(f"The directory sync did not finish: {(ds.report or {}).get('error', 'unknown error')}")
    return _directory_out(db, conn)


@router.post("/mail/client/test")
def client_test(body: ToIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    conn = cx.org_connection(db, org, create=True)
    _send_test(db, settings, actor, conn, body.to)
    return _client_out(db, settings, actor, org)


@router.post("/mail/client/finish")
def client_finish(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    conn = cx.org_connection(db, org, create=True)
    from app.core.clock import utcnow

    conn.completed_at = conn.completed_at or utcnow()
    ensure_default_groups(db, org.id)
    return _client_out(db, settings, actor, org)


@router.post("/mail/client/disconnect")
def client_disconnect(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client(db, actor, manage=True)
    conn = cx.org_connection(db, org)
    if conn is None:
        raise NotFound()
    cx.disconnect(db, settings, actor.user, conn)
    return _client_out(db, settings, actor, org)


@router.get("/mail/clients/{client_id}/status")
def client_status_for_futran(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The client's email connection, for wizard step 6 (client contacts) and the client page."""
    org = db.get(Organization, client_id)
    if org is None or org.type != "client":
        raise NotFound()
    if not actor.is_futran:
        authorize(db, actor, Action.VIEW_CLIENT_MAILBOX, org_id=client_id)
    elif not _may(db, actor, Action.VIEW_CLIENT_MAILBOX, org_id=client_id):
        authorize(db, actor, Action.CREATE_CLIENT_ENGAGEMENT)  # the person setting the client up in the wizard
        from app.engagements.models import Engagement

        e = db.scalar(select(Engagement).where(Engagement.client_id == client_id, Engagement.deleted_at.is_(None)).order_by(Engagement.created_at.desc()).limit(1))
        if e is not None and e.status not in ("draft", "pending_approval", "returned"):
            raise NotFound()
    conn = cx.org_connection(db, org)
    ds = directory.for_connection(db, conn) if conn else None
    out = cx.connection_out(conn)
    return {"status": out["status"], "provider": out["provider"], "provider_label": out.get("provider_label"), "mailbox_address": out["mailbox_address"],
            "sender_mode": conn.sender_mode if conn else None, "people": ds.people if ds and ds.last_run_at else None,
            "last_sync_at": ds.last_run_at.isoformat() if ds and ds.last_run_at else None, "test_sent_at": out.get("test_sent_at")}


# ---- OAuth redirects
def _session_id(db: Session, settings, request: Request) -> str | None:
    """The browser's signed-in session, if any. A personal mailbox consent must come back to the session that started it."""
    from app.auth.sessions import COOKIE_NAME, load_session

    s = load_session(db, request.cookies.get(COOKIE_NAME), settings, touch=False)
    return s.id if s is not None else None


def _finish(db: Session, settings, provider: str, params: dict, request: Request) -> str:
    path, _ = cx.complete_consent(db, settings, provider, params, session_id=_session_id(db, settings, request))
    return path


@router.get("/mail/oauth/{provider}")
def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    """Where Microsoft or Google send the browser back. An organisation consent needs no sign-in: the signed, single-use
    state identifies the connection (the client's IT admin may approve from an emailed link). A personal mailbox consent
    needs the session that started it."""
    params = dict(request.query_params)
    try:
        path = _finish(db, settings, provider, params, request)
        db.commit()
        return RedirectResponse(f"{settings.base_url}{cx.with_query(path, connected='1')}", status_code=302)
    except AppError as exc:
        db.commit()
        msg = exc.errors[0]["message"] if exc.errors else exc.detail
        return RedirectResponse(f"{settings.base_url}/mail/consent-result?error={quote(str(msg)[:300])}", status_code=302)


@router.post("/mail/oauth/{provider}/test")
def oauth_test_consent(provider: str, body: TestConsentIn, request: Request, db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    """Test mode only: the platform's own consent page stands in for Microsoft's or Google's."""
    if not use_fake(settings):
        raise NotFound()
    params = {"state": body.state, "mailbox": body.mailbox, "admin_consent": "True", "code": "test-code"}
    if not body.approve:
        params["error"] = "access_denied"
    return {"redirect": cx.with_query(_finish(db, settings, provider, params, request), connected="1")}


@router.get("/mail/test-consent-info")
def test_consent_info(state: str, settings=Depends(get_settings_dep), db: Session = Depends(get_db, scope="function")):
    """What the test consent page shows: which organisation asked and for what."""
    if not use_fake(settings):
        raise NotFound()
    data = cx._load_state(settings, state)
    holder = db.get(MailConnection if data["t"] == "org" else UserMailConnection, data["id"])
    if holder is None:
        raise NotFound()
    org = db.get(Organization, holder.organization_id)
    from app.mail.providers import get_adapter

    return {"provider": data["p"], "provider_label": PROVIDER_LABELS.get(data["p"]), "kind": data["k"], "organization": org.name if org else "",
            "mailbox": getattr(holder, "mailbox_address", None) or getattr(holder, "mailbox", None), "scopes": get_adapter(settings, data["p"]).scopes(data["k"])}


# ---- per-user mailbox (§27.1)
def _me_out(db: Session, actor: Actor, settings) -> dict:
    policy = cx.per_user_policy(db, actor.organization.id)
    uc = cx.user_connection(db, actor.user)
    connected = uc is not None and uc.status == "connected"
    org_conn = cx.org_connection(db, actor.organization)
    creds = credentials_status(settings)
    available = any(creds[p]["available"] for p in ("microsoft365", "google"))  # nothing to connect to yet: never block anyone
    prompt = available and policy != "off" and not connected and (policy == "required" or uc is None or uc.status != "declined")
    return {"policy": policy, "prompt": prompt, "required": available and policy == "required" and not connected,
            "connection": None if uc is None or uc.status in ("pending", "declined") else {"status": uc.status, "mailbox": uc.mailbox, "provider": uc.provider,
                                                                                           "provider_label": PROVIDER_LABELS.get(uc.provider), "consented_at": uc.consented_at.isoformat() if uc.consented_at else None},
            "suggested_provider": org_conn.provider if org_conn and org_conn.provider else None, "credentials": creds}


@router.get("/me/mailbox")
def my_mailbox(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    return _me_out(db, actor, settings)


@router.post("/me/mailbox/connect")
def my_mailbox_connect(body: ConnectIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    if cx.per_user_policy(db, actor.organization.id) == "off":
        raise Conflict("Your organization has switched off personal mailbox connections.")
    uc = cx.user_connection(db, actor.user, create=True)
    uc.mailbox = uc.mailbox or actor.user.email
    return {"url": cx.start_consent(db, settings, actor.user, uc, provider=body.provider, kind="user", next_path=body.next,
                                    session_id=actor.session.id if actor.session else None)}


@router.post("/me/mailbox/decline")
def my_mailbox_decline(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    if cx.per_user_policy(db, actor.organization.id) == "required":
        raise Conflict("Your organization asks everyone to connect their mailbox.")
    uc = cx.user_connection(db, actor.user, create=True)
    if uc.status != "connected":
        uc.status = "declined"
    return _me_out(db, actor, settings)


@router.post("/me/mailbox/disconnect")
def my_mailbox_disconnect(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    uc = cx.user_connection(db, actor.user)
    if uc is None:
        raise NotFound()
    cx.disconnect(db, settings, actor.user, uc)
    return _me_out(db, actor, settings)


# ---- settings
@router.get("/mail/settings")
def get_settings(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.SET_USER_MAIL_SYNC, org_id=None if actor.is_futran else actor.organization.id)
    return {"per_user_sync": cx.per_user_policy(db, actor.organization.id)}


@router.patch("/mail/settings")
def set_settings(body: SettingsIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Client Admin for client users; Futran Admin for Futran staff. Always the actor's own organisation."""
    authorize(db, actor, Action.SET_USER_MAIL_SYNC, org_id=None if actor.is_futran else actor.organization.id)
    if body.per_user_sync not in ("required", "optional", "off"):
        raise Invalid(errors=[{"field": "per_user_sync", "message": "Choose required, optional or off."}])
    s = cx.org_settings(db, actor.organization.id, create=True)
    if s.per_user_sync != body.per_user_sync:
        adminlog.write(db, organization_id=actor.organization.id, category="settings", action="per_user_sync", actor=actor.user,
                       summary=f"Personal mailbox connection set to {body.per_user_sync}", details={"from": s.per_user_sync, "to": body.per_user_sync})
        s.per_user_sync = body.per_user_sync
    return {"per_user_sync": s.per_user_sync}

