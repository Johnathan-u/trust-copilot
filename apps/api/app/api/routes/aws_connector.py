"""AWS connector API (P1-17, P1-18, P1-19, P1-20, P1-21)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db
from app.services import aws_collector_service as aws

router = APIRouter(prefix="/connectors/aws", tags=["aws-connector"])


class AwsAuthBody(BaseModel):
    access_key_id: str | None = None
    secret_access_key: str | None = None
    region: str = "us-east-1"
    role_arn: str | None = None


@router.post("/authenticate")
async def authenticate(
    body: AwsAuthBody,
    session: dict = Depends(require_can_admin),
):
    return aws.authenticate_aws(body.access_key_id, body.secret_access_key, body.region, body.role_arn)


@router.get("/iam")
async def collect_iam(
    region: str = Query("us-east-1"),
    session: dict = Depends(require_can_admin),
):
    return aws.collect_iam_posture(region)


@router.get("/s3")
async def collect_s3(
    region: str = Query("us-east-1"),
    session: dict = Depends(require_can_admin),
):
    return aws.collect_s3_posture(region)


@router.get("/logging")
async def collect_logging(
    region: str = Query("us-east-1"),
    session: dict = Depends(require_can_admin),
):
    return aws.collect_logging_posture(region)


@router.post("/sync")
async def sync(
    region: str = Query("us-east-1"),
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    return aws.run_aws_sync(db, session["workspace_id"], region)
