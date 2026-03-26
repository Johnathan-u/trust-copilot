"""CRM connector service for Salesforce and HubSpot (E1-02, E1-03).

Provides mock sync for both CRM platforms. Real implementations would use
the respective REST APIs with OAuth.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.deal import Deal

logger = logging.getLogger(__name__)


def sync_salesforce(db: Session, workspace_id: int) -> dict:
    """Mock Salesforce opportunity sync."""
    mock_opps = [
        {
            "external_id": "sf-opp-001",
            "company_name": "Acme Corp",
            "contact_name": "Jane Buyer",
            "contact_email": "jane@acme.com",
            "deal_value": 150000,
            "stage": "evaluation",
            "close_date": "2026-06-30",
        },
        {
            "external_id": "sf-opp-002",
            "company_name": "Globex Industries",
            "contact_name": "Bob Procurement",
            "contact_email": "bob@globex.com",
            "deal_value": 85000,
            "stage": "negotiation",
            "close_date": "2026-05-15",
        },
    ]
    synced = []
    for opp in mock_opps:
        existing = db.query(Deal).filter(
            Deal.workspace_id == workspace_id,
            Deal.crm_external_id == opp["external_id"],
        ).first()
        if existing:
            existing.company_name = opp["company_name"]
            existing.deal_value_arr = opp["deal_value"]
            existing.stage = opp["stage"]
            synced.append({"action": "updated", "external_id": opp["external_id"]})
        else:
            deal = Deal(
                workspace_id=workspace_id,
                company_name=opp["company_name"],
                buyer_contact_name=opp["contact_name"],
                buyer_contact_email=opp["contact_email"],
                deal_value_arr=opp["deal_value"],
                stage=opp["stage"],
                crm_source="salesforce",
                crm_external_id=opp["external_id"],
            )
            db.add(deal)
            synced.append({"action": "created", "external_id": opp["external_id"]})
    db.flush()
    return {"source": "salesforce", "synced": len(synced), "details": synced}


def sync_hubspot(db: Session, workspace_id: int) -> dict:
    """Mock HubSpot deal sync."""
    mock_deals = [
        {
            "external_id": "hs-deal-001",
            "company_name": "StartupCo",
            "contact_name": "Alice Security",
            "contact_email": "alice@startupco.io",
            "deal_value": 45000,
            "stage": "discovery",
            "close_date": "2026-07-31",
        },
    ]
    synced = []
    for d in mock_deals:
        existing = db.query(Deal).filter(
            Deal.workspace_id == workspace_id,
            Deal.crm_external_id == d["external_id"],
        ).first()
        if existing:
            existing.company_name = d["company_name"]
            existing.deal_value_arr = d["deal_value"]
            existing.stage = d["stage"]
            synced.append({"action": "updated", "external_id": d["external_id"]})
        else:
            deal = Deal(
                workspace_id=workspace_id,
                company_name=d["company_name"],
                buyer_contact_name=d["contact_name"],
                buyer_contact_email=d["contact_email"],
                deal_value_arr=d["deal_value"],
                stage=d["stage"],
                crm_source="hubspot",
                crm_external_id=d["external_id"],
            )
            db.add(deal)
            synced.append({"action": "created", "external_id": d["external_id"]})
    db.flush()
    return {"source": "hubspot", "synced": len(synced), "details": synced}


def get_sync_status(db: Session, workspace_id: int) -> dict:
    sf_count = db.query(Deal).filter(Deal.workspace_id == workspace_id, Deal.crm_source == "salesforce").count()
    hs_count = db.query(Deal).filter(Deal.workspace_id == workspace_id, Deal.crm_source == "hubspot").count()
    manual = db.query(Deal).filter(Deal.workspace_id == workspace_id, Deal.crm_source.is_(None)).count()
    return {"salesforce": sf_count, "hubspot": hs_count, "manual": manual, "total": sf_count + hs_count + manual}
