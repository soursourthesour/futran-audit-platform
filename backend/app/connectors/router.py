"""Screen 30, Integrations and AI discovery (spec §21 F2). Client endpoints take the tenant from the session; Futran
endpoints read a client's discovery under /clients/{client_id}. Every endpoint calls `authorize`."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor, get_settings_dep
from app.connectors import service as svc
from app.connectors.adapters import LABELS, PROVIDER_OF, credentials_status, get_adapter, use_fake
from app.connectors.models import OAUTH_TYPES, UPLOAD_TYPES, Connector
from app.core.db import get_db
from app.core.errors import AppError, Forbidden, Invalid, NotFound
from app.inventory.models import AITool
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization

router = APIRouter(tags=["integrations"])
ORDER = ["okta", "google_workspace", "microsoft_365", "entra_id", "expense_csv", "casb_csv"]


class ConnectIn(BaseModel):
    login_hint: str | None = None


class OktaIn(BaseModel):
    domain: str = ""
    client_id: str = ""
    client_secret: str = ""


class MapIn(BaseModel):
    ai_tool_id: str | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


class BulkIn(BaseModel):
    ids: list[str]
    action: str
    reason: str | None = None


class TestConsentIn(BaseModel):
    state: str
    domain: str | None = None
    tenant: str | None = None
    approve: bool = True


def _client_org(actor: Actor) -> Organization:
    if actor.is_futran:
        raise Forbidden("This screen is for the client's own people. Futran reads it from the client page.")
    return actor.organization


def _may(db: Session, actor: Actor, action: Action, org_id: str) -> bool:
    try:
        authorize(db, actor, action, org_id=org_id)
        return True
    except (Forbidden, NotFound):
        return False


def _page(db: Session, settings, org: Organization, *, can_manage: bool, can_decide: bool) -> dict:
    conns = {c.type: c for c in db.scalars(select(Connector).where(Connector.organization_id == org.id, Connector.deleted_at.is_(None)))}
    connectors = [svc.connector_out(db, conns[t], settings) if t in conns else {"type": t, "label": LABELS[t], "status": "not_connected", "scopes": [], "last_run": None}
                  for t in ORDER]
    tools = svc.tools(db, org)
    ai_tools = [{"id": a.id, "label": f"{a.vendor} {a.product}"} for a in db.scalars(select(AITool).where(AITool.organization_id == org.id, AITool.deleted_at.is_(None))
                                                                                   .order_by(AITool.vendor, AITool.product))]
    summary = {"total": len(tools), "undeclared": sum(1 for t in tools if not t["declared"] and t["status"] != "dismissed"),
               "new": sum(1 for t in tools if t["status"] == "new")}
    return {"organization": {"id": org.id, "name": org.name}, "connectors": connectors, "tools": tools, "runs": svc.runs(db, org), "ai_tools": ai_tools, "summary": summary,
            "credentials": credentials_status(settings), "can_manage": can_manage, "can_decide": can_decide}


# ---------------------------------------------------------------- client screen
@router.get("/integrations")
def page(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _client_org(actor)
    authorize(db, actor, Action.VIEW_INTEGRATIONS, org_id=org.id)
    return _page(db, settings, org, can_manage=_may(db, actor, Action.MANAGE_INTEGRATIONS, org.id), can_decide=_may(db, actor, Action.DECIDE_DISCOVERED_TOOLS, org.id))


def _manage(db: Session, actor: Actor) -> Organization:
    org = _client_org(actor)
    authorize(db, actor, Action.MANAGE_INTEGRATIONS, org_id=org.id)
    return org


@router.post("/integrations/{ctype}/connect")
def connect(ctype: str, body: ConnectIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _manage(db, actor)
    if ctype not in OAUTH_TYPES:
        raise NotFound()
    return {"url": svc.start_consent(db, settings, actor.user, actor.session.id if actor.session else None, org, ctype, login_hint=body.login_hint)}


@router.post("/integrations/okta/credentials")
def okta_credentials(body: OktaIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _manage(db, actor)
    try:
        conn = svc.connect_okta(db, settings, actor.user, org, body.domain, body.client_id, body.client_secret)
    except AppError:
        db.commit()  # keep the failed attempt in the audit log and on the connector
        raise
    return svc.connector_out(db, conn, settings)


def _conn(db: Session, org: Organization, ctype: str) -> Connector:
    c = svc.connector(db, org, ctype, create=False)
    if c is None:
        raise NotFound()
    return c


@router.post("/integrations/{ctype}/sync")
def sync_now(ctype: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _manage(db, actor)
    run = svc.sync(db, settings, _conn(db, org, ctype), actor.user)
    return {"status": run.status, "tools_found": run.tools_found, "error": run.error}


@router.post("/integrations/{ctype}/disconnect")
def disconnect(ctype: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _manage(db, actor)
    return svc.connector_out(db, svc.disconnect(db, settings, actor.user, _conn(db, org, ctype)), settings)


@router.post("/integrations/{ctype}/upload")
def upload(ctype: str, file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _manage(db, actor)
    if ctype not in UPLOAD_TYPES:
        raise NotFound()
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise Invalid(errors=[{"field": "file", "message": f"The file is larger than {settings.max_upload_mb} MB. Split it by month and upload each part."}])
    run = svc.upload(db, settings, actor.user, org, ctype, file.filename, data)
    return {"status": run.status, "rows_read": run.rows_read, "rows_matched": run.rows_matched, "tools_found": run.tools_found}


def _decide(db: Session, actor: Actor) -> Organization:
    org = _client_org(actor)
    authorize(db, actor, Action.DECIDE_DISCOVERED_TOOLS, org_id=org.id)
    return org


def _tool_out(db: Session, settings, org: Organization, tool_id: str) -> dict:
    return next(t for t in svc.tools(db, org) if t["id"] == tool_id)


@router.post("/discovered-tools/bulk")
def bulk(body: BulkIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _decide(db, actor)
    if body.action not in ("confirm", "dismiss"):
        raise Invalid(errors=[{"field": "action", "message": "Choose confirm or dismiss."}])
    done = 0
    for tid in dict.fromkeys(body.ids):
        if body.action == "confirm":
            t = svc._load_tool(db, org, tid)
            if t.status in ("confirmed", "mapped"):
                continue
            svc.confirm(db, settings, actor.user, org, tid)
        else:
            svc.dismiss(db, actor.user, org, tid, body.reason)
        done += 1
    return {"done": done}


@router.post("/discovered-tools/{tool_id}/confirm")
def confirm(tool_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _decide(db, actor)
    svc.confirm(db, settings, actor.user, org, tool_id)
    return _tool_out(db, settings, org, tool_id)


@router.post("/discovered-tools/{tool_id}/map")
def map_tool(tool_id: str, body: MapIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _decide(db, actor)
    svc.map_to_tool(db, actor.user, org, tool_id, body.ai_tool_id)
    return _tool_out(db, settings, org, tool_id)


@router.post("/discovered-tools/{tool_id}/dismiss")
def dismiss(tool_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _decide(db, actor)
    svc.dismiss(db, actor.user, org, tool_id, body.reason)
    return _tool_out(db, settings, org, tool_id)


# ---------------------------------------------------------------- Futran: the client's discovery, read only
def _futran_client(db: Session, actor: Actor, client_id: str, action: Action) -> Organization:
    if not actor.is_futran:
        raise NotFound()
    org = db.get(Organization, client_id)
    if org is None or org.type != "client" or org.deleted_at is not None:
        raise NotFound()
    authorize(db, actor, action, org_id=org.id)
    return org


@router.get("/clients/{client_id}/integrations")
def futran_page(client_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    org = _futran_client(db, actor, client_id, Action.VIEW_INTEGRATIONS)
    out = _page(db, settings, org, can_manage=False, can_decide=False)
    out["can_view_people"] = _may(db, actor, Action.VIEW_DISCOVERY_PEOPLE, org.id)
    return out


@router.get("/clients/{client_id}/discovered-tools/{tool_id}/people")
def people(client_id: str, tool_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = _futran_client(db, actor, client_id, Action.VIEW_DISCOVERY_PEOPLE)
    out = svc.people_for_auditor(db, actor, org, tool_id)
    return {"people": out}


# ---------------------------------------------------------------- OAuth redirects
def _session(db: Session, settings, request: Request):
    from app.auth.sessions import COOKIE_NAME, load_session

    return load_session(db, request.cookies.get(COOKIE_NAME), settings, touch=False)


def _finish(db: Session, settings, provider: str, params: dict, request: Request) -> Connector:
    s = _session(db, settings, request)
    return svc.complete_consent(db, settings, provider, params, session_id=s.id if s else None, user_id=s.user_id if s else None)


@router.get("/connectors/oauth/{provider}")
def oauth_callback(provider: str, request: Request, db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    """Where Microsoft or Google send the browser back. Accepted only in the signed-in session, and from the user, that
    started the connection; the signed, single-use state names the connector."""
    try:
        conn = _finish(db, settings, provider, dict(request.query_params), request)
        db.commit()
        return RedirectResponse(f"{settings.base_url}/integrations?connected={conn.type}", status_code=302)
    except AppError as exc:
        db.commit()
        msg = exc.errors[0]["message"] if exc.errors else exc.detail
        return RedirectResponse(f"{settings.base_url}/integrations?error={quote(str(msg)[:300])}", status_code=302)


@router.post("/connectors/oauth/{provider}/test")
def oauth_test(provider: str, body: TestConsentIn, request: Request, db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    """Test mode only: the platform's own consent page stands in for Microsoft's or Google's."""
    if not use_fake(settings):
        raise NotFound()
    params = {"state": body.state, "domain": body.domain, "tenant": body.tenant, "admin_consent": "True", "code": "test-code"}
    if not body.approve:
        params["error"] = "access_denied"
    try:
        conn = _finish(db, settings, provider, params, request)
    except AppError:
        db.commit()
        raise
    return {"redirect": f"/integrations?connected={conn.type}"}


@router.get("/connectors/test-consent-info")
def test_consent_info(state: str, request: Request, db: Session = Depends(get_db, scope="function"), settings=Depends(get_settings_dep)):
    if not use_fake(settings):
        raise NotFound()
    data = svc.load_state(settings, state)
    conn = db.get(Connector, data.get("c"))
    if conn is None:
        raise NotFound()
    org = db.get(Organization, conn.organization_id)
    return {"type": conn.type, "label": LABELS[conn.type], "provider": PROVIDER_OF.get(conn.type), "organization": org.name if org else "",
            "scopes": get_adapter(settings, conn.type).scopes()}
