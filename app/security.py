"""Password storage and opaque, revocable sessions (no third-party auth dependency)."""

import hashlib
import hmac
import secrets

PASSWORD_ROUNDS = 240_000
SESSION_SECONDS = 7 * 24 * 60 * 60
COOKIE_NAME = "opyt50_session"


def make_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${hashed.hex()}"


def verify_password(password: str, value: str) -> bool:
    try:
        algorithm, rounds, salt, hashed = value.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(check, bytes.fromhex(hashed))
    except (ValueError, TypeError):
        return False


def issue_session() -> tuple[str, str]:
    token = secrets.token_urlsafe(40)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
