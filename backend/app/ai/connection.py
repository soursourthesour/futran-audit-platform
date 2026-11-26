"""The platform's AI connection (F1, 11-03 notes): one provider, model and API key for every AI feature, chosen by the
Futran Admin in Platform settings. One platform-wide row (plan ruling: not per client).

Claude Platform on AWS (26 Nov 2026) adds a region, a workspace ID and how requests are signed: with an API key (sealed
like the others) or with the server's AWS role, in which case no key is stored (`key_encrypted`, `key_ref` and
`key_hint` are empty strings, so the existing columns stay NOT NULL).

The key is sealed with the email integration's token key (app.mail.tokens: TOKEN_ENCRYPTION_KEY, else derived from
SECRET_KEY). Only its last four characters are kept in clear, as a hint. The key never leaves the server, and the audit
log records what changed without it. Removing the connection deletes the row, key included.
"""
import re
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import Boolean, DateTime, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.ai.providers import CATALOGUE, LABELS, ConnectionConfig
from app.ai.providers import anthropic_aws as aws
from app.ai.providers.azure_openai import AZURE_HOST_SUFFIXES
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Invalid
from app.core.models import Base, IdMixin
from app.mail import tokens

PROVIDERS = {p["id"] for p in CATALOGUE}
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,79}$")
DEPLOYMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class AIConnection(IdMixin, Base):
    __tablename__ = "ai_connections"

    provider: Mapped[str] = mapped_column(String(20))  # anthropic | anthropic_aws | openai | azure_openai | gemini
    model: Mapped[str] = mapped_column(String(80))
    endpoint: Mapped[str | None] = mapped_column(String(300))  # Azure OpenAI resource endpoint; Claude Platform on AWS gateway (optional)
    deployment: Mapped[str | None] = mapped_column(String(80))  # Azure OpenAI deployment name
    auth_mode: Mapped[str | None] = mapped_column(String(20))  # Claude Platform on AWS: api_key | aws_role; None for the others
    aws_region: Mapped[str | None] = mapped_column(String(40))  # Claude Platform on AWS
    aws_workspace_id: Mapped[str | None] = mapped_column(String(120))  # Claude Platform on AWS
    key_encrypted: Mapped[str] = mapped_column(Text)
    key_ref: Mapped[str] = mapped_column(String(40))  # which key sealed it (app.mail.tokens)
    key_hint: Mapped[str] = mapped_column(String(12))  # "…" and the key's last four characters
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36))


def get(db: Session) -> AIConnection | None:
    return db.scalar(select(AIConnection).order_by(AIConnection.created_at).limit(1))


def config(settings, row: AIConnection | None) -> ConnectionConfig | None:
    """The saved connection with its key, or None when there is none or the key cannot be read with the current secret
    (then features fall back as if nothing were connected, and the screen asks for the key again)."""
    if row is None:
        return None
    if uses_aws_role(row):
        key = ""
    else:
        try:
            key = tokens.unseal(settings, row.key_encrypted)
        except tokens.TokenError:
            return None
    return ConnectionConfig(provider=row.provider, model=row.model, api_key=key, endpoint=row.endpoint, deployment=row.deployment,
                            auth_mode=row.auth_mode or aws.API_KEY, region=row.aws_region, workspace_id=row.aws_workspace_id)


def uses_aws_role(row: AIConnection | None) -> bool:
    """Claude Platform on AWS signing with the server's AWS credentials: no key is stored."""
    return row is not None and row.provider == "anthropic_aws" and row.auth_mode == aws.AWS_ROLE


def key_readable(settings, row: AIConnection) -> bool:
    return config(settings, row) is not None


def _hint(key: str) -> str:
    return "…" + key[-4:]


def _clean_endpoint(value: str) -> str:
    p = urlparse(value.strip())
    return f"https://{(p.hostname or '').lower()}" + (f":{p.port}" if p.port else "")


def save(db: Session, settings, actor, body: dict) -> AIConnection:
    errors: list[dict] = []
    provider = str(body.get("provider") or "").strip()
    model = str(body.get("model") or "").strip()
    key = body.get("api_key")
    key = str(key).strip() if key is not None else ""
    endpoint = str(body.get("endpoint") or "").strip()
    deployment = str(body.get("deployment") or "").strip()
    auth_mode = str(body.get("auth_mode") or aws.API_KEY).strip()
    region = str(body.get("aws_region") or "").strip().lower()
    workspace = str(body.get("aws_workspace_id") or "").strip()
    row = get(db)

    if provider not in PROVIDERS:
        errors.append({"field": "provider", "message": "Choose Anthropic Claude, Claude Platform on AWS, OpenAI, Azure OpenAI or Google Gemini."})
    if provider == "azure_openai":
        p = urlparse(endpoint)
        host = (p.hostname or "").lower()
        if not endpoint:
            errors.append({"field": "endpoint", "message": "Enter the resource endpoint from the Azure portal, for example https://your-resource.openai.azure.com."})
        elif p.scheme != "https" or not host.endswith(AZURE_HOST_SUFFIXES):
            errors.append({"field": "endpoint", "message": "Use the https address of an Azure OpenAI resource (ending openai.azure.com, services.ai.azure.com or cognitiveservices.azure.com)."})
        if not DEPLOYMENT_RE.match(deployment):
            errors.append({"field": "deployment", "message": "Enter the deployment name exactly as it appears in Azure AI Foundry."})
        model = model or deployment
    elif provider == "anthropic_aws":
        deployment = ""
        if auth_mode not in aws.AUTH_MODES:
            errors.append({"field": "auth_mode", "message": "Choose an API key or the server's AWS role."})
        if not aws.REGION_RE.match(region):
            errors.append({"field": "aws_region", "message": "Enter the AWS Region the workspace is in, for example us-east-1."})
        if not aws.WORKSPACE_RE.match(workspace):
            errors.append({"field": "aws_workspace_id", "message": "Enter the workspace ID from the AWS Console (Claude Platform on AWS, Workspaces), starting wrkspc_."})
        if endpoint:
            if not aws.gateway_url_ok(endpoint):
                errors.append({"field": "endpoint", "message": "Use the https address of the Claude Platform on AWS gateway, such as https://aws-external-anthropic.us-east-1.api.aws, or leave it blank."})
        if model.startswith(("anthropic.", "us.anthropic.", "eu.anthropic.", "global.anthropic.")):
            errors.append({"field": "model", "message": "Use the Claude model ID, such as claude-sonnet-5-5, not an Amazon Bedrock model ID."})
        if auth_mode == aws.AWS_ROLE and key:
            errors.append({"field": "api_key", "message": "Leave the API key blank: the server's AWS role signs the requests."})
    else:
        endpoint = deployment = ""
    if provider != "anthropic_aws":
        auth_mode, region, workspace = "", "", ""
    role = provider == "anthropic_aws" and auth_mode == aws.AWS_ROLE
    if not MODEL_RE.match(model):
        errors.append({"field": "model", "message": "Enter the model name as the provider writes it, for example gpt-6-astra (letters, digits, dots, dashes)."})
    same_provider = row is not None and row.provider == provider
    has_key = same_provider and not uses_aws_role(row)
    if role:
        pass
    elif key:
        if len(key) < 8 or len(key) > 500 or any(c.isspace() for c in key):
            errors.append({"field": "api_key", "message": "Paste the whole API key, with no spaces."})
    elif not has_key:
        errors.append({"field": "api_key", "message": "Enter the API key for this provider." if row is None or same_provider else "A different provider needs its own API key."})
    if errors:
        raise Invalid(errors=errors)

    before = _snapshot(row)
    if row is None:
        row = AIConnection(created_by=actor.id)
        db.add(row)
    row.provider, row.model = provider, model
    row.endpoint = _clean_endpoint(endpoint) if endpoint else None
    row.deployment = deployment or None
    row.auth_mode, row.aws_region, row.aws_workspace_id = auth_mode or None, region or None, workspace or None
    if role:
        key = ""
        row.key_ref, row.key_encrypted, row.key_hint = "", "", ""
    elif key:
        row.key_ref, row.key_encrypted = tokens.seal(settings, key)
        row.key_hint = _hint(key)
    changed = before is None or {k: v for k, v in before.items() if k != "key_hint"} != {k: v for k, v in _snapshot(row).items() if k != "key_hint"} or bool(key)
    if changed:
        row.last_tested_at = row.last_test_ok = row.last_test_message = None
    row.updated_by = actor.id
    row.updated_at = utcnow()
    db.flush()
    after = _snapshot(row) | {"key_replaced": bool(key)}
    audit.record(db, actor_id=actor.id, action="ai_connection.saved", object_type="AIConnection", object_id=row.id, organization_id=actor.organization_id,
                 before=before, after=after, summary=f"Connected {LABELS[provider]} ({model}) for the platform's AI features"
                 + (" with a new API key" if key else " signing with the server's AWS role" if role else ""))
    return row


def remove(db: Session, actor) -> None:
    row = get(db)
    if row is None:
        return
    before = _snapshot(row)
    db.delete(row)
    db.flush()
    audit.record(db, actor_id=actor.id, action="ai_connection.removed", object_type="AIConnection", object_id=before["id"], organization_id=actor.organization_id,
                 before=before, after=None, summary=f"Removed the {LABELS.get(before['provider'], before['provider'])} connection and deleted its API key")


def record_test(db: Session, actor, row: AIConnection, ok: bool, message: str) -> None:
    row.last_tested_at, row.last_test_ok, row.last_test_message = utcnow(), ok, message[:300]
    db.flush()
    audit.record(db, actor_id=actor.id, action="ai_connection.tested", object_type="AIConnection", object_id=row.id, organization_id=actor.organization_id,
                 after={"ok": ok, "provider": row.provider, "model": row.model, "message": message[:300]},
                 summary=f"Tested the {LABELS.get(row.provider, row.provider)} connection: {'working' if ok else 'failed'}")


def _snapshot(row: AIConnection | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "provider": row.provider, "model": row.model, "endpoint": row.endpoint, "deployment": row.deployment, "key_hint": row.key_hint,
            "auth_mode": row.auth_mode, "aws_region": row.aws_region, "aws_workspace_id": row.aws_workspace_id}
