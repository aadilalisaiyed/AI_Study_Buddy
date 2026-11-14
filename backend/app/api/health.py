
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db


router = APIRouter(
    prefix="/api/v1",
    tags=["Health"],
)


@router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "ai-study-buddy-backend",
    }


@router.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    try:
        result = db.execute(text("SELECT 1")).scalar_one()

        return {
            "status": "healthy",
            "database": "postgresql",
            "connection": "successful",
            "query_result": result,
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )
