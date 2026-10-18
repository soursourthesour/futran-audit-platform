from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

MIN_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Words that make up most breached passwords of 12+ characters. The check is offline, so it works without network access.
BREACHED_WORDS = (
    "password", "passw0rd", "qwerty", "asdfgh", "zxcvbn", "iloveyou", "letmein", "welcome", "admin", "abc123", "monkey", "dragon",
    "football", "baseball", "sunshine", "princess", "trustno1", "changeme", "default", "secret", "master", "shadow", "superman", "batman",
)
KEYBOARD_ROWS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")


def _is_trivial(password: str) -> bool:
    p = password.casefold()
    core = "".join(ch for ch in p if ch.isalpha())
    digits = "".join(ch for ch in p if ch.isdigit())
    if len(set(p)) <= 2:
        return True
    if any(w in p for w in BREACHED_WORDS) and len(core) <= len(max((w for w in BREACHED_WORDS if w in p), key=len)) + 2:
        return True  # a common word plus digits or symbols, such as Password12345 or iloveyou2026!
    if any(row[i:i + 6] in p for row in KEYBOARD_ROWS for i in range(len(row) - 5)) and len(set(p)) < 14:
        return True
    return bool(digits) and digits == p and len(set(digits)) <= 10 and p in "12345678901234567890" * 2


def validate_password(password: str, email: str) -> list[str]:
    errors = []
    if len(password) < MIN_LENGTH:
        errors.append(f"Use at least {MIN_LENGTH} characters.")
    if password.strip().lower() == email.strip().lower():
        errors.append("Do not use your email address as your password.")
    elif len(password) >= MIN_LENGTH and _is_trivial(password):
        errors.append("This password is too common or appears in breached-password lists. Choose another.")
    return errors
