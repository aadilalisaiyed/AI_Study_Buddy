
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import access_identity
from app.models.auth_session import AuthSession
from app.services.auth_sessions import now
from app.db.session import get_db
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_error

    try:
        user_id, session_id = access_identity(token)
    except InvalidTokenError:
        raise credentials_error

    if session_id is not None:
        session = db.get(AuthSession, session_id)
        if not session or session.user_id != user_id or session.revoked_at or session.expires_at <= now():
            raise credentials_error
    elif get_settings().production:
        raise credentials_error

    user = db.get(User, user_id)

    if user is None or not user.is_active:
        raise credentials_error

    return user
