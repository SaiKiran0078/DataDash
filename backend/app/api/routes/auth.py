from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_db, get_settings_dep, rate_limited
from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas import Credentials

router = APIRouter(prefix="/auth", tags=["auth"])

# A real hash used when the email is unknown, so "no such user" takes as long as "wrong password"
# (prevents learning which emails are registered by timing the response).
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _token_response(user: User, settings: Settings) -> dict:
    return {
        "token": create_access_token(user.id, settings.secret_key, settings.token_minutes),
        "user": {"id": user.id, "email": user.email},
    }


@router.post("/register", status_code=201, dependencies=[Depends(rate_limited("auth"))])
def register(body: Credentials, db: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return _token_response(user, settings)


@router.post("/login", dependencies=[Depends(rate_limited("auth"))])
def login(body: Credentials, db: Session = Depends(get_db), settings: Settings = Depends(get_settings_dep)):
    user = db.scalar(select(User).where(User.email == body.email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(401, "Invalid email or password")
    return _token_response(user, settings)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"user": {"id": user.id, "email": user.email}}
