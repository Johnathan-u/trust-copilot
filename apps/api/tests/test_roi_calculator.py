"""Tests for ROI calculator (P0-81)."""

import pytest
from app.services import roi_calculator_service as roi


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return client


class TestROICalculatorService:
    def test_default_calculation(self):
        result = roi.calculate_roi()
        assert "inputs" in result
        assert "manual" in result
        assert "with_trust_copilot" in result
        assert "savings" in result

    def test_positive_savings(self):
        result = roi.calculate_roi(
            questionnaires_per_year=50,
            hours_per_questionnaire=8,
            hourly_cost=75,
        )
        assert result["savings"]["dollars_saved_per_year"] > 0
        assert result["savings"]["hours_saved_per_year"] > 0

    def test_roi_multiple(self):
        result = roi.calculate_roi()
        assert result["savings"]["roi_multiple"] > 0

    def test_time_reduction(self):
        result = roi.calculate_roi()
        assert result["savings"]["time_reduction_pct"] > 90

    def test_custom_inputs(self):
        result = roi.calculate_roi(
            questionnaires_per_year=100,
            avg_questions_per_questionnaire=300,
            hourly_cost=100,
            hours_per_questionnaire=10,
            subscription_monthly=299,
        )
        assert result["inputs"]["questionnaires_per_year"] == 100
        assert result["inputs"]["subscription_monthly"] == 299

    def test_manual_vs_tc_hours(self):
        result = roi.calculate_roi(questionnaires_per_year=20, hours_per_questionnaire=5)
        assert result["manual"]["total_hours_per_year"] == 100
        assert result["with_trust_copilot"]["total_hours_per_year"] == 10


class TestROICalculatorAPI:
    def test_default(self, admin_client):
        r = admin_client.get("/api/roi-calculator")
        assert r.status_code == 200
        data = r.json()
        assert "savings" in data

    def test_custom_params(self, admin_client):
        r = admin_client.get("/api/roi-calculator?questionnaires_per_year=100&hourly_cost=100")
        assert r.status_code == 200
        data = r.json()
        assert data["inputs"]["questionnaires_per_year"] == 100
