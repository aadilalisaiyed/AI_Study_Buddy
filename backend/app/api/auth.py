from secrets import token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, password_hash
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.user import UserCreate, UserResponse
from app.services import auth_sessions as sessions

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
_dummy_hash = hash_password(token_urlsafe(32))


def token(user, row):
    return TokenResponse(access_token=create_access_token(user.id, row.id),
                         expires_in=get_settings().access_token_expire_minutes * 60)


def address(request):
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserResponse, status_code=201)
def register(user_data: UserCreate, request: Request, db: Session = Depends(get_db)):
    sessions.throttle(address(request), "register")
    email = str(user_data.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    with sessions.password_slot():
        user = User(name=user_data.name, email=email, hashed_password=hash_password(user_data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email already registered") from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(request: Request, response: Response, username: Annotated[str, Form(max_length=320)],
          password: Annotated[str, Form(max_length=128)], db: Session = Depends(get_db)):
    email = username.strip().lower()
    sessions.throttle(address(request), "login")
    origin = request.headers.get("origin")
    if origin:
        sessions.origin_allowed(request)
    user = db.scalar(select(User).where(User.email == email))
    with sessions.password_slot():
        if user is None:
            password_hash.verify(password, _dummy_hash)
            verified = False
        else:
            verified = password_hash.verify(password, user.hashed_password)
    if not verified or not user.is_active:
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    return token(user, sessions.start(db, response, user))


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    sessions.origin_allowed(request)
    sessions.throttle(address(request), "refresh")
    row = sessions.from_cookie(db, request)
    user = db.get(User, row.user_id) if row else None
    if not user or not user.is_active:
        raise sessions.credentials_error()
    sessions.rotate(response, row)
    db.commit()
    return token(user, row)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sessions.origin_allowed(request)
    row = sessions.from_cookie(db, request)
    if row:
        row.revoked_at = sessions.now()
        db.commit()
    response.delete_cookie(sessions.COOKIE, path=sessions.PATH, httponly=True,
                           secure=get_settings().production, samesite="lax")
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=UserResponse)
def get_my_profile(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
