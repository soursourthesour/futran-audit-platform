"""The platform's AI connection (F1, 11-03 notes): one provider, model and API key for every AI feature, chosen by the
Futran Admin in Platform settings. One platform-wide row (plan ruling: not per client).

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

    provider: Mapped[str] = mapped_column(String(20))  # anthropic | openai | azure_openai | gemini
    model: Mapped[str] = mapped_column(String(80))
    endpoint: Mapped[str | None] = mapped_column(String(300))  # Azure OpenAI resource endpoint
    deployment: Mapped[str | None] = mapped_column(String(80))  # Azure OpenAI deployment name
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
    try:
        key = tokens.unseal(settings, row.key_encrypted)
    except tokens.TokenError:
        return None
    return ConnectionConfig(provider=row.provider, model=row.model, api_key=key, endpoint=row.endpoint, deployment=row.deployment)


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
    row = get(db)

    if provider not in PROVIDERS:
        errors.append({"field": "provider", "message": "Choose Anthropic Claude, OpenAI, Azure OpenAI or Google Gemini."})
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
    else:
        endpoint = deployment = ""
    if not MODEL_RE.match(model):
        errors.append({"field": "model", "message": "Enter the model name as the provider writes it, for example gpt-6-astra (letters, digits, dots, dashes)."})
    same_provider = row is not None and row.provider == provider
    if key:
        if len(key) < 8 or len(key) > 500 or any(c.isspace() for c in key):
            errors.append({"field": "api_key", "message": "Paste the whole API key, with no spaces."})
    elif not same_provider:
        errors.append({"field": "api_key", "message": "Enter the API key for this provider." if row is None else "A different provider needs its own API key."})
    if errors:
        raise Invalid(errors=errors)

    before = _snapshot(row)
    if row is None:
        row = AIConnection(created_by=actor.id)
        db.add(row)
    row.provider, row.model = provider, model
    row.endpoint = _clean_endpoint(endpoint) if endpoint else None
    row.deployment = deployment or None
    if key:
        row.key_ref, row.key_encrypted = tokens.seal(settings, key)
        row.key_hint = _hint(key)
    changed = before is None or before["provider"] != provider or before["model"] != model or before["endpoint"] != row.endpoint or before["deployment"] != row.deployment or bool(key)
    if changed:
        row.last_tested_at = row.last_test_ok = row.last_test_message = None
    row.updated_by = actor.id
    row.updated_at = utcnow()
    db.flush()
    after = _snapshot(row) | {"key_replaced": bool(key)}
    audit.record(db, actor_id=actor.id, action="ai_connection.saved", object_type="AIConnection", object_id=row.id, organization_id=actor.organization_id,
                 before=before, after=after, summary=f"Connected {LABELS[provider]} ({model}) for the platform's AI features" + (" with a new API key" if key else ""))
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
    return {"id": row.id, "provider": row.provider, "model": row.model, "endpoint": row.endpoint, "deployment": row.deployment, "key_hint": row.key_hint}
