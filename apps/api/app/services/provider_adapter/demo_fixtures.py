"""Hand-built demo CRM rows.

These values are fixtures for the rejection boundary. They are not observations
of Salesforce or HubSpot and must never be inserted as deals or evidence.
"""

from __future__ import annotations

DEMO_SALESFORCE_OPPORTUNITIES: tuple[dict, ...] = (
    {
        "external_id": "sf-opp-001",
        "company_name": "Acme Corp",
        "stage": "evaluation",
        "demo": True,
    },
    {
        "external_id": "sf-opp-002",
        "company_name": "Globex Industries",
        "stage": "negotiation",
        "demo": True,
    },
)

DEMO_HUBSPOT_DEALS: tuple[dict, ...] = (
    {
        "external_id": "hs-deal-001",
        "company_name": "StartupCo",
        "stage": "discovery",
        "demo": True,
    },
)
