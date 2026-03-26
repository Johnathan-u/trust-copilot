"""Demo proof package API — generate sample artifacts for sales and onboarding."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth_deps import require_session
from app.core.database import get_db
from app.services import demo_proof_service

router = APIRouter(prefix="/demo-proof", tags=["demo-proof"])


@router.get("")
async def get_demo_package(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Generate the full demo proof package including sample questionnaire, coverage report, gap list, and walkthrough."""
    workspace_id = session["workspace_id"]
    return demo_proof_service.generate_demo_package(db, workspace_id)


@router.get("/questionnaire")
async def get_sample_questionnaire(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Get just the sample completed questionnaire."""
    return demo_proof_service._build_sample_questionnaire()


@router.get("/coverage")
async def get_coverage_report(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Get the sample coverage report."""
    q = demo_proof_service._build_sample_questionnaire()
    return demo_proof_service._build_coverage_report(q)


@router.get("/gaps")
async def get_gap_list(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Get the sample gap list."""
    q = demo_proof_service._build_sample_questionnaire()
    return demo_proof_service._build_gap_list(q)


@router.get("/walkthrough")
async def get_walkthrough(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Get the product walkthrough steps."""
    return demo_proof_service._build_walkthrough()
