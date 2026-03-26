"""ROI calculator service (P0-81)."""


def calculate_roi(
    questionnaires_per_year: int = 50,
    avg_questions_per_questionnaire: int = 200,
    hourly_cost: float = 75.0,
    hours_per_questionnaire: float = 8.0,
    subscription_monthly: float = 399.0,
) -> dict:
    """Calculate ROI for Trust Copilot vs. manual questionnaire handling."""
    total_manual_hours = questionnaires_per_year * hours_per_questionnaire
    total_manual_cost = total_manual_hours * hourly_cost

    tc_hours_per_q = 0.5
    total_tc_hours = questionnaires_per_year * tc_hours_per_q
    annual_subscription = subscription_monthly * 12
    total_tc_cost = annual_subscription + (total_tc_hours * hourly_cost)

    hours_saved = total_manual_hours - total_tc_hours
    dollars_saved = total_manual_cost - total_tc_cost
    roi_multiple = round(dollars_saved / annual_subscription, 1) if annual_subscription else 0
    time_reduction_pct = round((1 - tc_hours_per_q / hours_per_questionnaire) * 100, 1)

    return {
        "inputs": {
            "questionnaires_per_year": questionnaires_per_year,
            "avg_questions": avg_questions_per_questionnaire,
            "hourly_cost": hourly_cost,
            "hours_per_questionnaire": hours_per_questionnaire,
            "subscription_monthly": subscription_monthly,
        },
        "manual": {
            "total_hours_per_year": total_manual_hours,
            "total_cost_per_year": total_manual_cost,
        },
        "with_trust_copilot": {
            "total_hours_per_year": total_tc_hours,
            "subscription_annual": annual_subscription,
            "total_cost_per_year": round(total_tc_cost, 2),
        },
        "savings": {
            "hours_saved_per_year": hours_saved,
            "dollars_saved_per_year": round(dollars_saved, 2),
            "roi_multiple": roi_multiple,
            "time_reduction_pct": time_reduction_pct,
        },
    }
