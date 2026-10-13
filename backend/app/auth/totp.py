import base64
import hashlib

import pyotp
from cryptography.fernet import Fernet

ISSUER = "Futran Audit Platform"


def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("mfa:" + secret_key).encode()).digest())
    return Fernet(key)


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(secret.encode()).decode()


def decrypt_secret(token: str, secret_key: str) -> str:
    return _fernet(secret_key).decrypt(token.encode()).decode()


def provisioning_uri(email: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify_totp(secret: str, code: str, last_used_step: int | None = None, now: float | None = None) -> int | None:
    """Return the matched time step if `code` is valid and newer than `last_used_step`, else None."""
    import hmac
    import time

    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    t = now if now is not None else time.time()
    current = int(t // totp.interval)
    for step in (current - 1, current, current + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None
