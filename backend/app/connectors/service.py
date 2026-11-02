"""Integrations and automated AI discovery (spec §21 F2, screen 30).

Authorization of a connector:
- OAuth (Entra ID, Microsoft 365, Google Workspace). The `state` sent to the provider is signed, names the connector,
  carries a nonce whose hash is kept on the connector (single use), and is bound to the browser session and the user
  that started it: the response is accepted only in that session, from that user, while they may still manage
  integrations. What the provider grants is checked, not trusted: the tenant must have verified one of the
  organisation's own email domains (those of its users who have signed in) and must not be connected to another
  organisation. For Microsoft the tenant is proven by the administrator's sign-in after admin consent (the ID token's
  tenant), never taken from the consent redirect (see adapters/microsoft.py).
- Okta. The client's Okta admin installs Futran's API service integration with read scopes and gives the Client Admin a
  client ID and secret; the org's users must be in the organisation's own domains, and the Okta org must not be
  connected to another organisation.
Read-only scopes only (see each adapter). Tokens and Okta credentials are encrypted with the email integration's Fernet
helper (app.mail.tokens). Disconnecting revokes what the provider allows and deletes what is stored.

Discovery: a sync or upload produces `Observation`s (one per AI product × signal × department); each becomes or updates a
`DiscoveredTool`. Browsing data keeps no person. "Undeclared" means not declared in the organisation's latest
attestation campaign.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.connectors import csvparse, vendors
from app.connectors.adapters import LABELS, PROVIDER_OF, ConnectorError, get_adapter
from app.connectors.adapters.okta import clean_domain
from app.connectors.models import OAUTH_TYPES, TYPES, UPLOAD_TYPES, Connector, ConnectorRun, DiscoveredTool, DiscoveredToolUser
from app.connectors.signals import Observation, aggregate, describe as _detail
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError, Conflict, Forbidden, Invalid, NotFound
from app.inventory.models import AITool
from app.mail import tokens
from app.tenancy.models import Department, Organization, RoleAssignment, User

STATE_MAX_AGE = 3600
SIGNAL_LABELS = {"sso_app": "SSO app", "oauth_grant": "OAuth grant", "licence": "Licence", "expense": "Expense", "traffic": "Network traffic"}
ACCOUNT_FOR_SIGNAL = {"sso_app": "enterprise", "licence": "enterprise", "expense": "personal_paid", "oauth_grant": "unknown", "traffic": "unknown"}
MIN_REASON = 10


class BadRequest(AppError):
    status_code = 400


def _h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="connector-oauth")


def connector(db: Session, org: Organization, ctype: str, create: bool = True) -> Connector | None:
    if ctype not in TYPES:
        raise NotFound()
    c = db.scalar(select(Connector).where(Connector.organization_id == org.id, Connector.type == ctype, Connector.deleted_at.is_(None)))
    if c is None and create:
        c = Connector(organization_id=org.id, type=ctype, status="not_connected", scopes=[], verified_domains=[])
        db.add(c)
        db.flush()
    return c


def own_domains(db: Session, org: Organization) -> set[str]:
    """The organisation's own email domains: those of its users who have accepted their invitation and signed in. An
    invited user's address was typed by the Client Admin and proves nothing; nor does anything else typed into a form."""
    emails = db.scalars(select(User.email).where(User.organization_id == org.id, User.deleted_at.is_(None), User.status == "active"))
    return {e.rsplit("@", 1)[1].lower() for e in emails if e and "@" in e}


def _may_manage(db: Session, user: User, org: Organization) -> bool:
    from app.auth.deps import Actor, roles_of
    from app.policy.actions import Action
    from app.policy.authorize import authorize

    if user is None or user.organization_id != org.id or user.status != "active" or user.deleted_at is not None:
        return False
    try:
        authorize(db, Actor(user=user, organization=org, roles=roles_of(db, user.id)), Action.MANAGE_INTEGRATIONS, org_id=org.id)
        return True
    except (Forbidden, NotFound):
        return False


def _adapter(settings: Settings, ctype: str):
    a = get_adapter(settings, ctype)
    if a is None:
        raise Conflict(f"{LABELS[ctype]} is not set up on this platform yet. Futran IT must register the read-only discovery app and add its client ID and "
                       "secret to the configuration.")
    return a


def _refuse(db: Session, conn: Connector, actor_id: str | None, message: str, field: str | None = None):
    """A connection attempt that failed. A connector already connected keeps its stored access, which still works: the
    failed attempt is logged and shown on the connector, and the next successful sync clears it."""
    if conn.status == "connected" and conn.token_encrypted:
        conn.error = f"The latest attempt to connect again failed: {message} The existing connection still works."[:500]
        audit.record(db, actor_id=actor_id, action="connector.refused", obj=conn,
                     summary=f"{LABELS[conn.type]} reconnection failed; the existing connection was kept: {message[:200]}")
    else:
        conn.status, conn.error = "error", message[:500]
        audit.record(db, actor_id=actor_id, action="connector.refused", obj=conn, summary=f"{LABELS[conn.type]} not connected: {message[:200]}")
    db.flush()
    if field:
        raise Invalid(errors=[{"field": field, "message": message}])
    raise BadRequest(message)


def _check_ownership(db: Session, conn: Connector, org: Organization, actor_id: str | None, tenant: str | None, domains: list[str], adapter, grant: dict) -> None:
    label = LABELS[conn.type]
    own = own_domains(db, org)
    if not own & set(domains):
        try:
            adapter.revoke(grant)
        except ConnectorError:
            pass
        _refuse(db, conn, actor_id, f"This {label} organisation has not verified {org.name}'s email domain ({', '.join(sorted(own)) or 'none on record'}). "
                                    f"Approve access from {org.name}'s own {label} account.")
    family = [t for t, p in PROVIDER_OF.items() if p == PROVIDER_OF.get(conn.type)] or [conn.type]
    if tenant and db.scalar(select(Connector.id).where(Connector.tenant_id == tenant, Connector.type.in_(family), Connector.organization_id != org.id,
                                                       Connector.deleted_at.is_(None)).limit(1)):
        _refuse(db, conn, actor_id, f"This {label} organisation is already connected to another organisation on the platform. Each organisation connects its own.")


def _connected(db: Session, settings: Settings, conn: Connector, user: User, grant: dict, adapter, tenant: str, domains: list[str]) -> Connector:
    tokens.store(settings, conn, grant)
    conn.status, conn.error, conn.scopes = "connected", None, adapter.scopes()
    conn.tenant_id, conn.verified_domains = tenant, domains
    conn.authorized_by, conn.authorized_by_name, conn.authorized_at = user.id, user.name, utcnow()
    audit.record(db, actor_id=user.id, action="connector.connected", obj=conn,
                 summary=f"Connected {LABELS[conn.type]} with read-only access ({', '.join(conn.scopes)})")
    db.flush()
    return conn


# ---------------------------------------------------------------- OAuth connectors
def start_consent(db: Session, settings: Settings, user: User, session_id: str | None, org: Organization, ctype: str, login_hint: str | None = None) -> str:
    if ctype not in OAUTH_TYPES:
        raise Invalid(errors=[{"field": "type", "message": "This connector is not connected through a sign-in."}])
    if not session_id:
        raise BadRequest("Sign in again, then connect.")
    adapter = _adapter(settings, ctype)
    conn = connector(db, org, ctype)
    nonce = secrets.token_urlsafe(16)
    state = _serializer(settings).dumps({"c": conn.id, "n": nonce, "u": user.id, "s": _h(session_id), "p": PROVIDER_OF[ctype]})
    conn.oauth_state_hash = _h(nonce)
    if conn.status in ("not_connected", "disconnected", "error"):
        conn.status = "consent_requested"
    audit.record(db, actor_id=user.id, action="connector.consent_started", obj=conn, summary=f"Started connecting {LABELS[ctype]}")
    db.flush()
    return adapter.consent_url(state=state, login_hint=login_hint or user.email)


def load_state(settings: Settings, state: str) -> dict:
    try:
        return _serializer(settings).loads(state or "", max_age=STATE_MAX_AGE)
    except SignatureExpired as exc:
        raise BadRequest("This sign-in has expired. Start the connection again.") from exc
    except BadSignature as exc:
        raise BadRequest("This sign-in response is not valid.") from exc


def check_state_owner(data: dict, *, session_id: str | None, user_id: str | None) -> None:
    """A sign-in state is used only in the browser session, and by the user, that started it."""
    if not session_id or _h(session_id) != data.get("s") or not user_id or user_id != data.get("u"):
        raise BadRequest("Finish connecting in the same browser you started from, signed in to the Futran Audit Platform as the person who started it.")


def complete_consent(db: Session, settings: Settings, provider: str, params: dict, *, session_id: str | None, user_id: str | None) -> Connector | str:
    """Finish a provider's redirect. Returns the connected connector, or, after Microsoft's admin consent, the URL of the
    administrator's sign-in that proves the tenant (the browser goes there next)."""
    data = load_state(settings, params.get("state", ""))
    if data.get("p") != provider:
        raise BadRequest("This sign-in response is not valid.")
    conn = db.get(Connector, data.get("c"))
    if conn is None or conn.oauth_state_hash is None or conn.oauth_state_hash != _h(data.get("n", "")):
        raise BadRequest("This sign-in response has already been used or was replaced by a newer request.")
    check_state_owner(data, session_id=session_id, user_id=user_id)
    conn.oauth_state_hash = None  # single use, whatever happens next
    org = db.get(Organization, conn.organization_id)
    user = db.get(User, user_id)
    if not _may_manage(db, user, org):
        _refuse(db, conn, user_id, "You no longer have permission to manage integrations for this organisation.")
    adapter = _adapter(settings, conn.type)
    two_step = getattr(adapter, "proves_tenant_by_sign_in", False)
    try:
        if two_step and data.get("ph") != "signin":
            # Microsoft: the tenant in the admin-consent redirect is only a claim. Sign the administrator in next; the
            # ID token's tenant must match it. The consented tenant travels in the signed state, bound like the first.
            tenant = adapter.consent_tenant(params=params)
            nonce = secrets.token_urlsafe(16)
            conn.oauth_state_hash = _h(nonce)
            state = _serializer(settings).dumps({"c": conn.id, "n": nonce, "u": user.id, "s": data["s"], "p": data["p"], "ph": "signin", "t": tenant})
            audit.record(db, actor_id=user.id, action="connector.consent_given", obj=conn,
                         summary=f"Admin consent given in {LABELS[conn.type]}; the administrator's sign-in confirms the tenant")
            db.flush()
            return adapter.signin_url(state=state, nonce=_h(nonce), login_hint=user.email)
        grant = adapter.complete_consent(params=params, tenant=data.get("t"), nonce=_h(data.get("n", ""))) if two_step else adapter.complete_consent(params=params)
    except ConnectorError as exc:
        _refuse(db, conn, user_id, str(exc))
    domains = list(dict.fromkeys(d.lower() for d in grant.get("domains") or [] if d))
    tenant = str(grant.get("tenant") or "") or None
    _check_ownership(db, conn, org, user_id, tenant, domains, adapter, grant)
    return _connected(db, settings, conn, user, grant, adapter, tenant, domains)


# ---------------------------------------------------------------- Okta
def connect_okta(db: Session, settings: Settings, user: User, org: Organization, domain: str | None, client_id: str | None, client_secret: str | None) -> Connector:
    conn = connector(db, org, "okta")
    d = clean_domain(domain)
    errs = []
    if d is None:
        errs.append({"field": "domain", "message": "Enter your Okta domain, for example yourcompany.okta.com."})
    if not (client_id or "").strip():
        errs.append({"field": "client_id", "message": "Enter the client ID from the Futran integration in your Okta Admin Console."})
    if not (client_secret or "").strip():
        errs.append({"field": "client_secret", "message": "Enter the client secret Okta showed when the integration was installed."})
    if errs:
        raise Invalid(errors=errs)
    adapter = _adapter(settings, "okta")
    try:
        grant = adapter.connect(domain=d, client_id=client_id.strip(), client_secret=client_secret.strip())
    except ConnectorError as exc:
        _refuse(db, conn, user.id, str(exc), field="client_secret")
    domains = list(dict.fromkeys(x.lower() for x in grant.get("domains") or [] if x))
    _check_ownership(db, conn, org, user.id, d, domains, adapter, grant)
    return _connected(db, settings, conn, user, grant, adapter, d, domains)


def disconnect(db: Session, settings: Settings, user: User, conn: Connector) -> Connector:
    adapter = get_adapter(settings, conn.type)
    if adapter is not None and conn.token_encrypted:
        try:
            adapter.revoke(tokens.load(settings, conn))
        except (ConnectorError, tokens.TokenError):
            pass
    tokens.clear(conn)
    conn.status, conn.tenant_id, conn.verified_domains, conn.scopes, conn.oauth_state_hash, conn.error = "disconnected", None, [], [], None, None
    note = " Remove the Futran discovery app in Microsoft Entra ID to withdraw the consent itself." if PROVIDER_OF.get(conn.type) == "microsoft" else ""
    audit.record(db, actor_id=user.id, action="connector.disconnected", obj=conn, summary=f"Disconnected {LABELS[conn.type]}; stored tokens deleted.{note}")
    db.flush()
    return conn


# ---------------------------------------------------------------- departments
def _norm(name: str | None) -> str:
    v = (name or "").lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", v).split())


ALIASES = {"human resources": "hr", "people": "hr", "people and culture": "hr", "information technology": "it", "engineering and it": "it"}


def match_department(name: str | None, depts: list[Department]) -> Department | None:
    n = _norm(name)
    if not n:
        return None
    by = {_norm(d.name): d for d in depts}
    if n in by:
        return by[n]
    a = ALIASES.get(n, n)
    for k, d in by.items():
        if ALIASES.get(k, k) == a:
            return d
    initials = "".join(w[0] for w in n.split() if w != "and")
    return next((d for k, d in by.items() if k == initials or "".join(w[0] for w in k.split() if w != "and") == n), None)


# ---------------------------------------------------------------- ingest
def ingest(db: Session, conn: Connector, observations: list[Observation], now: datetime) -> int:
    depts = list(db.scalars(select(Department).where(Department.organization_id == conn.organization_id, Department.deleted_at.is_(None))))
    merged: dict[tuple[str, str, str], tuple[Observation, Department | None]] = {}
    for o in observations:
        if vendors.by_key(o.vendor_key) is None:
            continue
        d = match_department(o.department, depts)
        key = d.id if d else (f"name:{_norm(o.department)}" if o.department else "unknown")
        k = (o.vendor_key, o.signal, key)
        if k not in merged:
            merged[k] = (Observation(o.vendor_key, o.signal, o.department, o.user_count, o.count, list(o.details), dict(o.people) if o.people is not None else None), d)
            continue
        m = merged[k][0]  # two source names for one department ("HR", "Human Resources"): one row
        if m.people is not None and o.people is not None:
            anon = (m.user_count - len(m.people)) + (o.user_count - len(o.people))
            m.people.update({p: nm for p, nm in o.people.items() if p not in m.people or not m.people[p]})
            m.user_count = len(m.people) + anon
        else:
            m.user_count += o.user_count
        m.count += o.count
        m.details = sorted(set(m.details) | set(o.details))
    n = 0
    for (vendor_key, signal, key), (o, d) in merged.items():
        v = vendors.by_key(vendor_key)
        o.detail = _detail(o)
        row = db.scalar(select(DiscoveredTool).where(DiscoveredTool.connector_id == conn.id, DiscoveredTool.vendor_key == v.key, DiscoveredTool.signal == o.signal,
                                                     DiscoveredTool.department_key == key))
        if row is None:
            row = DiscoveredTool(organization_id=conn.organization_id, connector_id=conn.id, vendor_key=v.key, signal=o.signal, department_key=key, first_seen=now, status="new")
            db.add(row)
        row.vendor, row.product, row.category = v.vendor, v.product, v.category
        row.department_id, row.department_name = (d.id if d else None), (o.department or None)
        row.user_count, row.detail, row.last_seen = o.user_count, o.detail, now
        db.flush()
        db.execute(delete(DiscoveredToolUser).where(DiscoveredToolUser.discovered_tool_id == row.id))
        for person, name in (o.people or {}).items():
            db.add(DiscoveredToolUser(organization_id=conn.organization_id, discovered_tool_id=row.id, email=person if "@" in person else None, name=name or (None if "@" in person else person)))
        n += 1
    db.flush()
    return n


def _finish_run(db: Session, settings: Settings, conn: Connector, run: ConnectorRun, now: datetime) -> ConnectorRun:
    run.status, run.finished_at = "completed", now
    conn.last_sync_at, conn.error = now, None
    db.flush()
    from app.monitoring.service import after_sync

    after_sync(db, settings, db.get(Organization, conn.organization_id), run)
    return run


def sync(db: Session, settings: Settings, conn: Connector, user: User | None = None, now: datetime | None = None) -> ConnectorRun:
    now = now or utcnow()
    if conn.status != "connected" or conn.type in UPLOAD_TYPES:
        raise Conflict(f"Connect {LABELS[conn.type]} first.")
    run = ConnectorRun(organization_id=conn.organization_id, connector_id=conn.id, kind="sync", started_at=now, status="running", started_by=user.id if user else None)
    db.add(run)
    db.flush()
    adapter = _adapter(settings, conn.type)
    try:
        grant = tokens.load(settings, conn)
        signals = adapter.collect(grant)
    except (ConnectorError, tokens.TokenError) as exc:
        run.status, run.finished_at, run.error = "failed", utcnow(), str(exc)[:500]
        conn.error = str(exc)[:500]
        audit.record(db, actor_id=user.id if user else None, actor_name=None if user else "Scheduler", action="connector.sync_failed", obj=conn,
                     summary=f"{LABELS[conn.type]} sync failed: {str(exc)[:200]}")
        db.flush()
        return run
    if grant.pop("_refreshed", False):
        tokens.store(settings, conn, grant)
    obs = aggregate(signals, keep_people=True)
    run.rows_read, run.rows_matched = len(signals), len(signals)
    run.tools_found = ingest(db, conn, obs, now)
    audit.record(db, actor_id=user.id if user else None, actor_name=None if user else "Scheduler", action="connector.synced", obj=conn,
                 summary=f"{LABELS[conn.type]} sync: {run.tools_found} AI tool and department pairs")
    return _finish_run(db, settings, conn, run, now)


def upload(db: Session, settings: Settings, user: User, org: Organization, ctype: str, filename: str | None, data: bytes, now: datetime | None = None) -> ConnectorRun:
    if ctype not in UPLOAD_TYPES:
        raise NotFound()
    now = now or utcnow()
    parsed = (csvparse.parse_expense if ctype == "expense_csv" else csvparse.parse_casb)(data)
    conn = connector(db, org, ctype)
    conn.status = "connected"
    conn.authorized_by, conn.authorized_by_name, conn.authorized_at = user.id, user.name, now
    run = ConnectorRun(organization_id=org.id, connector_id=conn.id, kind="upload", started_at=now, status="running", started_by=user.id, filename=(filename or "upload.csv")[:255],
                       rows_read=parsed.rows_read, rows_matched=parsed.rows_matched)
    db.add(run)
    db.flush()
    run.tools_found = ingest(db, conn, parsed.observations, now)
    audit.record(db, actor_id=user.id, action="connector.uploaded", obj=conn,
                 summary=f"{LABELS[ctype]} file {run.filename}: {parsed.rows_read} rows, {parsed.rows_matched} matched to AI vendors (file not kept)")
    return _finish_run(db, settings, conn, run, now)


# ---------------------------------------------------------------- declared or not
def declared_keys(db: Session, org_id: str) -> tuple[set[str], bool]:
    """Vendor keys declared in the organisation's latest attestation campaign, and whether there is one at all."""
    from app.attestation.models import Attestation, AttestationCampaign

    camp = db.scalar(select(AttestationCampaign).where(AttestationCampaign.organization_id == org_id, AttestationCampaign.deleted_at.is_(None))
                     .order_by(AttestationCampaign.launched_at.desc()).limit(1))
    if camp is None:
        return set(), False
    keys: set[str] = set()
    for a in db.scalars(select(Attestation).where(Attestation.campaign_id == camp.id, Attestation.superseded_by_id.is_(None), Attestation.deleted_at.is_(None))):
        for t in a.tools_declared or []:
            v = vendors.for_attestation_value(t.get("tool")) or vendors.match_name(t.get("name"))
            if v is not None:
                keys.add(v.key)
    return keys, True


# ---------------------------------------------------------------- decisions
def _load_tool(db: Session, org: Organization, tool_id: str) -> DiscoveredTool:
    t = db.get(DiscoveredTool, tool_id)
    if t is None or t.organization_id != org.id or t.deleted_at is not None:
        raise NotFound()
    return t


def _leads_for(db: Session, org_id: str, department_id: str | None) -> list[User]:
    q = select(User).join(RoleAssignment, RoleAssignment.user_id == User.id).where(User.organization_id == org_id, RoleAssignment.deleted_at.is_(None))
    leads = list(db.scalars(q.where(RoleAssignment.role == "dept_compliance_lead", RoleAssignment.scope_id == department_id))) if department_id else []
    return leads or list(db.scalars(q.where(RoleAssignment.role == "caico")))


def confirm(db: Session, settings: Settings, user: User, org: Organization, tool_id: str) -> DiscoveredTool:
    t = _load_tool(db, org, tool_id)
    if t.status in ("confirmed", "mapped"):
        raise Conflict("This tool is already in the AI inventory.")
    existing = db.scalar(select(AITool).where(AITool.organization_id == org.id, AITool.deleted_at.is_(None), func.lower(AITool.vendor) == t.vendor.lower(),
                                              func.lower(AITool.product) == t.product.lower()).limit(1))
    tool = existing or AITool(organization_id=org.id, vendor=t.vendor, product=t.product, account_type=ACCOUNT_FOR_SIGNAL.get(t.signal, "unknown"), source="discovery",
                              approval_status="unreviewed", created_by=user.id)
    if existing is None:
        db.add(tool)
        db.flush()
    t.status, t.matched_tool_id, t.decided_by, t.decided_at, t.dismiss_reason = "confirmed", tool.id, user.id, utcnow(), None
    audit.record(db, actor_id=user.id, action="discovered_tool.confirmed", obj=t,
                 summary=f"Confirmed {t.product} ({_dept_label(db, t)}, {t.user_count} people) and {'linked it to' if existing else 'added it to'} the AI inventory")
    from app.notifications.service import notify

    dept = _dept_label(db, t)
    notify(db, _leads_for(db, org.id, t.department_id), "discovered_tool_confirmed", f"Add the use case for {t.product}",
           f"{t.product} was found through {LABELS[db.get(Connector, t.connector_id).type]} in {dept} ({t.user_count} people) and confirmed by {user.name}. "
           "Describe what it is used for in the AI inventory.", "/inventory/new", settings=settings)
    db.flush()
    return t


def map_to_tool(db: Session, user: User, org: Organization, tool_id: str, ai_tool_id: str | None) -> DiscoveredTool:
    t = _load_tool(db, org, tool_id)
    target = db.get(AITool, ai_tool_id) if isinstance(ai_tool_id, str) else None
    if target is None or target.organization_id != org.id or target.deleted_at is not None:
        raise Invalid(errors=[{"field": "ai_tool_id", "message": "Choose a tool from your AI inventory."}])
    t.status, t.matched_tool_id, t.decided_by, t.decided_at, t.dismiss_reason = "mapped", target.id, user.id, utcnow(), None
    audit.record(db, actor_id=user.id, action="discovered_tool.mapped", obj=t, summary=f"Mapped {t.product} ({_dept_label(db, t)}) to {target.vendor} {target.product}")
    db.flush()
    return t


def dismiss(db: Session, user: User, org: Organization, tool_id: str, reason: str | None) -> DiscoveredTool:
    t = _load_tool(db, org, tool_id)
    reason = " ".join((reason or "").split())
    if len(reason) < MIN_REASON:
        raise Invalid(errors=[{"field": "reason", "message": "Say why this is not an AI tool your people use for work. The Futran auditor sees the reason."}])
    t.status, t.dismiss_reason, t.decided_by, t.decided_at, t.matched_tool_id = "dismissed", reason[:1000], user.id, utcnow(), None
    audit.record(db, actor_id=user.id, action="discovered_tool.dismissed", obj=t, summary=f"Dismissed {t.product} ({_dept_label(db, t)}): {reason[:200]}")
    db.flush()
    return t


# ---------------------------------------------------------------- named-user checks
def tier_of_tool(db: Session, org_id: str, ai_tool_id: str | None) -> int | None:
    """The highest tier of a use case or register system that uses this inventory tool."""
    if not ai_tool_id:
        return None
    from app.inventory.models import UseCase
    from app.register.models import RegisterSystem

    tiers = []
    for uc in db.scalars(select(UseCase).where(UseCase.organization_id == org_id, UseCase.deleted_at.is_(None))):
        if ai_tool_id in (uc.tool_ids or []):
            tiers.append(uc.final_tier or uc.proposed_tier or 0)
    for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org_id, RegisterSystem.deleted_at.is_(None))):
        if f"tool:{ai_tool_id}" in (s.source_refs or []):
            tiers.append(s.risk_tier or 0)
    return max(tiers) if tiers else None


def people_for_auditor(db: Session, actor, org: Organization, tool_id: str) -> list[dict]:
    t = _load_tool(db, org, tool_id)
    if t.signal == "traffic":
        raise Forbidden("Network traffic is kept as department totals only; no names are stored.")
    tier = tier_of_tool(db, org.id, t.matched_tool_id)
    if tier is None or tier < 2:
        raise Forbidden("Names are shown only for tools used in a Tier 2 or Tier 3 use case, for the named-user check.")
    rows = db.scalars(select(DiscoveredToolUser).where(DiscoveredToolUser.discovered_tool_id == t.id).order_by(DiscoveredToolUser.name, DiscoveredToolUser.email))
    out = [{"name": r.name, "email": r.email} for r in rows]
    audit.record(db, actor_id=actor.id, action="discovered_tool.people_viewed", obj=t,
                 summary=f"Viewed the {len(out)} people behind {t.product} ({_dept_label(db, t)}) for the Tier {tier} named-user check")
    db.flush()
    return out


# ---------------------------------------------------------------- read models
def _dept_label(db: Session, t: DiscoveredTool) -> str:
    if t.department_id:
        d = db.get(Department, t.department_id)
        if d is not None:
            return d.name
    return t.department_name or "Department not recorded"


def tool_out(db: Session, t: DiscoveredTool, conn: Connector, declared: set[str], has_campaign: bool, tools_by_id: dict[str, AITool], systems_by_tool: dict[str, str]) -> dict:
    matched = tools_by_id.get(t.matched_tool_id) if t.matched_tool_id else None
    src = LABELS[conn.type]
    sig = f"{src} · {t.detail}" if t.signal in ("expense", "traffic") and t.detail else (f"{src} {SIGNAL_LABELS[t.signal]}" + (f" ({t.detail})" if t.detail else ""))
    return {"id": t.id, "vendor": t.vendor, "product": t.product, "category": t.category, "signal": t.signal, "signal_label": sig, "source": conn.type, "source_label": src,
            "department_id": t.department_id, "department": _dept_label(db, t), "department_matched": bool(t.department_id), "user_count": t.user_count, "detail": t.detail,
            "declared": t.vendor_key in declared, "attestation_exists": has_campaign, "status": t.status, "dismiss_reason": t.dismiss_reason,
            "matched_tool": {"id": matched.id, "label": f"{matched.vendor} {matched.product}"} if matched else None,
            "system_reference": systems_by_tool.get(matched.id) if matched else None, "first_seen": t.first_seen.isoformat(), "last_seen": t.last_seen.isoformat(),
            "decided_at": t.decided_at.isoformat() if t.decided_at else None}


def tools(db: Session, org: Organization) -> list[dict]:
    declared, has_campaign = declared_keys(db, org.id)
    conns = {c.id: c for c in db.scalars(select(Connector).where(Connector.organization_id == org.id, Connector.deleted_at.is_(None)))}
    by_id = {a.id: a for a in db.scalars(select(AITool).where(AITool.organization_id == org.id, AITool.deleted_at.is_(None)))}
    from app.register.models import RegisterSystem

    systems: dict[str, str] = {}
    for s in db.scalars(select(RegisterSystem).where(RegisterSystem.organization_id == org.id, RegisterSystem.deleted_at.is_(None)).order_by(RegisterSystem.reference)):
        for ref in s.source_refs or []:
            if isinstance(ref, str) and ref.startswith("tool:"):
                systems.setdefault(ref[5:], s.reference)
    rows = db.scalars(select(DiscoveredTool).where(DiscoveredTool.organization_id == org.id, DiscoveredTool.deleted_at.is_(None))
                      .order_by(DiscoveredTool.status != "new", DiscoveredTool.product, DiscoveredTool.department_name))
    return [tool_out(db, t, conns[t.connector_id], declared, has_campaign, by_id, systems) for t in rows if t.connector_id in conns]


def connector_out(db: Session, c: Connector, settings: Settings) -> dict:
    last = db.scalar(select(ConnectorRun).where(ConnectorRun.connector_id == c.id).order_by(ConnectorRun.started_at.desc()).limit(1))
    return {"id": c.id, "type": c.type, "label": LABELS[c.type], "status": c.status, "scopes": c.scopes or [], "tenant": c.tenant_id, "verified_domains": c.verified_domains or [],
            "authorized_by": c.authorized_by_name, "authorized_at": c.authorized_at.isoformat() if c.authorized_at else None,
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None, "error": c.error,
            "last_run": {"kind": last.kind, "status": last.status, "at": last.started_at.isoformat(), "filename": last.filename, "rows_read": last.rows_read,
                         "rows_matched": last.rows_matched, "tools_found": last.tools_found, "error": last.error} if last else None}


def runs(db: Session, org: Organization, limit: int = 50) -> list[dict]:
    conns = {c.id: c for c in db.scalars(select(Connector).where(Connector.organization_id == org.id))}
    rows = db.scalars(select(ConnectorRun).where(ConnectorRun.organization_id == org.id).order_by(ConnectorRun.started_at.desc()).limit(limit))
    out = []
    for r in rows:
        u = db.get(User, r.started_by) if r.started_by else None
        out.append({"id": r.id, "connector": LABELS[conns[r.connector_id].type], "kind": r.kind, "status": r.status, "started_at": r.started_at.isoformat(),
                    "by": u.name if u else "Scheduled", "filename": r.filename, "rows_read": r.rows_read, "rows_matched": r.rows_matched, "tools_found": r.tools_found,
                    "error": r.error})
    return out
