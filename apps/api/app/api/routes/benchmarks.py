"""Benchmark dashboard API (P0-84)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import benchmark_service as bs

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.get("")
async def get_benchmarks(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return bs.get_benchmarks(db, session["workspace_id"])
