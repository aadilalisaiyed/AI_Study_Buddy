
from pwdlib import PasswordHash

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import get_settings


def create_access_token(user_id: UUID, session_id: UUID | None = None) -> str:
    settings = get_settings()

    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.access_token_expire_minutes
        ),
        "type": "access",
    }

    if session_id is not None:
        payload["sid"] = str(session_id)

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm="HS256",
    )


def access_identity(token: str) -> tuple[UUID, UUID | None]:
    settings = get_settings()

    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp", "type"]},
    )

    if payload.get("type") != "access":
        raise InvalidTokenError("Invalid token type")

    try:
        return UUID(payload["sub"]), UUID(payload["sid"]) if "sid" in payload else None
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidTokenError("Invalid user ID") from exc

def decode_access_token(token: str) -> UUID:
    return access_identity(token)[0]


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(
        plain_password,
        hashed_password,
    )
