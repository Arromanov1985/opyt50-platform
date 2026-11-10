"""Password storage and opaque, revocable sessions."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


# OWASP Password Storage Cheat Sheet minimum Argon2id profile:
# 19 MiB memory, 2 iterations, parallelism 1.
ARGON2 = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Legacy verifier only. Existing PBKDF2 hashes are transparently upgraded after
# the next successful login; new passwords are never written with PBKDF2.
LEGACY_PASSWORD_ROUNDS = 240_000
SESSION_SECONDS = 7 * 24 * 60 * 60
ADMIN_SESSION_SECONDS = 30 * 60
COOKIE_NAME = "opyt50_session"


def make_password_hash(password: str) -> str:
    return ARGON2.hash(password)


def _verify_legacy_pbkdf2(password: str, value: str) -> bool:
    try:
        algorithm, rounds, salt, hashed = value.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        )
        return hmac.compare_digest(check, bytes.fromhex(hashed))
    except (ValueError, TypeError):
        return False


def verify_password(password: str, value: str) -> bool:
    if value.startswith("$argon2id$"):
        try:
            return bool(ARGON2.verify(value, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    return _verify_legacy_pbkdf2(password, value)


def password_needs_rehash(value: str) -> bool:
    if not value.startswith("$argon2id$"):
        return True
    try:
        return ARGON2.check_needs_rehash(value)
    except (VerificationError, InvalidHashError):
        return True


def issue_session() -> tuple[str, str]:
    token = secrets.token_urlsafe(40)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
