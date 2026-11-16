from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import decode_access_token
from app.db.models import Dashboard, Dataset, User
from app.services.dataset_store import DatasetStore

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> DatasetStore:
    return request.app.state.store


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> User:
    unauthorized = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    user_id = decode_access_token(creds.credentials, settings.secret_key)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise unauthorized
    return user


def owned_dataset(db: Session, user: User, dataset_id: int) -> Dataset:
    """Other people's datasets look exactly like missing ones (404) so IDs can't be probed."""
    ds = db.get(Dataset, dataset_id)
    if ds is None or ds.owner_id != user.id:
        raise HTTPException(404, "Dataset not found")
    return ds


def owned_dashboard(db: Session, user: User, dashboard_id: int) -> Dashboard:
    d = db.get(Dashboard, dashboard_id)
    if d is None or d.owner_id != user.id:
        raise HTTPException(404, "Dashboard not found")
    return d


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-real-ip")
        if forwarded:
            return forwarded.strip()
    return request.client.host if request.client else "unknown"


def rate_limited(name: str):
    """Dependency factory: `Depends(rate_limited("auth"))` returns 429 when a client is too fast."""

    def dependency(request: Request, settings: Settings = Depends(get_settings_dep)) -> None:
        if not settings.rate_limit_enabled:
            return
        limiter = request.app.state.limiters[name]
        if not limiter.allow(client_ip(request, settings)):
            raise HTTPException(429, "Too many requests - please slow down and try again shortly.")

    return dependency
