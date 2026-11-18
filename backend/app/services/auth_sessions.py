from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from secrets import token_urlsafe
from threading import BoundedSemaphore, Lock
from time import monotonic
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth_session import AuthSession

COOKIE = "study_refresh"
PATH = "/api/v1/auth"
LIMIT = 60
WINDOW = 60
_attempts = OrderedDict()
_lock = Lock()
_hash_slots = BoundedSemaphore(4)


@contextmanager
def password_slot():
    if not _hash_slots.acquire(blocking=False):
        raise HTTPException(429, "Try again later", headers={"Retry-After": "2"})
    try:
        yield
    finally:
        _hash_slots.release()


def throttle(address, operation):
    key = (address, operation)
    timestamp = monotonic()
    with _lock:
        while _attempts and next(iter(_attempts.values()))[0] <= timestamp:
            _attempts.popitem(last=False)
        if key not in _attempts:
            if len(_attempts) >= 4096:
                raise HTTPException(429, "Try again later", headers={"Retry-After": "60"})
            _attempts[key] = (timestamp + WINDOW, 0)
        deadline, count = _attempts[key]
        if count >= LIMIT:
            raise HTTPException(429, "Try again later", headers={"Retry-After": "60"})
        _attempts[key] = (deadline, count + 1)


def now():
    return datetime.now(timezone.utc)


def credentials_error():
    return HTTPException(401, "Invalid or expired session")


def origin_allowed(request):
    if request.headers.get("origin") not in get_settings().cors_origins:
        raise HTTPException(403, "Request origin is not allowed")


def digest(secret):
    return sha256(secret.encode()).hexdigest()


def rotate(response, session):
    secret = token_urlsafe(48)
    session.previous_digest = session.token_digest or None
    session.token_digest = digest(secret)
    response.set_cookie(
        COOKIE, f"{session.id}.{secret}", httponly=True, secure=get_settings().production,
        samesite="lax", path=PATH, max_age=max(0, int((session.expires_at - now()).total_seconds())),
    )
    response.headers["Cache-Control"] = "no-store"


def start(db, response, user):
    row = AuthSession(user_id=user.id, token_digest="", expires_at=now() + timedelta(days=7))
    db.add(row)
    db.flush()
    rotate(response, row)
    db.commit()
    return row


def from_cookie(db, request):
    cookie = request.cookies.get(COOKIE, "")
    identifier, _, secret = cookie.partition(".")
    if len(identifier) != 36 or len(secret) != 64:
        return None
    try:
        key = UUID(identifier)
    except ValueError:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.id == key).with_for_update())
    if row is None or row.revoked_at is not None or row.expires_at <= now():
        return None
    if not hmac.compare_digest(row.token_digest, digest(secret)):
        # A stale bearer on this session invalidates the refresh family.
        if row.previous_digest and hmac.compare_digest(row.previous_digest, digest(secret)):
            row.revoked_at = now()
            db.commit()
        return None
    return row
