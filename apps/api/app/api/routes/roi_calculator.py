"""ROI calculator API (P0-81)."""

from fastapi import APIRouter, Query

from app.services import roi_calculator_service as roi

router = APIRouter(prefix="/roi-calculator", tags=["roi-calculator"])


@router.get("")
async def calculate(
    questionnaires_per_year: int = Query(50, ge=1),
    avg_questions: int = Query(200, ge=1),
    hourly_cost: float = Query(75.0, ge=0),
    hours_per_questionnaire: float = Query(8.0, ge=0.1),
    subscription_monthly: float = Query(399.0, ge=0),
):
    return roi.calculate_roi(
        questionnaires_per_year=questionnaires_per_year,
        avg_questions_per_questionnaire=avg_questions,
        hourly_cost=hourly_cost,
        hours_per_questionnaire=hours_per_questionnaire,
        subscription_monthly=subscription_monthly,
    )
