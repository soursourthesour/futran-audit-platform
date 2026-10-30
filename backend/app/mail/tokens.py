"""OAuth tokens, encrypted at rest (spec §26.2). The key is TOKEN_ENCRYPTION_KEY when set, otherwise one derived from
SECRET_KEY. `token_ref` records which key encrypted the row, so a later key change is detected rather than misread."""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


class TokenError(Exception):
    pass


class Grant(dict):
    """A token set (access token, refresh token, expiry, tenant, mailbox). `dirty` is set when an adapter refreshes it."""

    dirty: bool = False

    def update_tokens(self, **values) -> None:
        self.update({k: v for k, v in values.items() if v is not None})
        self.dirty = True


def _key_material(settings: Settings) -> tuple[str, str]:
    if settings.token_encryption_key:
        return "token_key", settings.token_encryption_key
    return "secret_key", settings.secret_key


def _fernet(settings: Settings) -> tuple[str, Fernet]:
    label, material = _key_material(settings)
    key = base64.urlsafe_b64encode(hashlib.sha256(("mail-tokens:" + material).encode()).digest())
    fingerprint = hashlib.sha256(key).hexdigest()[:8]
    return f"{label}:{fingerprint}", Fernet(key)


def store(settings: Settings, holder, data: dict) -> None:
    ref, f = _fernet(settings)
    holder.token_encrypted = f.encrypt(json.dumps(dict(data)).encode()).decode()
    holder.token_ref = ref


def load(settings: Settings, holder) -> Grant:
    if not getattr(holder, "token_encrypted", None):
        raise TokenError("No token is stored for this mailbox. Connect it again.")
    ref, f = _fernet(settings)
    try:
        return Grant(json.loads(f.decrypt(holder.token_encrypted.encode())))
    except InvalidToken as exc:
        raise TokenError("The stored token cannot be read with the current encryption key. Connect the mailbox again.") from exc


def save_if_refreshed(settings: Settings, holder, grant: Grant) -> None:
    if grant.dirty:
        store(settings, holder, grant)
        grant.dirty = False


def clear(holder) -> None:
    holder.token_encrypted = None
    holder.token_ref = None
