from datetime import date

from fastapi import APIRouter, Query, Response

from app.api.documents import DB, Owner
from app.services.analytics_service import period, report

router = APIRouter(prefix="/api/v1/analytics", tags=["Learning analytics"])


@router.get("/overview")
def overview(owner: Owner, db: DB, response: Response, days: int = Query(30, ge=1, le=366),
             start_date: date | None = None, end_date: date | None = None,
             timezone: str | None = Query(None, max_length=100), offset: int = Query(0, ge=0),
             limit: int = Query(30, ge=1, le=100)):
    response.headers["Cache-Control"] = "private, no-store"
    return report(db, owner.id, period(db, owner.id, days, start_date, end_date, timezone), offset, limit)
