"""Platform settings › AI provider (F1, 11-03 notes). The Futran Admin and the Chief Auditor read it; only the Futran Admin
saves, tests or removes it. Responses never carry the key, only its last four characters."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import connection
from app.ai.client import AIError, ai_status, connected_provider
from app.ai.providers import CATALOGUE, LABELS
from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Conflict, Forbidden
from app.policy.actions import Action
from app.policy.authorize import authorize

router = APIRouter(tags=["ai"])

TEST_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def _can_manage(db: Session, actor: Actor) -> bool:
    try:
        authorize(db, actor, Action.MANAGE_AI_CONNECTION)
        return True
    except Forbidden:
        return False


def out(db: Session, request: Request, actor: Actor) -> dict:
    s = request.app.state.settings
    row = connection.get(db)
    return {
        "connected": row is not None,
        "provider": row.provider if row else None,
        "provider_label": LABELS.get(row.provider) if row else None,
        "model": row.model if row else None,
        "endpoint": row.endpoint if row else None,
        "deployment": row.deployment if row else None,
        "key_hint": row.key_hint if row else None,
        "key_unreadable": bool(row and not connection.key_readable(s, row)),
        "updated_at": row.updated_at.isoformat() if row else None,
        "last_test": {"at": row.last_tested_at.isoformat(), "ok": row.last_test_ok, "message": row.last_test_message} if row and row.last_tested_at else None,
        "active": ai_status(request.app.state, s, db),
        "demo_mode": s.ai_client == "fake",
        "stand_in": s.ai_provider_http == "fake",
        "providers": CATALOGUE,
        "can_manage": _can_manage(db, actor),
    }


@router.get("/admin/ai-connection")
def get_connection(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.VIEW_PLATFORM_SETTINGS)
    return out(db, request, actor)


class ConnectionIn(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str | None = None
    endpoint: str | None = None
    deployment: str | None = None


@router.put("/admin/ai-connection")
def save_connection(body: ConnectionIn, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_AI_CONNECTION)
    connection.save(db, request.app.state.settings, actor.user, body.model_dump())
    return out(db, request, actor)


@router.delete("/admin/ai-connection")
def remove_connection(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    authorize(db, actor, Action.MANAGE_AI_CONNECTION)
    connection.remove(db, actor.user)
    return out(db, request, actor)


@router.post("/admin/ai-connection/test")
def test_connection(request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """One small JSON call to the saved provider. The result is a fixed message; provider error bodies are never shown."""
    authorize(db, actor, Action.MANAGE_AI_CONNECTION)
    row = connection.get(db)
    if row is None:
        raise Conflict("Save an AI provider first.")
    s = request.app.state.settings
    provider = connected_provider(request.app.state, s, db)
    if provider is None:
        ok, message = False, "The saved API key cannot be read with the server's current secret. Enter the key again."
    else:
        try:
            reply = provider.complete(task="connection_test", system="You check that a connection works. Reply with JSON only.",
                                      prompt='Reply with {"ok": true}.', schema=TEST_SCHEMA, max_tokens=1024)
            ok, message = True, f"Connected. {LABELS.get(row.provider, row.provider)} answered with model {reply.model}."
        except AIError as e:
            ok, message = False, str(e)
        except Exception as e:  # noqa: BLE001 - an SDK failure is reported by type only
            ok, message = False, f"The AI provider could not be reached ({type(e).__name__})."
    connection.record_test(db, actor.user, row, ok, message)
    return {"ok": ok, "message": message, "connection": out(db, request, actor)}
