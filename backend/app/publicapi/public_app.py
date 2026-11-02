"""The public API, version 1 (spec §21 F17), mounted at /api/public/v1 as its own application so its OpenAPI document
(/api/public/v1/openapi.json, page at /api/public/v1/docs) lists the public endpoints only.

Every endpoint takes the caller from `Authorization: Bearer` (app.publicapi.auth.authenticate), checks one scope, and reads
or writes inside the caller's organization only. Findings, management responses and remediation are served only once they
are released to the client (approved findings, from the draft report at stage 7), with the comments shared with the client.
"""
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Conflict, Invalid, NotFound, install_error_handlers
from app.publicapi import auth as A
from app.publicapi.auth import Caller, OAuthError, authenticate, require

PREFIX = "/api/public/v1"
RELEASE_STAGE = 7  # findings and remediation reach the client with the draft report
TOKEN_REQUESTS_PER_MINUTE = 30  # per network address, so a guessed or leaked client id cannot be tried at speed
WRITABLE = ("name", "type", "sourcing", "department_id", "purpose", "users_description", "user_count", "vendor_name", "ai_provider", "model_name", "model_version",
            "hosting", "autonomy", "decision_impact")

router = APIRouter()


def caller(request: Request, db: Session = Depends(get_db, scope="function")) -> Caller:
    return authenticate(request, db)


class Page(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: list[dict]


# ---------------------------------------------------------------- OAuth
@router.post("/oauth/token", tags=["authentication"], summary="Get an access token (OAuth 2.0 client credentials)")
async def token(request: Request, db: Session = Depends(get_db, scope="function")):
    """Send `grant_type=client_credentials` with `client_id` and `client_secret` as form fields or HTTP Basic authentication.
    Optional `scope`: a space-separated subset of the client's scopes. Tokens last one hour."""
    import base64

    from app.core.ratelimit import TooManyRequests, client_ip, limiter

    try:
        limiter(request, "public_api_token", TOKEN_REQUESTS_PER_MINUTE).check(client_ip(request))
    except TooManyRequests:  # as an OAuth error body
        raise OAuthError(429, "rate_limited", "Too many token requests from this address. Wait a minute and try again.", {"Retry-After": "60"}) from None
    form = dict(await request.form())
    basic = None
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("basic "):
        try:
            cid, _, sec = base64.b64decode(auth[6:].strip()).decode().partition(":")
            basic = (cid, sec)
        except (ValueError, UnicodeDecodeError):
            raise OAuthError(400, "invalid_request", "The Basic credentials are not readable.") from None
    out = A.issue_token(request, db, {k: str(v) for k, v in form.items()}, basic)
    return JSONResponse(out, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.get("/me", tags=["authentication"], summary="The API client and its scopes")
def me(c: Caller = Depends(caller)):
    return {"client": c.client.name, "client_id": c.client.client_id, "organization": c.organization.name, "scopes": sorted(c.scopes),
            "rate_limit_per_minute": c.client.rate_limit_per_minute}


# ---------------------------------------------------------------- AI inventory (the AI system register)
def _system_out(db: Session, s) -> dict:
    from app.tenancy.models import Department
    from app.systems.models import Vendor

    dept = db.get(Department, s.department_id) if s.department_id else None
    vendor = db.get(Vendor, s.vendor_id) if s.vendor_id else None
    return {"id": s.id, "reference": s.reference, "name": s.name, "type": s.type, "sourcing": s.sourcing, "stage": s.stage, "department_id": s.department_id,
            "department": dept.name if dept else ("Company-wide" if s.company_wide else None), "purpose": s.purpose, "risk_tier": s.risk_tier, "vendor": vendor.legal_name if vendor else None,
            "ai_provider": s.ai_provider, "model_name": s.model_name, "model_version": s.model_version, "autonomy": s.autonomy, "decision_impact": s.decision_impact,
            "live_since": s.live_since.isoformat() if s.live_since else None, "updated_at": s.updated_at.isoformat() if s.updated_at else None}


def _own_system(db: Session, c: Caller, system_id: str):
    from app.register.models import RegisterSystem

    s = db.get(RegisterSystem, system_id)
    if s is None or s.deleted_at is not None or s.organization_id != c.organization.id:
        raise NotFound()
    return s


def _writable(data: dict) -> dict:
    extra = sorted(k for k in data if k not in WRITABLE)
    if extra:
        raise Invalid(f"These fields cannot be set through the API: {', '.join(extra)}. Stage changes, roles and laws are made in the register.",
                      errors=[{"field": k, "message": "Not settable through the API."} for k in extra])
    return dict(data)


@router.get("/inventory/systems", tags=["inventory"], summary="AI systems in the register", response_model=Page)
def list_systems(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.register.models import RegisterSystem

    require(c, "inventory:read")
    rows = db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == c.organization.id, RegisterSystem.deleted_at.is_(None)).order_by(RegisterSystem.reference))
    return {"data": [_system_out(db, s) for s in rows]}


@router.get("/inventory/systems/{system_id}", tags=["inventory"], summary="One AI system")
def get_system(system_id: str, c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    require(c, "inventory:read")
    return _system_out(db, _own_system(db, c, system_id))


@router.post("/inventory/systems", tags=["inventory"], summary="Add an AI system (stage: proposed)")
def create_system(data: dict, c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.register import service as reg

    require(c, "inventory:write")
    body = _writable(data) | {"stage": "proposed"}
    s = reg.create_system(db, c.owner(db), c.organization, body, origin="api", reason=f"Through API client {c.client.name}")
    return _system_out(db, s)


@router.patch("/inventory/systems/{system_id}", tags=["inventory"], summary="Edit an AI system")
def patch_system(system_id: str, data: dict, c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.register import service as reg

    require(c, "inventory:write")
    s = _own_system(db, c, system_id)
    if s.stage == "retired":
        raise Conflict("A retired system cannot be edited.")
    reg.update_system(db, c.owner(db), s, _writable(data), reason=f"Through API client {c.client.name}", settings=c.request.app.state.settings)
    return _system_out(db, s)


@router.get("/inventory/departments", tags=["inventory"], summary="Departments, for department_id")
def departments(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.tenancy.people import departments as depts

    require(c, "inventory:read")
    return {"data": [{"id": d.id, "name": d.name} for d in depts(db, c.organization)]}


@router.get("/inventory/tools", tags=["inventory"], summary="AI tools in the audit inventory, for tool_ids")
def tools(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.inventory.service import tools_for

    require(c, "inventory:read")
    return {"data": [{"id": t.id, "vendor": t.vendor, "product": t.product, "account_type": t.account_type, "approval_status": t.approval_status} for t in tools_for(db, c.organization.id)]}


# ---------------------------------------------------------------- use case intake
@router.post("/usecases", tags=["use cases"], summary="Submit a new AI use case (saved as a draft for the department to review)")
def create_use_case(data: dict, c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.inventory.service import save_use_case
    from app.tenancy.people import current_engagement

    require(c, "usecases:write")
    e = current_engagement(db, c.organization)
    if e is None:
        raise Conflict("There is no audit in progress to take use cases. Add the system to the register instead.")
    uc = save_use_case(db, c.owner(db), c.organization, e, data)
    return {"id": uc.id, "name": uc.name, "status": uc.status, "proposed_tier": uc.proposed_tier}


# ---------------------------------------------------------------- attestation
@router.get("/attestation/status", tags=["attestation"], summary="Attestation progress (counts only; small counts are masked)")
def attestation_status(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.attestation import service as att
    from app.tenancy.people import current_engagement

    require(c, "attestation:read")
    e = current_engagement(db, c.organization)
    camp = att.current_campaign(db, e) if e else None
    if camp is None:
        return {"campaign": None, "totals": None, "departments": []}
    t = att.tracker(db, None, camp, dept_scope=None, individuals=False)
    cp = {k: v for k, v in t["campaign"].items() if k not in ("link", "department_ids")}
    return {"campaign": cp, "totals": t["totals"], "departments": [{"name": d["name"], "responses": d["responses"]} for d in t["departments"]]}


# ---------------------------------------------------------------- findings and remediation
def _released_engagements(db: Session, c: Caller) -> dict:
    from app.engagements.models import Engagement

    return {e.id: e for e in db.scalars(select(Engagement).where(Engagement.client_id == c.organization.id, Engagement.deleted_at.is_(None),
                                                                    Engagement.status.not_in(["draft", "pending_approval"]), Engagement.stage >= RELEASE_STAGE))}


def _finding_out(db: Session, f, e, detail: bool = False) -> dict:
    from app.remediation.models import ManagementResponse
    from app.systems.models import AISystem

    sys_ = db.get(AISystem, f.ai_system_id) if f.ai_system_id else None
    mr = db.scalar(select(ManagementResponse).where(ManagementResponse.finding_id == f.id, ManagementResponse.deleted_at.is_(None)))
    out = {"id": f.id, "ref": f.ref, "engagement": e.audit_ref, "system": sys_.name if sys_ else None, "title": f.title, "severity": f.severity, "description": f.description,
           "recommendation": f.recommended_remediation, "approved_at": f.approved_at.isoformat() if f.approved_at else None,
           "management_response": {"response": mr.response, "planned_action": mr.planned_action, "due_date": mr.due_date.isoformat() if mr.due_date else None, "status": mr.status} if mr else None}
    if detail:
        from app.comments.service import shared_for_object

        out["comments"] = shared_for_object(db, "finding", f.id)
    return out


@router.get("/findings", tags=["findings"], summary="Findings released to you", response_model=Page)
def list_findings(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.findings.models import Finding

    require(c, "findings:read")
    engs = _released_engagements(db, c)
    rows = db.scalars(select(Finding).where(Finding.engagement_id.in_(list(engs)), Finding.status == "approved", Finding.deleted_at.is_(None)).order_by(Finding.ref)) if engs else []
    return {"data": [_finding_out(db, f, engs[f.engagement_id]) for f in rows]}


@router.get("/findings/{finding_id}", tags=["findings"], summary="One finding, with the comments shared with you")
def get_finding(finding_id: str, c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.findings.models import Finding

    require(c, "findings:read")
    f = db.get(Finding, finding_id)
    engs = _released_engagements(db, c)
    if f is None or f.deleted_at is not None or f.status != "approved" or f.engagement_id not in engs:
        raise NotFound()
    return _finding_out(db, f, engs[f.engagement_id], detail=True)


@router.get("/remediation", tags=["remediation"], summary="Remediation items and their status", response_model=Page)
def list_remediation(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.findings.models import Finding
    from app.remediation.models import RemediationItem

    require(c, "remediation:read")
    engs = _released_engagements(db, c)
    out = []
    for it in db.scalars(select(RemediationItem).where(RemediationItem.engagement_id.in_(list(engs)), RemediationItem.deleted_at.is_(None)).order_by(RemediationItem.created_at)) if engs else []:
        f = db.get(Finding, it.finding_id) if it.finding_id else None
        if f is not None and f.status != "approved":
            continue
        out.append({"id": it.id, "engagement": engs[it.engagement_id].audit_ref, "finding_ref": f.ref if f else None, "action": it.action, "owner": it.owner_name or _name(db, it.owner_user_id),
                    "due_date": it.due_date.isoformat() if it.due_date else None, "status": it.status, "closed_at": it.closed_at.isoformat() if it.closed_at else None})
    return {"data": out}


def _name(db: Session, user_id: str | None) -> str | None:
    from app.tenancy.models import User

    u = db.get(User, user_id) if user_id else None
    return u.name if u else None


# ---------------------------------------------------------------- regulatory updates
@router.get("/updates", tags=["regulatory updates"], summary="Regulatory updates published to you", response_model=Page)
def list_updates(c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    from app.publicapi.updates import published_updates

    require(c, "updates:read")
    return {"data": [{k: v for k, v in u.items() if not k.endswith("_dt")} for u in published_updates(db, c.organization.id)]}


# ---------------------------------------------------------------- AI agent decision logs (F14)
@router.post("/agents/{system_id}/decisions", tags=["agents"], summary="Send an agent's decision log (tracing add-on)")
def push_decisions(system_id: str, body: dict, c: Caller = Depends(caller), db: Session = Depends(get_db, scope="function")):
    """Body: `{"events": [{"time", "action", "tool", "decision": allowed|blocked|escalated, "policy", "approver", "agent", "session", "event_id"}]}`.
    Events whose event_id is already held are skipped. All or nothing: one bad event and nothing is saved."""
    from app.tracing.agents import push

    require(c, "agent_logs:write")
    s = _own_system(db, c, system_id)
    return push(db, c.request.app.state.settings, c.owner(db), s, body.get("events"), c.client.name)


SCOPE_OF = {"list_systems": "inventory:read", "get_system": "inventory:read", "departments": "inventory:read", "tools": "inventory:read", "create_system": "inventory:write",
            "patch_system": "inventory:write", "create_use_case": "usecases:write", "attestation_status": "attestation:read", "list_findings": "findings:read",
            "get_finding": "findings:read", "list_remediation": "remediation:read", "list_updates": "updates:read", "push_decisions": "agent_logs:write"}


# ---------------------------------------------------------------- the application
def build(main: FastAPI) -> FastAPI:
    from app.core.config import VERSION

    sub = FastAPI(title="Futran Audit Platform public API", version=f"1 ({VERSION})", docs_url="/docs", openapi_url="/openapi.json", redoc_url=None,
                  description="REST API for clients' GRC tools. Authenticate with OAuth 2.0 client credentials at /oauth/token, then send "
                              "`Authorization: Bearer <token>`. Webhooks are signed: `X-Futran-Signature: t=<timestamp>,v1=<HMAC-SHA256 of \"<timestamp>.<body>\">`.")
    sub.state = main.state  # one settings object, session factory and rate-limit store
    install_error_handlers(sub)

    @sub.exception_handler(OAuthError)
    async def _oauth(_: Request, exc: OAuthError):
        return exc.response()

    from fastapi.routing import APIRoute

    for r in router.routes:  # the scope each call needs, in the OpenAPI document (x-required-scope) for the reference page
        if isinstance(r, APIRoute) and r.name in SCOPE_OF:
            r.openapi_extra = {**(r.openapi_extra or {}), "x-required-scope": SCOPE_OF[r.name]}
    sub.include_router(router)
    return sub


def mount(main: FastAPI) -> None:
    main.mount(PREFIX, build(main))
