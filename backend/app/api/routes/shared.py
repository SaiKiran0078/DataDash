from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_store, rate_limited
from app.db.models import Dashboard
from app.services.dashboards import render_widgets
from app.services.dataset_store import DatasetStore

router = APIRouter(prefix="/shared", tags=["shared"])


@router.get("/{token}", dependencies=[Depends(rate_limited("shared"))])
def shared_dashboard(token: str, response: Response, db: Session = Depends(get_db), store: DatasetStore = Depends(get_store)):
    """Public, read-only view. Exposes only the dashboard's charts - never raw rows, the schema, or the owner."""
    if not (20 <= len(token) <= 64):
        raise HTTPException(404, "This link is invalid or has been disabled")
    d = db.scalar(select(Dashboard).where(Dashboard.share_token == token))
    if d is None:
        raise HTTPException(404, "This link is invalid or has been disabled")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return {
        "name": d.name,
        "widgets": render_widgets(store.load(d.dataset), d.dataset.schema_json, d.widgets, d.filters),
    }
